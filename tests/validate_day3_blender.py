"""Run under Blender 5.3. Camera, footprints and roadway here are synthetic."""
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender" / "scripts"))
from urban_camera import PRESETS, bake_visibility, key_camera, sample_subject
from urban_massing import extrude, height_for


def box(name, location):
    bpy.ops.mesh.primitive_cube_add(size=4, location=location)
    obj = bpy.context.object
    obj.name = name
    return obj


def main():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    camera = bpy.data.objects.new("Synthetic camera", bpy.data.cameras.new("Fixture camera"))
    scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    scene.camera = camera
    camera.data.clip_end = 100
    key_camera(camera, 1, (0,0,0), 30, 0, 0, 40)
    key_camera(camera, 20, (0,0,0), 30, 0, PRESETS["isometric"], 40)
    key_camera(camera, 40, (0,0,0), 30, 0, 0, 40)
    primary = box("Between camera and subject", (0,-3,2.3))
    outside = box("Behind subject", (0,8,2.3))
    subject = sample_subject([[(-1,0,0), (1,0,0)]], spacing=0.5, half_width=0)
    hits = bake_visibility(scene, camera, [primary, outside], subject, 1, 40, "fade")
    assert 20 in hits[primary.name]
    assert not hits[outside.name]
    scene.frame_set(20)
    assert abs(primary.color[3] - 0.15) < 1e-5
    scene.frame_set(40)
    assert abs(primary.color[3] - 1) < 1e-5
    primary["visibility_override"] = "show"
    bake_visibility(scene, camera, [primary, outside], subject, 1, 40, "hide")
    scene.frame_set(20)
    assert primary.color[3] == 1
    primary["visibility_override"] = "auto"
    bake_visibility(scene, camera, [primary, outside], subject, 1, 40, "hide")
    assert primary.color[3] == 0
    outside["visibility_override"] = "hide"
    bake_visibility(scene, camera, [primary, outside], subject, 1, 40, "manual")
    assert primary.color[3] == 1 and outside.color[3] == 0
    assert height_for({"levels":3}, 3.2, 7)[0] == 3 * 3.2
    assert height_for({"height_verified_m":12,"levels":3}, 3.2, 7) == (12,"verified")
    assert height_for({"height_unverified_m":12}, 3.2, 7)[0] == 7
    v, faces = extrude([[(0,0),(8,0),(8,8),(0,8)], [(2,2),(2,6),(6,6),(6,2)]], 5)
    roof = [face for face in faces if all(v[i][2] == 5 for i in face)]
    area = sum((Vector(v[b]) - Vector(v[a])).cross(Vector(v[c]) - Vector(v[a])).length / 2
               for a,b,c in roof)
    assert abs(area - 48) < .001, area
    try:
        extrude([[(0,0),(1,1)]], 5)
    except ValueError:
        pass
    else:
        raise AssertionError("Malformed footprint should fail")
    print("Blender Day 3 regression checks passed")


if __name__ == "__main__":
    main()
