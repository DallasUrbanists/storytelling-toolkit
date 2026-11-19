"""Build an editable Blender polygon-boundary reveal from WGS84 GeoJSON.

Run: blender --background --python blender/scripts/import_geography.py -- --geojson path.geojson --output scene.blend
Day-1 demo only: local equirectangular meters near a compact study area, not a general GIS reprojection engine.
"""
import argparse
import json
import math
import os
import sys

import bpy


def args_after_separator():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--geojson", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--name", default="Study Area")
    return parser.parse_args(args_after_separator())


def exterior_rings_from_geojson(document):
    if not isinstance(document, dict):
        raise ValueError("GeoJSON must be an object")
    features = document.get("features") if document.get("type") == "FeatureCollection" else [document]
    if not isinstance(features, list):
        raise ValueError("GeoJSON FeatureCollection must contain a features array")
    rings = []
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("GeoJSON feature must be an object")
        geometry = feature.get("geometry") if feature.get("type") == "Feature" else feature
        if not isinstance(geometry, dict):
            raise ValueError("GeoJSON feature must have a polygon geometry")
        kind = geometry.get("type")
        coords = geometry.get("coordinates")
        if kind not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"Day-1 importer supports Polygon and MultiPolygon only: {kind!r}")
        if not isinstance(coords, list) or not coords:
            raise ValueError(f"GeoJSON {kind} must have a nonempty coordinates array")
        for polygon in [coords] if kind == "Polygon" else coords:
            if not isinstance(polygon, list) or not polygon:
                raise ValueError("Polygon must have an exterior ring")
            ring = polygon[0]
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError("Polygon exterior ring must contain at least four positions")
            for point in ring:
                if (
                    not isinstance(point, list) or len(point) < 2
                    or any(type(value) not in (int, float) for value in point[:2])
                    or not -180 <= point[0] <= 180
                    or not -90 <= point[1] <= 90
                ):
                    raise ValueError("Polygon positions must use WGS84 longitude and latitude in degrees")
            positions = [tuple(point[:2]) for point in ring]
            if positions[0] != positions[-1] or len(set(positions)) < 3:
                raise ValueError("Polygon exterior ring must be closed with at least three distinct positions")
            rings.append(positions)
    if not rings:
        raise ValueError("GeoJSON contains no polygons")
    return rings


def main():
    opts = parse_args()
    with open(opts.geojson, encoding="utf-8") as handle:
        document = json.load(handle)
    rings = exterior_rings_from_geojson(document)
    locations = [point for ring in rings for point in ring]
    lon0 = sum(p[0] for p in locations) / len(locations)
    lat0 = sum(p[1] for p in locations) / len(locations)
    if max(abs(p[0]-lon0) for p in locations) > 0.5 or max(abs(p[1]-lat0) for p in locations) > 0.5:
        raise ValueError("This demo accepts compact local areas only; reproject large regions before production")
    def project(p):
        return ((p[0]-lon0)*111320*math.cos(math.radians(lat0)), (p[1]-lat0)*111320, 0.0)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.frame_start = 1
    scene.frame_end = 90
    scene.render.fps = 30
    bounds = []
    bevel = 2.5
    for index, ring in enumerate(rings):
        vertices = [project(p) for p in ring]
        bounds.extend(vertices)
        curve = bpy.data.curves.new("BoundaryCurve", "CURVE")
        curve.dimensions = "3D"
        curve.bevel_depth = bevel
        curve.bevel_resolution = 2
        curve.bevel_factor_end = 0.0
        spline = curve.splines.new("POLY")
        spline.points.add(len(vertices)-1)
        for point, coords in zip(spline.points, vertices):
            point.co = (*coords, 1)
        # Keep the repeated endpoint so Blender can trim the open spline as it draws.
        obj = bpy.data.objects.new(f"Boundary_{index+1}", curve)
        scene.collection.objects.link(obj)
        # True draw-on: reveal an increasing fraction of the native curve.
        curve.keyframe_insert(data_path="bevel_factor_end", frame=1)
        curve.bevel_factor_end = 1.0
        curve.keyframe_insert(data_path="bevel_factor_end", frame=55)
        mat = bpy.data.materials.new("BoundaryBlue")
        mat.diffuse_color = (0.12, 0.52, 0.95, 1.0)
        if mat.node_tree is None:
            mat.use_nodes = True
        mat.node_tree.nodes.clear()
        emission = mat.node_tree.nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = (0.12, 0.52, 0.95, 1.0)
        emission.inputs["Strength"].default_value = 1.0
        output_node = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(emission.outputs[0], output_node.inputs["Surface"])
        curve.materials.append(mat)
        obj["source"] = os.path.basename(opts.geojson)
    xs = [v[0] for v in bounds]
    ys = [v[1] for v in bounds]
    width = max(max(xs)-min(xs), 1)
    height = max(max(ys)-min(ys), 1)
    center_x = (min(xs)+max(xs))/2

    label_curve = bpy.data.curves.new("FocusLabelText", "FONT")
    label_curve.body = opts.name
    label_curve.align_x = "CENTER"
    label_curve.size = max(width,height)*0.045
    label = bpy.data.objects.new("FocusLabel", label_curve)
    scene.collection.objects.link(label)
    label.location = (center_x, min(ys) - max(height * 0.13, label_curve.size), 1)
    for visibility in ("hide_render", "hide_viewport"):
        setattr(label, visibility, True)
        label.keyframe_insert(data_path=visibility, frame=1)
        setattr(label, visibility, False)
        label.keyframe_insert(data_path=visibility, frame=60)

    bpy.context.view_layer.update()
    label_x = [label.location.x + corner[0] for corner in label.bound_box]
    label_y = [label.location.y + corner[1] for corner in label.bound_box]
    x_min, x_max = min(min(xs) - bevel, min(label_x)), max(max(xs) + bevel, max(label_x))
    y_min, y_max = min(min(ys) - bevel, min(label_y)), max(max(ys) + bevel, max(label_y))
    frame_width = max(x_max - x_min, 1)
    frame_height = max(y_max - y_min, 1)
    camera_distance = max(frame_width, frame_height) * 2.5
    bpy.ops.object.camera_add(location=((x_min + x_max) / 2, (y_min + y_max) / 2, camera_distance))
    camera = bpy.context.object
    camera.name = "MapCamera_Orthographic"
    camera.rotation_euler = (0, 0, 0)
    camera.data.type = "ORTHO"
    # Blender's default far clip is shorter than a typical study area needs.
    camera.data.clip_end = max(camera_distance * 2, 10)
    aspect = scene.render.resolution_x / scene.render.resolution_y
    camera.data.ortho_scale = max(frame_width, frame_height * aspect) * 1.15
    scene.camera = camera

    scene.world.color=(0.16,0.19,0.22)
    scene.render.film_transparent = True
    label_mat = bpy.data.materials.new("LabelWhite")
    label_mat.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    if label_mat.node_tree is None:
        label_mat.use_nodes = True
    label_mat.node_tree.nodes.clear()
    emission = label_mat.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1, 1, 1, 1)
    output_node = label_mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    label_mat.node_tree.links.new(emission.outputs[0], output_node.inputs["Surface"])
    label_curve.materials.append(label_mat)
    scene.view_settings.view_transform = "Standard"
    scene.frame_set(60)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
    output = os.path.abspath(opts.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=output)
    print("Created scene:", output)


if __name__ == "__main__":
    main()
