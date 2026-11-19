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


def polygons_from_geojson(document):
    features = document.get("features", []) if document.get("type") == "FeatureCollection" else [document]
    polygons = []
    for feature in features:
        geometry = feature.get("geometry", feature)
        kind = geometry.get("type")
        coords = geometry.get("coordinates", [])
        if kind == "Polygon":
            polygons.append(coords)
        elif kind == "MultiPolygon":
            polygons.extend(coords)
        else:
            raise ValueError("Day-1 importer supports Polygon and MultiPolygon only: " + str(kind))
    if not polygons:
        raise ValueError("GeoJSON contains no polygons")
    return polygons


def main():
    opts = parse_args()
    with open(opts.geojson, encoding="utf-8") as handle:
        document = json.load(handle)
    polygons = polygons_from_geojson(document)
    rings = [ring for poly in polygons for ring in poly[:1]]
    locations = [point for ring in rings for point in ring]
    if not locations:
        raise ValueError("Polygons contain no exterior coordinates")
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
    scene.frame_start = 1
    scene.frame_end = 90
    scene.render.fps = 30
    bounds = []
    for index, ring in enumerate(rings):
        if len(ring) < 4:
            raise ValueError("Polygon exterior ring must contain at least 4 coordinates")
        vertices = [project(p) for p in ring]
        if vertices[0] == vertices[-1]:
            vertices = vertices[:-1]
        bounds.extend(vertices)
        curve = bpy.data.curves.new("BoundaryCurve", "CURVE")
        curve.dimensions = "3D"
        curve.bevel_depth = 2.5
        curve.bevel_resolution = 2
        curve.bevel_factor_end = 0.0
        spline = curve.splines.new("POLY")
        spline.points.add(len(vertices)-1)
        for point, coords in zip(spline.points, vertices):
            point.co = (*coords, 1)
        spline.use_cyclic_u = True
        obj = bpy.data.objects.new(f"Boundary_{index+1}", curve)
        scene.collection.objects.link(obj)
        # True draw-on: reveal an increasing fraction of the native curve.
        curve.keyframe_insert(data_path="bevel_factor_end", frame=1)
        curve.bevel_factor_end = 1.0
        curve.keyframe_insert(data_path="bevel_factor_end", frame=55)
        mat = bpy.data.materials.new("BoundaryBlue")
        mat.diffuse_color = (0.12, 0.52, 0.95, 1.0)
        mat.use_nodes = True
        mat.node_tree.nodes.clear()
        emission = mat.node_tree.nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = (0.12, 0.52, 0.95, 1.0)
        emission.inputs["Strength"].default_value = 1.0
        output_node = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(emission.outputs[0], output_node.inputs["Surface"])
        curve.materials.append(mat)
        obj["source"] = os.path.basename(opts.geojson)
    xs = [v[0] for v in bounds]; ys = [v[1] for v in bounds]
    width = max(max(xs)-min(xs), 1)
    height = max(max(ys)-min(ys), 1)
    center_x = (min(xs)+max(xs))/2
    center_y = (min(ys)+max(ys))/2

    bpy.ops.object.camera_add(location=(center_x,center_y,max(width,height)*2.5))
    camera = bpy.context.object
    camera.name = "MapCamera_Orthographic"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(width*1.3, height*1.3*960/540)
    camera.rotation_euler = (0,0,0)
    # Cameras look down local -Z: the camera starts above the map.
    scene.camera = camera
    label_curve = bpy.data.curves.new("FocusLabelText", "FONT")
    label_curve.body = opts.name
    label_curve.size = max(width,height)*0.045
    label = bpy.data.objects.new("FocusLabel", label_curve)
    scene.collection.objects.link(label)
    label.location=(center_x, min(ys)-height*.13, 1)
    label.hide_render=True
    label.keyframe_insert(data_path="hide_render", frame=1)
    label.hide_render=False
    label.keyframe_insert(data_path="hide_render", frame=60)

    scene.world.color=(0.16,0.19,0.22)
    scene.render.film_transparent = True
    label_mat = bpy.data.materials.new("LabelWhite")
    label_mat.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    label_mat.use_nodes = True
    label_mat.node_tree.nodes.clear()
    emission = label_mat.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1, 1, 1, 1)
    output_node = label_mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    label_mat.node_tree.links.new(emission.outputs[0], output_node.inputs["Surface"])
    label_curve.materials.append(label_mat)
    scene.view_settings.view_transform = "Standard"
    output = os.path.abspath(opts.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=output)
    print("Created scene:", output)


if __name__ == "__main__":
    main()
