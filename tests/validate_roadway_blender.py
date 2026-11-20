"""Check that the roadway stays in frame and its adjacent edges stay joined."""
from math import isclose

import bpy
from bpy_extras.object_utils import world_to_camera_view


scene = bpy.data.scenes["Roadway redesign"]
bpy.context.window.scene = scene
root = scene.objects["Roadway origin and bearing"]
controls = scene.objects["Section controls | dimensions in meters"]
strips = [item for item in scene.objects if item.name.startswith("Lane | ")]
assert scene.camera.data.type == "ORTHO"
assert scene.render.fps == 30
assert strips
for frame in range(1,scene.frame_end+1):
    scene.frame_set(frame)
    center = world_to_camera_view(scene, scene.camera, root.matrix_world.translation)
    assert .30 < center.x < .70 and .30 < center.y < .70, (frame, center)
    spans = [(obj.location.x - obj.scale.x / 2, obj.location.x + obj.scale.x / 2)
             for obj in strips if obj.scale.x > 1e-5]
    spans.sort()
    assert all(isclose(right, left, abs_tol=1e-5)
               for (_,right), (left,_) in zip(spans,spans[1:])), (frame, spans)
    progress = controls["progress"]
    assert 0 <= progress <= 1
    old, new = [controls[f"{phase} right-of-way m"] for phase in ("existing","proposed")]
    assert isclose(spans[-1][1] - spans[0][0],old*(1-progress)+new*progress,abs_tol=1e-5)
print(f"Verified camera framing and roadway allocation for {scene.frame_end} frames.",flush=True)
