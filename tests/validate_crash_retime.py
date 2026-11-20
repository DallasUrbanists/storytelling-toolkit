"""Check native retiming of the sample's editable impact tracks in Blender."""
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"blender/scripts"))
from crash_review import animation_curves,move_keys,sync_impacts,verify_scene
scene=bpy.context.scene
start=verify_scene(scene)
for actor in (o for o in scene.objects if "Actor ID" in o):
    for fcurve in animation_curves(actor):
        move_keys(fcurve,3)
for marker in scene.timeline_markers:
    marker.frame+=3
scene.frame_end+=3
sync_impacts(scene)
assert verify_scene(scene)==start+3
