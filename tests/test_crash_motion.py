"""Regression tests for authored manoeuvres and the deliverable inventory."""
import json
import sys
import unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/"blender/scripts"))
from crash_motion import motion_poses


class CrashMotionTest(unittest.TestCase):
    def test_braking_hold_and_reversing(self):
        keys=motion_poses({"start":[1,0,0,0,0,0],"segments":[
            {"kind":"move","frame":31,"to":[0,10],"ease":"out"},
            {"kind":"hold","frame":51},
            {"kind":"move","frame":71,"to":[0,4],"reverse":True}]})
        self.assertLess(keys[30][2]-keys[29][2], .03)
        self.assertEqual(keys[-2][1:],keys[30][1:])
        self.assertEqual(keys[-1],[71,0,4,0,0,0])

    def test_adjacent_lane_changes_preserve_tangent(self):
        k=motion_poses({"start":[1,0,0,0,0,0],"segments":[
            {"kind":"lane-change","frame":31,"to":[3,15]},
            {"kind":"lane-change","frame":61,"to":[0,30]},
            {"kind":"lane-change","frame":91,"to":[3,45]}]})
        self.assertEqual([k[i][1] for i in (30,60,90)],[3,0,3])
        self.assertEqual([k[i][4] for i in (30,60,90)],[0,0,0])
        self.assertTrue(all(a[2]<b[2] for a,b in zip(k,k[1:])))

    def test_inventory(self):
        plan=json.loads((root/"examples/maple-crash-manifest.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(len({clip["id"] for clip in plan["clips"]}),15)
        self.assertEqual(len(plan["clips"])*len(plan["sizes"]),30)
        self.assertEqual(plan["minimum_settled_hold_frames"],150)
