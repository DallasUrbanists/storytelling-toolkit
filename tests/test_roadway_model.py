"""Exercise cross-section dimensions and continuous allocation."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender" / "scripts"))
from roadway_model import FEET_TO_METERS, load_model, validate_segments


class RoadwayModelTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "examples" / "illustrative-roadway.json").read_text())

    def test_locked_and_derived_widths(self):
        slots, roads, rows = load_model(self.config)
        self.assertEqual(roads, (44 * FEET_TO_METERS,) * 2)
        self.assertEqual(rows, (57 * FEET_TO_METERS,) * 2)
        turns = [slot[1] for slot in slots if slot[1] and slot[1].kind == "turn"]
        self.assertTrue(turns[0].derived)
        self.assertFalse(turns[0].locked)
        self.assertAlmostEqual(turns[0].width, 10 * FEET_TO_METERS)
        self.assertTrue(slots[0][0].locked)

    def test_edit_known_dimension_and_rederive_remaining_space(self):
        travel = next(row for row in self.config["proposed"]["elements"] if row["id"] == "travel-w")
        travel["width"] += .5
        slots, _, _ = load_model(self.config)
        turn = next(new for _, new, *_ in slots if new and new.kind == "turn")
        self.assertAlmostEqual(turn.width, 9.5 * FEET_TO_METERS)

    def test_contiguous_allocation_throughout_morph(self):
        slots, roads, rows = load_model(self.config)
        for tick in range(101):
            p = tick / 100
            edge = None
            road_width = total = 0
            for old, new, a, b, width0, width1 in slots:
                start = a*(1-p) + b*p
                width = width0*(1-p) + width1*p
                if edge is not None:
                    self.assertAlmostEqual(start, edge)
                self.assertGreaterEqual(width, 0)
                edge = start + width
                road_width += width if (old or new).zone == "road" else 0
                total += width
            self.assertAlmostEqual(road_width, roads[0])
            self.assertAlmostEqual(total, rows[0])

    def test_reject_excess_width_and_invalid_mapping(self):
        wide = copy.deepcopy(self.config)
        wide["proposed"]["elements"][3]["width"] = 100
        with self.assertRaisesRegex(ValueError, "allocation"):
            load_model(wide)
        self.config["mapping"].pop(4)
        with self.assertRaisesRegex(ValueError, "cross-section order"):
            load_model(self.config)

    def test_corridor_locations_require_source_and_confidence(self):
        segment = {
            "id": "intersection", "start": [-96.8, 32.8], "end": [-96.7, 32.7],
            "source": "Synthetic source for test", "reference": "Figure 1", "confidence": "planning",
            "existing": "old", "proposed": "new",
        }
        validate_segments([segment], {"old", "new"})
        segment["start"] = None
        with self.assertRaisesRegex((TypeError, ValueError), "None|longitude"):
            validate_segments([segment], {"old", "new"})


if __name__ == "__main__":
    unittest.main()
