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
        road = {"kind": "route"}
        apply_style_preset({"style_preset": "maple", "layers": [callout, route, road]})
        self.assertEqual(callout["backing_color"], "123456")
        self.assertEqual(callout["casing_color"], "ffffff")
        self.assertEqual(callout["backing_x_padding"], 0.00075)
        self.assertEqual(route["route_labels"], {"uppercase": True, "corner": 0, "x_padding": 0.0015})
        self.assertEqual(route["trace"], 15)
        self.assertEqual(road, {"kind": "route"})
        check_route_labels(route["route_labels"], "Rail")
        with self.assertRaisesRegex(ValueError, "route label x_padding"):
            check_route_labels({"x_padding": -1}, "Rail")


if __name__ == "__main__":
    unittest.main()
