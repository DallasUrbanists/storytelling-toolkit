"""Append an editable geographic 2.5D shot to a saved Day 2 project or a blank scene."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_story import (
    TITLE_COLOR, TITLE_SIZE, caption, feature_polygons, link, map_fill, material, municipality_data,
    municipality_label, paint, scale_driver,
    stroke, title_position,
)
from story_config import FORMATS, bounds, frame_target, project
from story_layout import Placement, overlap
from urban_camera import MODES, PRESETS, bake_visibility, key_camera, sample_subject
from urban_massing import create_massing


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def group(parent, name):
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def line_paths(dataset, origin):
    output = []
    for feature in dataset["features"]:
        geo = feature["geometry"]
        if geo["type"] not in {"LineString", "MultiLineString"}:
            raise ValueError(f"Expected line input, got {geo['type']}")
        parts = [geo["coordinates"]] if geo["type"] == "LineString" else geo["coordinates"]
        output.extend([[project(c, origin) for c in line] for line in parts])
    if not output or any(len(p) < 2 for p in output):
        raise ValueError("Expected nonempty polylines")
    return output


def overview_street_extent(center, scale, dimensions, margin=1.05):
    """Local-meter footprint of the overhead orthographic camera, plus bleed."""
    x, y = center
    longest = max(dimensions)
    dx, dy = (scale * margin * side / (2 * longest) for side in dimensions)
    return x - dx, y - dy, x + dx, y + dy


def street_context_paths(directory, primary, supplemental, origin, extent):
    """Take real source routes covering the camera extent, including edge crossings."""
    paths = []
    for name in (primary, *supplemental):
        if not name:
            continue
        for path in line_paths(read(directory / name), origin):
            left, bottom, right, top = bounds(path)
            if overlap((left - .01, bottom - .01, right + .01, top + .01), extent):
                paths.append(path)
    return paths


def flat(name, color):
    # Fully opaque emission for ground graphics, with a depth-tested material.
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = paint(color)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    node = nodes.new("ShaderNodeEmission")
    node.inputs["Color"].default_value = mat.diffuse_color
    links.new(node.outputs[0], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    return mat


def add_polygon(collection, dataset, origin, name, color, z, show_holes=True):
    polygons = [projected for feature in dataset["features"]
                for projected in feature_polygons(feature["geometry"], origin)]
    if not show_holes:
        polygons = [rings[:1] for rings in polygons]
    return map_fill(collection, name, polygons, flat(name, color), z)


def ground_line(collection, name, paths, color, width, z):
    obj = stroke(collection, name, paths, flat(name, color), width, (0, 0, z))
    obj.scale.z = 0.001
    return obj


def ground_points(collection, name, dataset, origin, color, radius, z):
    vertices, faces = [], []
    for feature in dataset["features"]:
        geometry = feature["geometry"]
        if geometry["type"] != "Point":
            raise ValueError(f"{name}: expected point geometry")
        x, y = project(geometry["coordinates"], origin)
        angles = [math.tau * i / 12 for i in range(12)]
        faces.append(tuple(range(len(vertices), len(vertices) + len(angles))))
        vertices.extend((x + radius * math.cos(a), y + radius * math.sin(a), 0) for a in angles)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(flat(name, color))
    return link(collection, name, mesh, (0, 0, z))


def rectangle(collection, name, center, size, z, mat):
    x, y = center
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(x - size, y - size, 0), (x + size, y - size, 0),
                      (x + size, y + size, 0), (x - size, y + size, 0)], [], [(0, 1, 2, 3)])
    mesh.materials.append(mat)
    return link(collection, name, mesh, (0, 0, z))


def stage_massing_reveal(objects, start, end):
    nodes = objects[0].data.materials[0].node_tree.nodes
    links = objects[0].data.materials[0].node_tree.links
    alpha = nodes.get("Principled BSDF").inputs["Alpha"]
    influence = nodes.new("ShaderNodeMath")
    influence.operation = "MULTIPLY"
    influence.label = "Reveal representative building area"
    links.new(alpha.links[0].from_socket, influence.inputs[0])
    links.new(influence.outputs[0], alpha)
    for frame, opacity in ((start, 0), (end, 1)):
        influence.inputs[1].default_value = opacity
        influence.inputs[1].keyframe_insert(data_path="default_value", frame=frame)



def add_shot(scene, directory, config, format_name, mode):
    origin = config["origin"]
    subject_name = config.get("subject_name", "Study corridor")
    first = scene.frame_end + 1 if scene.camera else 1
    prior_camera = scene.camera
    z = -10000 - (prior_camera.data.clip_end if prior_camera else 0)
    # With the same X/Y origin as Day 2, this isolated stage avoids its intentionally elevated map layers.
    stage = group(scene.collection, "Day 3 | editable geographic stage")
    editable = group(stage, "Generated building volumes")
    roads = line_paths(read(directory / config["corridor"]), origin)
    all_points = [p for line in roads for p in line]
    ground = group(stage, "Geographic ground layers")
    context = config.get("context_lines")
    style = {**json.loads(scene.get("geographic_style_json", "{}")), **config.get("map_style", {})}
    ground_color = style.get("ground_color", "223742")
    municipalities = json.loads(scene.get("municipality_labels_json", "[]"))
    if config.get("municipalities"):
        layer = {"id": "municipalities", "features": read(directory / config["municipalities"])["features"]}
        municipalities = list(municipality_data(layer, origin))
    if not config.get("municipality_labels", True):
        municipalities = []
    center = project(config["detail_center"], origin)
    fields = config.get("framing", {}).get(format_name, {})
    full_center, full_scale = frame_target(all_points, FORMATS[format_name], 1.45, min_scale=0)
    overview_bounds = (directory / config["walkshed"]) if config.get("walkshed") else None
    if overview_bounds is not None:
        data = read(overview_bounds)
        rings = [ring for feature in data["features"] for polygon in feature_polygons(feature["geometry"], origin)
                 for ring in polygon]
        full_center, full_scale = frame_target([p for ring in rings for p in ring], FORMATS[format_name], 1.16)
    full_scale = fields.get("overview_scale", full_scale)
    extent = overview_street_extent(full_center, full_scale, FORMATS[format_name])
    rectangle(ground, "Ground", full_center, max(9000, full_scale), z, flat("Background ground", ground_color))
    if overview_bounds is not None:
        add_polygon(ground, data, origin, "Estimated walkshed frontage",
                    style.get("walkshed_color", "355e56"), z + 0.015,
                    show_holes=config.get("walkshed_show_holes", True))
    paths = street_context_paths(directory, context, config.get("context_supplemental_lines", []), origin, extent)
    if paths:
        ground_line(ground, "Street context", paths, style.get("street_color", "3f5560"),
                    style.get("street_width_m", 5), z + (.009 if municipalities else .05))
    if config.get("zoning"):
        zoning = group(stage, "Optional | City zoning")
        add_polygon(zoning, read(directory / config["zoning"]), origin,
                    config.get("zoning_name", "Zoning overlay"), "526a58", z + 0.023)
        zoning.hide_render = True
        zoning.hide_viewport = True
    for overlay in config.get("transit", []):
        item = group(stage, "Optional | " + overlay["name"])
        data = read(directory / overlay["file"])
        if overlay.get("kind") == "points":
            ground_points(item, overlay["name"], data, origin, overlay["color"], overlay.get("radius", 7), z + .38)
        else:
            ground_line(item, overlay["name"], line_paths(data, origin), overlay["color"], 5, z + .10)
        item.hide_render = True
        item.hide_viewport = True
    width = config.get("subject_width_m", 18)
    corridor = ground_line(ground, subject_name, roads, style.get("corridor_color", "ffc866"), width, z + 0.15)
    rise = z + 0.23
    objects = create_massing(editable, read(directory / config["buildings"]), origin, rise,
                             config.get("floor_height_m", 3.2), config.get("fallback_height_m", 7),
                             config.get("visibility_overrides", {}))
    stage_massing_reveal(objects, first + 36, first + 74)
    sun = link(stage, "Massing sunlight", bpy.data.lights.new("Massing sunlight", "SUN"))
    sun.rotation_euler = (math.radians(34), math.radians(-27), math.radians(-18))
    sun.data.energy = 2.2
    sun.data.angle = 0.12
    fill_light = link(stage, "Massing fill", bpy.data.lights.new("Massing fill", "SUN"))
    fill_light.rotation_euler = (math.radians(22), math.radians(32), 0)
    fill_light.data.energy = 0.55
    fill_light.data.use_shadow = False
    camera = link(stage, subject_name + " | 2.5D camera", bpy.data.cameras.new("2.5D orthographic"))
    camera.data.type = "ORTHO"
    distance = config.get("distance", 2800)
    camera.data.clip_end = distance + 17000
    camera.data.passepartout_alpha = 0.95
    if "subject_width_px" in config:
        driver = scale_driver(corridor.data, "bevel_depth", camera, config["subject_width_px"] / 3840)
        driver.driver.expression = f"max({width / 2:.9g}, {driver.driver.expression})"
    end = first + 138
    if prior_camera:
        # Preserve existing bound cameras and ensure the original starts the timeline.
        if not any(m.camera is not None for m in scene.timeline_markers):
            scene.timeline_markers.new("Geographic story camera", frame=scene.frame_start).camera = prior_camera
    scene.timeline_markers.new("Day 3 | 10-minute walkshed", frame=first).camera = camera
    scene.timeline_markers.new("Day 3 | tilt into 2.5D", frame=first + 30)
    scene.timeline_markers.new("Day 3 | " + subject_name + " in 2.5D", frame=first + 100)
    bearing = fields.get("bearing", config.get("bearing", 39))
    if "center" in fields:
        center = project(fields["center"], origin)
    detail_scale = fields.get("scale", 1550)
    tilt = fields.get("tilt", config.get("tilt", PRESETS["isometric"]))
    end_tilt = fields.get("end_tilt", config.get("end_tilt", tilt))
    for offset, xy, scale, angle, slope in (
        (0, full_center, full_scale, 0, PRESETS["overhead"]),
        (28, full_center, full_scale, 0, PRESETS["overhead"]),
        (100, center, detail_scale, bearing, tilt),
        (138, center, detail_scale, bearing, end_tilt),
    ):
        key_camera(camera, first + offset, (*xy, rise), scale, angle, slope, distance)
    scene.frame_end = end
    scene.render.resolution_x, scene.render.resolution_y = FORMATS[format_name]
    scene.render.fps = 30
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 32
    scene.view_settings.view_transform = "Standard"
    screen = group(stage, "Editable Day 3 titles")
    anchor = link(screen, "Day 3 screen coordinates", at=(0, 0, -60), parent=camera)
    for axis in range(3):
        scale_driver(anchor, "scale", camera, 1, axis)
    ratio = min(FORMATS[format_name]) / max(FORMATS[format_name])
    left = -.45 if format_name == "landscape" else -.45 * ratio
    top = .44 * ratio if format_name == "landscape" else .44
    bottom = -.44 * ratio if format_name == "landscape" else -.44
    layout = Placement((full_center, full_scale), FORMATS[format_name])
    layout.add_route(("study corridor", 1), [(path, []) for path in roads], 0)
    for number, path in enumerate(paths):
        layout.add_route(("street context", number), [(path, [])], 0)
    if overview_bounds is not None:
        layout.add_route(("walkshed boundary", 1), [(ring, []) for ring in rings], 0)
    if municipalities:
        cities = group(ground, "Municipality labels")
        keys = [(1, 0), (max(1, first - 1), 0), (first, 1), (first + 28, 1), (first + 42, 0)]
        for name, center, color, size, placement in municipalities:
            municipality_label(cities, name, center, color, size, keys, camera, z + .012, [layout], placement)
    side, title_x, title_y, _, heading = title_position(
        FORMATS[format_name], layout, config.get("overview_title", "Walking catchment"),
        previous=scene.get("geographic_title_corner", "LEFT"),
    )
    intro = material("Day 3 | walkshed title", TITLE_COLOR, [(first, 1), (first + 25, 1), (first + 43, 0)])
    detail = material("Day 3 | detail title", "ebf5f2", [(first, 0), (first + 67, 0), (first + 97, 1)])
    credit = flat("Day 3 source text", "a6c6bf")
    caption(screen, "Walkshed title", heading, intro, TITLE_SIZE, (title_x, title_y, 0), anchor, side)
    caption(screen, "Isometric title", subject_name + " in 2.5D", detail, .029, (left, top, 0), anchor)
    if config.get("credit"):
        credit_text = config["credit"]
        caption(screen, "Map attribution", credit_text, credit, .011, (left, bottom, 0), anchor)
        box = bpy.data.meshes.new("Attribution backing")
        width = min(len(credit_text) * 0.006, .89 if format_name == "landscape" else .5)
        box.from_pydata([(-.009,-.015,-.001),(width,-.015,-.001),
                         (width,.009,-.001),(-.009,.009,-.001)], [], [(0,1,2,3)])
        box.materials.append(flat("Attribution background", ground_color))
        link(screen, "Attribution backing", box, (left, bottom, 0), anchor)
    if config.get("approved_caption"):
        value = read(directory / config["approved_caption"])
        if not value.get("approved_by"):
            raise ValueError("Population caption needs explicit approval")
        caption(screen, "Population estimate", value["caption"], intro, .018,
                (left, top - .034, 0), anchor)
        caption(screen, "Population source", value["source"], intro, .012,
                (left, top - .055, 0), anchor)
    rays = sample_subject([[(x, y, z + .20) for x, y in line] for line in roads],
                          half_width=width * .46)
    hits = bake_visibility(scene, camera, objects, rays, first, end, mode,
                           config.get("faded_opacity", .15), config.get("fade_frames", 7))
    stage["origin_wgs84"] = origin
    stage["visibility_mode"] = mode
    stage["occlusion_start"] = first
    stage["occlusion_end"] = end
    stage["building_count"] = len(objects)
    stage["obstructing_building_count"] = sum(bool(frames) for frames in hits.values())
    stage["map_ground_elevation"] = z
    stage["number_of_subject_samples"] = len(rays)
    scene.frame_set(first + 106)
    for layout in bpy.data.screens:
        for area in layout.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.region_3d.view_perspective = "CAMERA"
                space.clip_end = max(space.clip_end, camera.data.clip_end)
                space.overlay.show_overlays = False
    return stage


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--format", choices=FORMATS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visibility", choices=sorted(MODES), default="fade")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError("Choose a new .blend path to preserve authored work")
    scene = bpy.context.scene
    if bpy.data.filepath == "":
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        scene.frame_end = 0
    stage = add_shot(scene, args.config.resolve().parent, read(args.config), args.format, args.visibility)
    if bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve())) != {"FINISHED"}:
        raise OSError("Could not save Blender project")
    print(f"Day 3: {stage['building_count']} buildings, {stage['obstructing_building_count']} obstructors")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:])
