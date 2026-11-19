"""Run with Blender against a generated Day 1 scene and optional PNGs."""
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


scene = bpy.context.scene
camera = scene.camera
assert camera is not None and camera.data.type == "ORTHO"
curves = [obj for obj in scene.objects if obj.type == "CURVE"]
assert curves, "The scene must contain editable boundary curves"
label = bpy.data.objects["FocusLabel"]
assert label.type == "FONT" and label.data.body

for frame, visible in ((1, False), (25, False), (60, True)):
    scene.frame_set(frame)
    assert label.hide_render != visible and label.hide_viewport != visible
    for curve in curves:
        fraction = curve.data.bevel_factor_end
        if frame == 25:
            assert 0 < fraction < 1, "Expected a partial boundary reveal"
        else:
            assert fraction == int(visible)

for obj in [*curves, label]:
    for corner in obj.bound_box:
        projected = world_to_camera_view(scene, camera, obj.matrix_world @ Vector(corner))
        assert 0 < projected.x < 1 and 0 < projected.y < 1, obj.name
        assert camera.data.clip_start < projected.z < camera.data.clip_end, obj.name

if "--" in sys.argv:
    partial_path, full_path = sys.argv[sys.argv.index("--") + 1:]
    def visible_pixels(path):
        image = bpy.data.images.load(str(Path(path).resolve()), check_existing=False)
        assert tuple(image.size) == (960, 540)
        return sum(alpha > 0.5 for alpha in image.pixels[:][3::4])

    assert 0 < visible_pixels(partial_path) < visible_pixels(full_path) < 960 * 540

print("Day 1 Blender scene validated")
