"""Tests for configured reveal anchors and GTFS directions."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "blender" / "scripts"), str(ROOT / "tools")]
from story_config import read_story, select_direction
from story_layout import split_trace
from gtfs_directions import attach_directions


class TransitControlsTests(unittest.TestCase):
    def test_midpoint_uses_length_and_inserts_interpolated_lane_offset(self):
        branches, rest = split_trace([([(0, 0), (2, 0), (10, 0)], [(0, 0), (0, 1), (0, 5)])])
        self.assertEqual(rest, [])
        self.assertEqual([path[0] for path, _ in branches], [(5, 0), (5, 0)])
        self.assertEqual([offsets[0] for _, offsets in branches], [(0, 2.5), (0, 2.5)])

    def test_coordinate_prefers_closest_segment_and_handles_endpoint(self):
        main = [(0, 0), (0, 100)]
        spur = [(14, 0), (14, 12)]
        branches, rest = split_trace([(main, []), (spur, [])], (18, 20))
        self.assertEqual(branches, [([(14, 12), (14, 0)], [])])
        self.assertEqual(rest, [(main, [])])

    def test_gtfs_keeps_default_geometry_and_filters_arrivals(self):
        original = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
        feature = {"type": "Feature", "properties": {"id": "001"}, "geometry": original}
        collection = {"type": "FeatureCollection", "features": [feature]}
        with TemporaryDirectory() as directory:
            path = Path(directory)
            feed = path / "test.zip"
            with ZipFile(feed, "w") as archive:
                archive.writestr("routes.txt", "route_id,route_short_name\nr,001\n")
                archive.writestr("trips.txt", "route_id,trip_id,shape_id,direction_id,trip_headsign\n"
                                 "r,a,a,0,Downtown\nr,b,b,1,Terminal\n")
                archive.writestr("stops.txt", "stop_id\nstation\nother\n")
                archive.writestr("stop_times.txt", "trip_id,stop_id,stop_sequence,stop_headsign,pickup_type\n"
                                 "a,station,10,City Center,0\na,other,30,,0\n"
                                 "b,other,1,,0\nb,station,2,,1\n")
                archive.writestr("shapes.txt", "shape_id,shape_pt_lon,shape_pt_lat,shape_pt_sequence\n"
                                 "a,0,0,10\na,2,1,20\nb,2,1,1\nb,0,0,2\n")
            result = attach_directions(collection, feed, ["station"], departures_only=True)
            supplied = result["features"][0]
            self.assertEqual([option["headsign"] for option in supplied["properties"]["directions"]],
                             ["City Center"])
            self.assertEqual(select_direction(supplied, "all", "Test")["geometry"], original)
            with self.assertRaisesRegex(ValueError, "Available directions"):
                select_direction(supplied, "1", "Test")
            (path / "routes.geojson").write_text(json.dumps(result), encoding="utf-8")
            config = {"origin": [0, 0], "layers": [{
                "id": "Bus", "kind": "route", "file": "routes.geojson",
                "route_overrides": {"001": {"direction": "city center", "trace_origin": [1, 1],
                                            "trace": 32, "opacity": 0.5, "color": "#11aa22"}},
            }], "steps": [{"title": "Test", "hold": 100, "layers": {"Bus": 1}, "focus": ["Bus"]}]}
            story = path / "story.json"
            story.write_text(json.dumps(config), encoding="utf-8")
            chosen = read_story(story)["layers"][0]["features"][0]
            self.assertEqual(chosen["geometry"]["coordinates"], [[0, 0], [2, 1]])
