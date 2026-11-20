"""Build editable orthographic shots and bake subject-driven building visibility."""
import math

import bpy
from bpy_extras.anim_utils import action_get_channelbag_for_slot
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree

PRESETS = {"overhead": 0.0, "isometric": math.degrees(math.acos(1 / math.sqrt(3))), "oblique": 68.0}
MODES = {"normal", "fade", "hide", "manual"}


def camera_pose(target, bearing_deg=0, tilt_deg=0, distance=2000):
    """Bearing measures the direction from the camera toward the subject, clockwise from north."""
    if not 0 <= tilt_deg < 89 or not math.isfinite(distance) or distance <= 0 or not math.isfinite(bearing_deg):
        raise ValueError("Camera tilt must be in [0, 89) degrees and camera distance must be positive")
    bearing, tilt = map(math.radians, (bearing_deg, tilt_deg))
    target = Vector(target)
    rotation = Quaternion((0, 0, 1), -bearing) @ Quaternion((1, 0, 0), tilt)
    return target + rotation @ Vector((0, 0, distance)), rotation


def key_camera(camera, frame, target, scale, bearing, tilt, distance):
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Orthographic scale must be positive")
    camera.rotation_mode = "QUATERNION"
    location, rotation = camera_pose(target, bearing, tilt, distance)
    # Blender interpolates quaternion components. Keep adjacent keys on the same
    # hemisphere when the bearing crosses a quaternion sign discontinuity.
    if camera.rotation_quaternion.dot(rotation) < 0:
        rotation.negate()
    camera.location, camera.rotation_quaternion = location, rotation
    camera.data.ortho_scale = scale
    for path in ("location", "rotation_quaternion"):
        camera.keyframe_insert(data_path=path, frame=frame, group="Urban camera")
    camera.data.keyframe_insert(data_path="ortho_scale", frame=frame, group="Urban framing")


def sample_subject(paths, spacing=5, half_width=4):
    points = []
    for path in paths:
        for a, b in zip(path, path[1:]):
            a, b = Vector(a), Vector(b)
            delta = b - a
            if delta.length < 1e-7:
                continue
            travel = math.ceil(delta.length / spacing)
            offset = Vector((-delta.y, delta.x, 0)).normalized() * half_width
            for i in range(travel + 1):
                point = a.lerp(b, i / travel)
                points.extend((point, point + offset, point - offset))
    if not points:
        raise ValueError("Occlusion subject must have at least one nonempty line")
    return points


def building_tree(objects, depsgraph):
    vertices, polygons, owners = [], [], []
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            start = len(vertices)
            vertices.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
            for face in mesh.polygons:
                polygons.append(tuple(start + i for i in face.vertices))
                owners.append(obj.name)
        finally:
            evaluated.to_mesh_clear()
    return (BVHTree.FromPolygons(vertices, polygons), owners) if polygons else (None, [])


def blockers(scene, camera, ray_points, tree, owners):
    if tree is None:
        return set()
    rotation = camera.matrix_world.to_quaternion()
    right, up, look = [rotation @ Vector(axis) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, -1))]
    found = set()
    for point in ray_points:
        bounds = world_to_camera_view(scene, camera, point)
        if not (0 <= bounds.x <= 1 and 0 <= bounds.y <= 1 and bounds.z > 0):
            continue
        if camera.data.type == "ORTHO":
            offset = point - camera.matrix_world.translation
            start = camera.matrix_world.translation + right * offset.dot(right) + up * offset.dot(up)
        else:
            start = camera.matrix_world.translation.copy()
        delta = point - start
        length = delta.length
        direction = look if camera.data.type == "ORTHO" else delta.normalized()
        while length > 0.02:
            hit, _, face, distance = tree.ray_cast(start, direction, length - 0.01)
            if hit is None:
                break
            found.add(owners[face])
            step = distance + 0.025
            start += direction * step
            length -= step
    return found


def opacity_at(frame, active, fade_frames, low):
    if frame in active:
        return low
    distance = next((d for d in range(1, fade_frames + 1)
                     if frame - d in active or frame + d in active), fade_frames)
    t = distance / fade_frames
    return low + (1 - low) * t * t * (3 - 2 * t)


def bake_visibility(scene, camera, objects, subject, start, end, mode="fade",
                    faded_opacity=0.15, fade_frames=7):
    if mode not in MODES or not 0 <= faded_opacity <= 1 or fade_frames < 1 or end < start:
        raise ValueError("Invalid visibility mode, frame range, opacity, or fade length")
    overrides = {obj.name: obj.get("visibility_override", "auto") for obj in objects}
    if set(overrides.values()) - {"auto", "show", "fade", "hide"}:
        raise ValueError("Building visibility overrides must be auto, show, fade, or hide")
    original = scene.frame_current
    hits = {obj.name: set() for obj in objects}
    if mode in {"fade", "hide"}:
        # Geometry for this bake is evaluated at the opening frame. Rebake after editing static massing.
        scene.frame_set(start)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eligible = [obj for obj in objects if overrides[obj.name] != "hide"]
        tree, owners = building_tree(eligible, depsgraph)
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            for name in blockers(scene, camera, subject, tree, owners):
                hits[name].add(frame)
    for obj in objects:
        override = overrides[obj.name]
        animation = obj.animation_data
        if animation and animation.action and animation.action_slot:
            bag = action_get_channelbag_for_slot(animation.action, animation.action_slot)
            curve = bag.fcurves.find("color", index=3) if bag else None
            if curve:
                for key in list(curve.keyframe_points)[::-1]:
                    if start <= key.co.x <= end:
                        curve.keyframe_points.remove(key, fast=True)
                curve.update()
        levels = []
        for frame in range(start, end + 1):
            if override != "auto":
                level = {"show": 1, "fade": faded_opacity, "hide": 0}[override]
            elif mode == "fade":
                level = opacity_at(frame, hits[obj.name], fade_frames, faded_opacity)
            else:
                level = float(mode != "hide" or frame not in hits[obj.name])
            levels.append(level)
        # Keep endpoints of constant runs and every changing sample. All keys stay editable.
        for index, level in enumerate(levels):
            if 0 < index < len(levels) - 1 and levels[index - 1] == level == levels[index + 1]:
                continue
            obj.color[3] = level
            obj.keyframe_insert(data_path="color", index=3, frame=start + index, group="Urban visibility")
        animation = obj.animation_data
        curve = action_get_channelbag_for_slot(animation.action, animation.action_slot).fcurves.find("color", index=3)
        for key in curve.keyframe_points:
            key.interpolation = "CONSTANT" if (mode == "hide" and override == "auto") else "LINEAR"
    scene.frame_set(original)
    return hits
