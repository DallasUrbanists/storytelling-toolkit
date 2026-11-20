"""Check a generated .blend, including camera and geographic label animation."""
import argparse
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender" / "scripts"))
from story_config import FORMATS, badge_keys, layer_events, read_story, route_opacity_keys, route_starts, schedule
from build_story import feature_polygons


parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--format", choices=FORMATS, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
config = read_story(args.config)
scene = bpy.context.scene
camera = scene.camera
assert camera.data.type == "ORTHO" and camera.data.clip_end > camera.location.z > 0
assert (scene.render.resolution_x, scene.render.resolution_y) == FORMATS[args.format]
assert scene.render.fps == 30 and scene.render.resolution_percentage == 100
assert camera.animation_data.action and camera.data.animation_data.action
timings = schedule(config["steps"])
assert scene.frame_end == timings[-1][2]


def opacity(material):
    return next(node for node in material.node_tree.nodes if node.label == "Layer opacity").inputs[0].default_value


def ring_area(ring):
    return abs(sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(ring, ring[1:]))) / 2


for layer in config["layers"]:
    objects = bpy.data.collections[layer["id"]].objects
    assert objects
    keys, draws = layer_events(layer, config["steps"], timings)
    if layer["kind"] in {"boundary", "route"}:
        outline = next(obj for obj in objects if obj.type == "CURVE" and obj.data.animation_data and obj.data.animation_data.drivers)
        assert outline.data.splines and outline.data.animation_data.drivers
        for start, end in draws:
            if end - start > 2:
                scene.frame_set((start + end) // 2)
                assert 0 < outline.data.bevel_factor_end < 1, outline.name
            scene.frame_set(end)
            assert math.isclose(outline.data.bevel_factor_end, 1), outline.name
        for _, (start, _) in zip(draws, draws[1:]):
            scene.frame_set(start - 2)
            assert math.isclose(outline.data.bevel_factor_end, 1), outline.name
            scene.frame_set(start - 1)
            assert math.isclose(outline.data.bevel_factor_end, 0), outline.name
        mat = outline.data.materials[0]
        if "route_labels" in layer:
            starts = route_starts(keys, draws)
            for feature in layer["features"]:
                props = feature.get("properties", {})
                name = props.get("route_label", props.get("id", props.get("name")))
                if name is False:
                    continue
                expected = badge_keys({**layer["route_labels"], **props.get("route_label_timing", {})},
                                      starts, scene.frame_end)
                if any(expected.values()):
                    badge = next(o for o in objects if o.type == "FONT" and o.data.body == name)
                    assert badge.parent.name.endswith("Badge placement")
                    for frame, visible in expected.items():
                        scene.frame_set(frame)
                        assert badge.hide_render == (not visible), (name, frame)
                        if visible:
                            for corner in badge.bound_box:
                                point = world_to_camera_view(scene, camera, badge.matrix_world @ Vector(corner))
                                assert 0 <= point.x <= 1 and 0 <= point.y <= 1, (name, frame)
            keys = route_opacity_keys(keys, draws)
        if "interline" in layer:
            shape_keys = outline.data.shape_keys
            assert shape_keys.animation_data.drivers and "Parallel alignment" in shape_keys.key_blocks
        for frame, value in keys:
            scene.frame_set(frame)
            assert math.isclose(opacity(mat), value * layer.get("opacity", 1), abs_tol=1e-6), outline.name
        if layer.get("outside_dim"):
            mask = next(obj for obj in objects if obj.name.endswith("Outside mask"))
            assert mask.type == "MESH" and mask.data.polygons
        if layer["kind"] == "boundary" and layer.get("fill"):
            for index, feature in enumerate(layer["features"], 1):
                label = feature.get("properties", {}).get("name", f"{layer['id']} {index}")
                fill = objects[label + " | Fill"]
                polygons = feature_polygons(feature["geometry"], config["origin"], layer.get("show_holes", True))
                area = sum(ring_area(shell) - sum(map(ring_area, holes)) for shell, *holes in polygons)
                assert math.isclose(sum(face.area for face in fill.data.polygons), area, rel_tol=0.001), label
    if layer["kind"] == "street_labels":
        for label in (obj for obj in objects if obj.type == "FONT" and "Street label" in obj.name):
            assert abs(label.parent.rotation_euler.z) <= math.pi / 2
    if layer["kind"] in {"callout", "station"}:
        for label in (obj for obj in objects if obj.type == "FONT"):
            assert label.parent.name.endswith("Label placement"), label.name
            if layer.get("label_backing"):
                backing = objects[label.data.body + " | Label backing"]
                assert backing.parent == label.parent and backing.type == "CURVE"
            anchor = label.parent.parent
            assert anchor.animation_data.drivers and label.data.body
            leader = objects.get(label.data.body + " | Leader")
            if leader:
                hook = leader.modifiers[0]
                assert leader.type == "CURVE" and hook.type == "HOOK" and hook.object == label.parent
            for step, timing in zip(config["steps"], timings):
                if step["layers"].get(layer["id"], 0) < 0.99:
                    continue
                scene.frame_set(timing[2])
                for corner in label.bound_box:
                    point = world_to_camera_view(scene, camera, label.matrix_world @ Vector(corner))
                    assert 0 <= point.x <= 1 and 0 <= point.y <= 1, (label.name, step["title"], point)

for (_, arrival, end), (first, next_arrival, _) in zip(timings, timings[1:]):
    if next_arrival - first < 3:
        continue
    scene.frame_set(arrival)
    start = camera.data.ortho_scale
    scene.frame_set(end)
    assert math.isclose(camera.data.ortho_scale, start)
    scene.frame_set((first + next_arrival) // 2)
    halfway = camera.data.ortho_scale
    scene.frame_set(next_arrival)
    finish = camera.data.ortho_scale
    if not math.isclose(start, finish):
        assert min(start, finish) < halfway < max(start, finish)

print(f"Validated {args.format} scene, {len(timings)} focus steps, {scene.frame_end} frames at 30 fps")

