"""Run the configuration tests without Blender."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender" / "scripts"))
from story_config import FORMATS, frame_target, layer_events, positions, project, read_story, schedule


class StoryConfigTests(unittest.TestCase):
    def test_fixture_loading(self):
        story = read_story(ROOT / "examples" / "illustrative-story.json")
        self.assertEqual(len(story["steps"]), 5)
        self.assertEqual(
            [layer["features"][0]["geometry"]["type"] for layer in story["layers"]],
            ["Polygon", "MultiLineString", "Point", "Point"],
        )
        self.assertTrue(all("SYNTHETIC" in f["properties"]["source"]
                            for layer in story["layers"] for f in layer["features"]))

    def test_format_specific_camera_fit(self):
        corners = [(-200, -25), (200, 25)]
        (_, landscape) = frame_target(corners, FORMATS["landscape"], 1.15)
        (_, portrait) = frame_target(corners, FORMATS["portrait"], 1.15)
        self.assertAlmostEqual(landscape, 460)
        self.assertAlmostEqual(portrait * 1080 / 1920, landscape)
        (center, scale) = frame_target(corners, FORMATS["portrait"], 1.15, (50, 0), 1000)
        self.assertEqual(center, (50, 0))
        self.assertAlmostEqual(scale, 500 * 1.15 / (1080 / 1920))

    def test_arbitrary_steps_persist_fade_and_retrace(self):
        steps = [
            {"hold": 15, "layers": {"line": 1}},
            {"hold": 15, "transition": 5, "layers": {"line": 1}},
            {"hold": 15, "transition": 5, "layers": {"line": 0.4}},
            {"hold": 15, "transition": 0, "layers": {}},
            {"hold": 15, "transition": 3, "layers": {"line": 1}},
        ]
        timings = schedule(steps)
        self.assertEqual(timings, [(1, 1, 15), (16, 21, 35), (36, 41, 55), (56, 56, 70), (71, 74, 88)])
        keys, draws = layer_events({"id": "line", "fade": 4, "trace": 8, "delay": 2}, steps, timings)
        self.assertEqual(draws, [(3, 11), (76, 84)])
        self.assertEqual(keys, [(1, 0), (2, 0), (7, 1), (35, 1), (40, 0.4),
                                (55, 0.4), (60, 0), (75, 0), (80, 1)])
        self.assertEqual(schedule([{"hold": 2, "transition": 9}]), [(1, 1, 2)])

    def test_invalid_input(self):
        with self.assertRaisesRegex(ValueError, "WGS 84"):
            project((2400000, 6900000), (0, 0))
        with self.assertRaisesRegex(ValueError, "closing point"):
            list(positions({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [2, 2], [3, 3]]]}))
        with self.assertRaisesRegex(ValueError, "Hold must be positive"):
            schedule([{"hold": 0}])
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "story.json"
            file.write_text(json.dumps({
                "layers": [{"id": "test", "kind": "route", "trace": -1}],
                "steps": [{"hold": 4, "layers": {"test": 1}}],
            }))
            with self.assertRaisesRegex(ValueError, "trace must be"):
                read_story(file)


class MapleStyleTests(unittest.TestCase):
    def test_preset_defaults_and_explicit_overrides(self):
        from story_config import apply_style_preset, check_route_labels

        callout = {"kind": "station", "backing_color": "123456"}
        route = {"kind": "route", "route_labels": {}, "trace": 15}
        bus = {"kind": "route", "route_mode": "bus", "route_labels": {}}
        road = {"kind": "route"}
        apply_style_preset({"style_preset": "maple", "layers": [callout, route, bus, road]})
        self.assertEqual(callout["backing_color"], "123456")
        self.assertEqual(callout["casing_color"], "ffffff")
        self.assertEqual(callout["backing_x_padding"], "character")
        self.assertEqual(route["route_labels"], {"uppercase": True, "corner": 0, "x_padding": "character"})
        self.assertEqual(route["trace"], 15)
        self.assertEqual(bus["uniform_color"], "a695e9")
        self.assertNotIn("uniform_color", route)
        self.assertEqual(bus["route_labels"]["x_padding"], 0.0015)
        self.assertEqual(road, {"kind": "route", "opening_visible": True})
        check_route_labels(route["route_labels"], "Rail")
        with self.assertRaisesRegex(ValueError, "route label x_padding"):
            check_route_labels({"x_padding": -1}, "Rail")


    def test_select_bus_direction_by_headsign_or_override(self):
        from story_config import select_direction

        combined = {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[1, 1], [0, 0]]]}
        departure = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
        feature = {"geometry": combined, "properties": {"directions": [
            {"direction_id": "1", "headsign": "Bachman Station", "geometry": departure}
        ]}}
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "bus.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "features": [
                    {**feature, "properties": {**feature["properties"], "id": "213"}}]
            }), encoding="utf-8")
            file = directory / "story.json"
            layer = {"id": "bus", "kind": "route", "file": "bus.geojson", "route_mode": "bus",
                     "direction": "Bachman Station"}
            story = {"origin": [0, 0], "layers": [layer],
                     "steps": [{"hold": 4, "focus": ["bus"], "layers": {"bus": 1}}]}
            file.write_text(json.dumps(story), encoding="utf-8")
            self.assertEqual(read_story(file)["layers"][0]["features"][0]["geometry"], departure)
            layer["route_overrides"] = {"213": {"direction": "all"}}
            file.write_text(json.dumps(story), encoding="utf-8")
            self.assertEqual(read_story(file)["layers"][0]["features"][0]["geometry"], combined)
        self.assertEqual(select_direction(feature, "1", "213")["geometry"], departure)


class TitlePlacementTests(unittest.TestCase):
    def test_uses_previous_corner_for_ties(self):
        from story_layout import title_corner

        self.assertEqual(title_corner(8, 8), "LEFT")
        self.assertEqual(title_corner(8, 9, "RIGHT"), "RIGHT")
        self.assertEqual(title_corner(8, 0, "LEFT"), "RIGHT")
        self.assertEqual(title_corner(0, 8, "RIGHT"), "LEFT")

    def test_route_intersection_scores_as_title_conflict(self):
        from story_layout import Placement, title_corner

        placement = Placement(((0, 0), 1000), FORMATS["landscape"])
        placement.add_route(("rail", 1), [([(-470, 195), (-320, 270)], [])], 0)
        left = placement.title_conflicts((-.48, .20, -.27, .27))
        right = placement.title_conflicts((.27, .20, .48, .27))
        self.assertEqual(title_corner(left, right), "RIGHT")


class MunicipalityTests(unittest.TestCase):
    def test_center_does_not_move_away_from_a_label_or_viewport(self):
        from story_layout import Placement, municipality_offset

        layout = Placement(((0, 0), 1000), FORMATS["portrait"])
        self.assertEqual(municipality_offset([layout], (900, 900), .01, .01, "center"), (0, 0))

    def test_full_boundary_centroid_subtracts_holes(self):
        from story_config import municipality_center

        geometry = {"type": "Polygon", "coordinates": [
            [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
            [[2, 1], [3, 1], [3, 3], [2, 3], [2, 1]],
        ]}
        x, y = municipality_center(geometry, (0, 0))
        self.assertAlmostEqual(x / 111320, (16 * 2 - 2 * 2.5) / 14)
        self.assertAlmostEqual(y / 111320, 2)

    def test_defaults_on_with_per_shot_and_project_opt_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "city.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "features": [{
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "properties": {"name": "Test City"},
                }]
            }), encoding="utf-8")
            file = directory / "story.json"
            layer = {"id": "cities", "kind": "municipalities", "file": "city.geojson"}
            steps = [{"hold": 5, "focus": ["cities"], "layers": {}},
                     {"hold": 5, "focus": ["cities"], "layers": {}, "municipality_labels": False}]
            story = {"origin": [0, 0], "layers": [layer], "steps": steps}
            file.write_text(json.dumps(story), encoding="utf-8")
            self.assertEqual([step["layers"]["cities"] for step in read_story(file)["steps"]], [1, 0])
            story["municipality_labels"] = False
            file.write_text(json.dumps(story), encoding="utf-8")
            self.assertEqual([step["layers"]["cities"] for step in read_story(file)["steps"]], [0, 0])


if __name__ == "__main__":
    unittest.main()
