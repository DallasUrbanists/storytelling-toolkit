"""Synthetic approval tests. The numbers do not describe a real population."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis"))
from approve_population import approved_caption


class PopulationApprovalTest(unittest.TestCase):
    def test_exact_value_and_reviewer_are_required(self):
        report = {"baseline": {"rounded": 3500}, "period": "2020–2024", "minutes": 10}
        self.assertIn("3,500", approved_caption(report, 3500, "Editor")["caption"])
        for value, reviewer in [(3400, "Editor"), (3500, " "), (None, "Editor")]:
            with self.subTest(value=value, reviewer=reviewer), self.assertRaises(ValueError):
                approved_caption(report, value, reviewer)
