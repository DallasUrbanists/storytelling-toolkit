"""Test lane geometry, label collision, and intro timing without Blender."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender" / "scripts"))
from story_config import badge_keys, layer_events, route_opacity_keys, route_starts, schedule
from story_layout import Placement, callout_geometry, crosses, parallel_routes, place_callout


class StoryLayoutTests(unittest.TestCase):
    def test_parallel_strokes_separate_reversed_shared_routes_but_not_crossings(self):
        main = [(0, 0), (900, 0)]
        reverse = [(500, 0), (100, 0)]
        crossing = [(320, -300), (320, 300)]
        routes = parallel_routes([[main], [reverse], [crossing]], 12)
        self.assertTrue(all(offset == (0, 0) for offset in routes[2][0][1]))
        for index, expected in [(0, -0.5), (1, 0.5)]:
            points, offsets = routes[index][0]
            shared_index = min(range(len(points)), key=lambda i: abs(points[i][0] - 300))
            self.assertAlmostEqual(offsets[shared_index][1], expected)
        self.assertEqual(routes[0][0][1][-1], (0, 0))

    def test_callout_avoids_transit_crossing(self):
        layout = Placement(((0, 0), 1000), (1920, 1080))
        a, b = (10, -75), (10, 75)
        layout.add_route("rail", [([a, b], [])], 0)
        offset = place_callout([layout], (0, 0), (0.046, 0.022), 0.08, 0.019)
        _, segments = callout_geometry((0, 0), offset, 0.08, 0.019)
        self.assertLess(offset[0], 0)
        self.assertFalse(any(crosses(*segment, layout.screen(a), layout.screen(b)) for segment in segments))

    def test_first_trace_badge_and_custom_windows(self):
        steps = [{"hold": 12, "layers": {"rail": 0.8}}]
        keys, draws = layer_events({"id": "rail", "trace": 10}, steps, schedule(steps))
        starts = route_starts(keys, draws)
        self.assertEqual(starts, [1])
        self.assertGreater(dict(route_opacity_keys(keys, draws))[1], 0)
        self.assertEqual(badge_keys({"duration": 4}, starts, 12), {1: 1, 5: 0})
        self.assertEqual(badge_keys({"windows": [[5, 5], [8, 12]]}, starts, 12),
                         {1: 0, 5: 1, 6: 0, 8: 1})
