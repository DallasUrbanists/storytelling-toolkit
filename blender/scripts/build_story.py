"""Build one editable Blender composition from a local geographic story."""
import argparse
import math
from functools import lru_cache
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.geometry import delaunay_2d_cdt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_layout import Placement, parallel_routes, place_callout, rect, samples, split_trace
from story_config import (
    FORMATS, badge_keys, bounds, frame_target, layer_events, positions,
    project, read_story, route_opacity_keys, route_starts, schedule,
)


def paint(color):
    color = color.lstrip("#")
    if len(color) != 6:
        raise ValueError("Expected a six-digit hexadecimal color")
    channels = [int(color[i:i+2], 16) / 255 for i in (0, 2, 4)]
    return tuple(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels) + (1,)


def material(name, color, keys, opacity=1, image=None):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = paint(color)
    if mat.node_tree is None:
        mat.use_nodes = True
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    else:
        mat.blend_method = "BLEND"
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = mat.diffuse_color
    if image:
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        links.new(texture.outputs["Color"], emission.inputs["Color"])
    mix = nodes.new("ShaderNodeMixShader")
    mix.label = "Layer opacity"
    links.new(nodes.new("ShaderNodeBsdfTransparent").outputs[0], mix.inputs[1])
    links.new(emission.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    factor = mix.inputs[0]
    for frame, value in keys:
        factor.default_value = value * opacity
        factor.keyframe_insert(data_path="default_value", frame=frame)
    return mat


def scale_driver(block, path, camera, factor, index=None):
    curve = block.driver_add(path) if index is None else block.driver_add(path, index)
    driver = curve.driver
    var = driver.variables.new()
    var.name = "ortho_scale"
    var.targets[0].id_type = "CAMERA"
    var.targets[0].id = camera.data
    var.targets[0].data_path = "ortho_scale"
    driver.expression = f"ortho_scale * {factor:.9g}"


def link(collection, name, data=None, at=(0, 0, 0), parent=None):
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.parent = parent
    obj.location = at
    return obj


def spline(curve, points, cyclic=False):
    part = curve.splines.new("POLY")
    part.points.add(len(points) - 1)
    for point, (x, y) in zip(part.points, points):
        point.co = (x, y, 0, 1)
    part.use_cyclic_u = cyclic


def stroke(collection, name, paths, mat, width, at, camera=None, parent=None, draws=(), seed=0):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_resolution = 2
    curve.materials.append(mat)
    curve.bevel_depth = width / 2
    if camera:
        scale_driver(curve, "bevel_depth", camera, width / 3840)
    for path in paths:
        spline(curve, path)
    if draws:
        for begin, finish in draws:
            curve.bevel_factor_end = 0
            curve.keyframe_insert(data_path="bevel_factor_end", frame=max(1, begin - 1))
            if seed and finish > begin:
                curve.bevel_factor_end = seed
                curve.keyframe_insert(data_path="bevel_factor_end", frame=begin)
            curve.bevel_factor_end = 1
            curve.keyframe_insert(data_path="bevel_factor_end", frame=finish)
        # Keep the outline complete until the next hidden reset frame.
        animation = curve.animation_data
        strip = animation.action.layers[0].strips[0]
        channels = strip.channelbag(animation.action_slot)
        trace = channels.fcurves.find("bevel_factor_end")
        completed = {finish for _, finish in draws}
        for key in trace.keyframe_points:
            if key.co.x in completed:
                key.interpolation = "CONSTANT"
    return link(collection, name, curve, at, parent)


def oriented_ring(ring, counterclockwise):
    points = ring[:-1] if ring[0] == ring[-1] else ring
    signed = sum(x1*y2 - x2*y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))
    return points if (signed > 0) == counterclockwise else points[::-1]


def fill(collection, name, rings, mat, at, parent=None):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.materials.append(mat)
    for ring, counterclockwise in rings:
        spline(curve, oriented_ring(ring, counterclockwise), cyclic=True)
    return link(collection, name, curve, at, parent)


def map_fill(collection, name, polygons, mat, z, outside=None):
    vertices, edges = [], []
    prepared = []
    for polygon in polygons:
        prepared.append([])
        for ring in polygon:
            prepared[-1].append((ring, bounds(ring)))
    rings = [ring for polygon in polygons for ring in polygon]
    if outside is not None:
        rings.append(outside)
    for ring in rings:
        points = oriented_ring(ring, counterclockwise=True)
        start = len(vertices)
        vertices.extend(Vector(point) for point in points)
        edges.extend((index, index + 1) for index in range(start, len(vertices) - 1))
        edges.append((len(vertices) - 1, start))
    points, _, triangles, *_ = delaunay_2d_cdt(vertices, edges, [], 0, 0.001, False)
    outside_bounds = bounds(outside) if outside is not None else None

    def inside_ring(ring, envelope, x, y):
        xmin, ymin, xmax, ymax = envelope
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            return False
        inside = False
        previous = ring[-1]
        for current in ring:
            ax, ay = previous
            bx, by = current
            if (ay > y) != (by > y) and x < ax + (bx - ax) * (y - ay) / (by - ay):
                inside = not inside
            previous = current
        return inside

    kept = []
    for triangle in triangles:
        x = sum(points[index].x for index in triangle) / 3
        y = sum(points[index].y for index in triangle) / 3
        # Constrained edges prevent triangles from crossing polygon boundaries.
        inside = any(inside_ring(*shell, x, y) and not any(inside_ring(*hole, x, y) for hole in holes)
                     for shell, *holes in prepared)
        if outside_bounds:
            inside = not inside and inside_ring(outside, outside_bounds, x, y)
        if inside:
            kept.append(triangle)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(p.x, p.y, 0) for p in points], [], kept)
    mesh.materials.append(mat)
    return link(collection, name, mesh, (0, 0, z))


def caption(collection, name, value, mat, size, at, parent, align="LEFT"):
    font = bpy.data.curves.new(name, "FONT")
    font.body = value
    font.size = size
    font.align_x = align
    font.align_y = "CENTER"
    font.materials.append(mat)
    return link(collection, name, font, at, parent)


def feature_polygons(geometry, origin, show_holes=True):
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [[[project(point, origin) for point in ring] for ring in (polygon if show_holes else polygon[:1])] for polygon in polygons]


def raster_layer(collection, layer, keys, origin, z):
    xmin, ymin = project(layer["bounds"][:2], origin)
    xmax, ymax = project(layer["bounds"][2:], origin)
    mesh = bpy.data.meshes.new(layer["id"])
    mesh.from_pydata([(xmin, ymin, 0), (xmax, ymin, 0), (xmax, ymax, 0), (xmin, ymax, 0)], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new()
    for loop, coordinate in zip(mesh.polygons[0].loop_indices, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[loop].uv = coordinate
    image = bpy.data.images.load(str(layer["path"]), check_existing=True)
    image.pack()
    mesh.materials.append(material(layer["id"], "ffffff", keys, layer.get("opacity", 1), image=image))
    link(collection, layer["id"], mesh, (0, 0, z))


def callout(collection, layer, feature, origin, z, camera, format_name, keys, color, layouts):
    props = feature.get("properties", {})
    name = props.get("name", layer["id"])
    x, y = project(feature["geometry"]["coordinates"], origin)
    root = link(collection, name + " | Geographic anchor", at=(x, y, z))
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.02
    for axis in (0, 1):
        scale_driver(root, "scale", camera, 1, axis)
    opacity = layer.get("opacity", 1)
    backing_color = layer.get("backing_color", color)
    leader_color = layer.get("leader_color", color)
    dot_color = layer.get("dot_color", color)
    ink = {value: material(f"{name} | {value}", value, keys, opacity)
           for value in dict.fromkeys((backing_color, leader_color, dot_color))}
    white = material(name + " | White casing", layer.get("casing_color", "f1f7fc"), keys, opacity)
    radius = layer.get("radius", 0.0036)
    disk = [(radius * math.cos(i * math.tau / 24), radius * math.sin(i * math.tau / 24)) for i in range(24)]
    fill(collection, name + " | Anchor dot", [(disk, True)], ink[dot_color], (0, 0, 12), root)
    preferred = props.get("offsets", {}).get(format_name, layer.get("offsets", {}).get(format_name, [0.025, 0.023]))
    size = layer.get("text_size", 0.017)
    width, height, text_center = label_box(name, size, 0.005, layer.get("backing_x_padding"))
    auto = props.get("auto_place", layer.get("auto_place", False))
    dx, dy = place_callout(layouts, (x, y), preferred, width, height) if auto else preferred
    placement = link(collection, name + " | Label placement", at=(dx, dy, 0), parent=root)
    placement.empty_display_type = "PLAIN_AXES"
    placement.empty_display_size = 0.007
    if dx or dy:
        path = [(0, 0), (dx * 0.67, dy), (dx, dy)]
        casing = stroke(collection, name + " | Leader casing", [path], white, 0.0020, (0, 0, 2), parent=root)
        leader = stroke(collection, name + " | Leader", [path], ink[leader_color], 0.0010, (0, 0, 6), parent=root)
        for line in (casing, leader):
            hook = line.modifiers.new("Follow label placement", "HOOK")
            hook.object = placement
            hook.vertex_indices_set([1, 2])
            hook.matrix_inverse = Matrix.Translation((-dx, -dy, line.location.z))
    direction = 1 if dx >= 0 else -1
    if layer.get("label_backing", False):
        text = material(name + " | Text", contrasting_text(backing_color), keys, opacity)
        box_x = direction * width / 2
        panel(collection, name + " | Label backing", ink[backing_color], width, height, (box_x, 0, 13),
              placement, corner=layer.get("backing_corner", 0.003))
        caption(collection, name + " | Label", name, text, size, (box_x - text_center, 0, 16), placement, "CENTER")
    else:
        caption(collection, name + " | Label", name, white, size, (direction * 0.004, 0, 16), placement,
                "LEFT" if direction == 1 else "RIGHT")


def panel(collection, name, mat, width, height, at, parent, corner=0.003):
    x, y = width / 2, height / 2
    r = min(corner, x / 2, y / 2)
    path = ([(-x + r, -y), (x - r, -y), (x, -y + r), (x, y - r),
             (x - r, y), (-x + r, y), (-x, y - r), (-x, -y + r)] if r else
            [(-x, -y), (x, -y), (x, y), (-x, y)])
    return fill(collection, name, [(path, True)], mat, at, parent)


def text_box(value, size, padding, horizontal=None):
    units = sum(0.33 if char in " ilI.,:/!" else 0.92 if char in "MWmw" else 0.62 for char in value)
    return units * size + 2 * (padding if horizontal is None else horizontal), size * 1.05 + padding


@lru_cache(maxsize=256)
def glyph_bounds(value, size):
    """Measure the actual centered Blender glyph geometry in local coordinates."""
    data = bpy.data.curves.new("Label measurement", "FONT")
    obj = bpy.data.objects.new("Label measurement", data)
    try:
        data.body, data.size, data.align_x = value, size, "CENTER"
        bpy.context.scene.collection.objects.link(obj)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        coords = [corner[0] for corner in evaluated.bound_box]
        return min(coords), max(coords)
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.curves.remove(data)


def label_box(value, size, vertical, horizontal):
    if horizontal != "character":
        width, height = text_box(value, size, vertical, horizontal)
        return width, height, 0
    left, right = glyph_bounds(value, size)
    ink_width = right - left
    average = ink_width / max(1, sum(not char.isspace() for char in value))
    return ink_width + 2 * average, size * 1.05 + vertical, (left + right) / 2


def contrasting_text(color):
    light = sum(v * k for v, k in zip(paint(color), (0.2126, 0.7152, 0.0722)))
    return "13232f" if light > 0.24 else "f1f7fc"


def styled_route_layer(layer):
    return any(key in layer for key in ("interline", "route_labels", "route_overrides", "trace_origin", "uniform_color"))


def route_paths(layer, origin):
    groups = []
    for feature in layer["features"]:
        geometry = feature["geometry"]
        lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
        groups.append([[project(point, origin) for point in line] for line in lines])
    if "interline" in layer:
        return parallel_routes(groups, layer["interline"].get("tolerance", 28))
    if "route_labels" in layer:
        groups = [[samples(line, 35) for line in paths] for paths in groups]
    return [[(line, []) for line in paths] for paths in groups]


def lane_spacing(layer):
    return layer.get("interline", {}).get("spacing", layer.get("width", 5) + 2) / 1920


def choose_badge(packed, layouts, owner, width, height, separation):
    layout = layouts[0]
    best = None
    for part, (path, offsets) in enumerate(packed):
        last = None
        for i in range(1, len(path) - 1):
            vx, vy = offsets[i] if offsets else (0, 0)
            x, y = layout.screen(path[i])
            x, y = x + vx * separation, y + vy * separation
            if last and math.hypot(x - last[0], y - last[1]) < 0.010:
                continue
            if not (layout.frame[0] < x < layout.frame[2] and layout.frame[1] < y < layout.frame[3]):
                continue
            last = (x, y)
            for dx, dy in ((0, 0), (-0.039, 0), (0.039, 0), (0, -0.027), (0, 0.027),
                           (-0.043, 0.027), (0.043, -0.027)):
                box = rect((x + dx, y + dy), width + 0.010, height + 0.010)
                leader = [((x, y), (x + dx, y + dy))] if dx or dy else []
                conflicts = 0
                for pose in layouts:
                    u, v = pose.screen(path[i])
                    u, v = u + vx * separation, v + vy * separation
                    pose_box = rect((u + dx, v + dy), width + 0.010, height + 0.010)
                    tether = [((u, v), (u + dx, v + dy))] if leader else []
                    conflicts += pose.score(pose_box, tether, owner=owner)
                rank = (conflicts, bool(leader), math.hypot(x, y), part)
                if best is None or rank < best[0]:
                    best = rank, part, i, box, (dx, dy), leader
    return best


def interline_stroke(obj, packed, camera, separation, scale):
    if not any(offsets for _, offsets in packed):
        return
    obj.shape_key_add(name="Source alignment")
    key = obj.shape_key_add(name="Parallel alignment")
    for item, (point, offset) in zip(key.data, (
            (point, offset) for path, offsets in packed for point, offset in zip(path, offsets))):
        item.co = (point[0] + offset[0] * separation * scale, point[1] + offset[1] * separation * scale, 0)
    scale_driver(key, "value", camera, 1 / scale)


def route_badge(collection, label, point, offset, separation, color, timing, size, width, height, z, camera, shift,
                corner=0.003, text_center=0):
    root = link(collection, label + " | Badge anchor", at=(*point, z))
    for axis in (0, 1):
        scale_driver(root, "scale", camera, 1, axis)
        delta = offset[axis] * separation
        if delta:
            scale_driver(root, "location", camera, delta, axis)
            root.animation_data.drivers.find("location", index=axis).driver.expression += f" + ({point[axis]:.12g})"
    static = [(1, 1)]
    rim = material(label + " | Badge rim", "162733", static)
    main = material(label + " | Badge", color, static)
    text = material(label + " | Badge text", contrasting_text(color), static)
    badge = link(collection, label + " | Badge placement", at=(*shift, 0), parent=root)
    parts = [
        panel(collection, label + " | Badge rim", rim, width + 0.0025, height + 0.0025, (0, 0, 1), badge, corner=corner),
        panel(collection, label + " | Badge backing", main, width, height, (0, 0, 3), badge, corner=corner),
        caption(collection, label + " | Route label", label, text, size, (-text_center, 0, 5), badge, "CENTER"),
    ]
    if any(shift):
        tether = stroke(collection, label + " | Route badge tether", [[(0, 0), shift]], main,
                        0.00115, (0, 0, 0), parent=root)
        hook = tether.modifiers.new("Follow badge placement", "HOOK")
        hook.object = badge
        hook.vertex_indices_set([1])
        hook.matrix_inverse = Matrix.Translation((-shift[0], -shift[1], 0))
        parts.append(tether)
    for obj in parts:
        for frame, visible in timing.items():
            obj.hide_render = not visible
            obj.hide_viewport = not visible
            for field in ("hide_render", "hide_viewport"):
                obj.keyframe_insert(data_path=field, frame=frame)


def street_label(collection, feature, paths, keys, layer, camera, layout, z, origin):
    props = feature.get("properties", {})
    name = props.get("name", layer["id"])
    size = layer.get("text_size", 0.015)
    width, height = text_box(name, size, 0.003)
    near = project(props["near"], origin) if "near" in props else paths[0][0][0]
    preferred = layout.screen(near)
    candidates = []
    for path, _ in paths:
        path = samples(path, layout.scale * 0.013)
        for a, point, b in zip(path, path[1:], path[2:]):
            sx, sy = layout.screen(point)
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            angle = (angle + math.pi / 2) % math.pi - math.pi / 2
            cos, sin = math.cos(angle), math.sin(angle)
            box = rect((sx, sy), abs(width * cos) + abs(height * sin), abs(width * sin) + abs(height * cos))
            distance = math.hypot(sx - preferred[0], sy - preferred[1])
            cost = layout.score(box) + distance * 650
            candidates.append((cost, point, angle, box))
    if not candidates:
        return
    _, point, angle, box = min(candidates)
    layout.boxes.append(box)
    root = link(collection, name + " | Street label anchor", at=(*point, z))
    root.rotation_euler.z = angle
    for axis in (0, 1):
        scale_driver(root, "scale", camera, 1, axis)
    halo = material(name + " | Halo", "152733", keys)
    ink = material(name + " | Street label", layer.get("color", "d8e6e9"), keys)
    backing = caption(collection, name + " | Halo", name, halo, size, (0, 0, 1), root, "CENTER")
    backing.data.offset = 0.00075
    caption(collection, name + " | Street label", name, ink, size, (0, 0, 3), root, "CENTER")


def badge_visible_in_pose(timing, layout):
    if layout.visible_frames is None:
        return True
    first, end = layout.visible_frames
    prior = next((on for frame, on in reversed(sorted(timing.items())) if frame <= first), False)
    return prior or any(on and first < frame <= end for frame, on in timing.items())


def place_route_badges(pending, camera, badge_z):
    # All geographic labels are registered before badges pick positions.
    for mode, collection, label, paths, layouts, owner, separation, color, timing, options in sorted(
            pending, key=lambda batch: batch[0] == "bus"):
        size = options.get("size", 0.013)
        width, height, text_center = label_box(label, size, 0.0045, options.get("x_padding"))
        layouts = [layout for layout in layouts if badge_visible_in_pose(timing, layout)] or layouts[:1]
        choice = choose_badge(paths, layouts, owner, width, height, separation)
        if choice is None:
            continue
        _, part, i, _, shift, _ = choice
        path, offsets = paths[part]
        vx, vy = offset = offsets[i] if offsets else (0, 0)
        for layout in layouts:
            x, y = layout.screen(path[i])
            x, y = x + vx * separation, y + vy * separation
            target = (x + shift[0], y + shift[1])
            layout.boxes.append(rect(target, width + 0.010, height + 0.010))
            if any(shift):
                layout.leaders.append(((x, y), target))
        route_badge(collection, label, path[i], offset, separation, color, timing, size, width, height,
                    badge_z + (20 if mode == "bus" else 0), camera, shift,
                    corner=options.get("corner", 0.003), text_center=text_center)


def styled_routes(collection, layer, packed, keys, draws, camera, layouts, z, end, scale, config, pending):
    label_options = layer.get("route_labels")
    width, separation = layer.get("width", 5), lane_spacing(layer)
    for number, (feature, paths) in enumerate(zip(layer["features"], packed), 1):
        props = feature.get("properties", {})
        name = props.get("name", f"{layer['id']} {number}")
        override = layer.get("route_overrides", {}).get(props.get("id"), {})
        route_keys, route_draws = keys, draws
        if "trace" in override:
            steps = config["steps"]
            route_keys, route_draws = layer_events({**layer, "trace": override["trace"]}, steps, schedule(steps))
        starts = route_starts(route_keys, route_draws)
        if label_options is not None:
            route_keys = route_opacity_keys(route_keys, route_draws)
        color = layer.get("uniform_color", override.get("color", props.get(
            layer.get("color_property", ""), layer.get("color", "4de2c1"))))
        mat = material(name, color, route_keys, override.get("opacity", layer.get("opacity", 1)))
        if label_options is not None and props.get("route_label", True) is not False:
            options = {**label_options, **props.get("route_label_timing", {})}
            label = str(props.get("route_label", props.get("id", name)))
            if options.get("uppercase", False):
                label = label.upper()
            timing = badge_keys(options, starts, end)
            if any(timing.values()):
                pending.append((layer.get("route_mode"), collection, label, paths, layouts,
                                (layer["id"], number), separation, color, timing, options))
        coordinate = override.get("trace_origin", layer.get("trace_origin"))
        remaining = []
        if route_draws:
            point = project(coordinate, config["origin"]) if coordinate is not None else None
            paths, remaining = split_trace(paths, point)
        obj = stroke(collection, name, [path for path, _ in paths], mat, width, (0, 0, z),
                     camera=camera, draws=route_draws, seed=0.01 if route_draws else 0)
        interline_stroke(obj, paths, camera, separation, scale)
        if remaining:
            later = [(first + (last - first + 1) // 2, last) for first, last in route_draws]
            branch = stroke(collection, name + " | Additional paths", [path for path, _ in remaining],
                            mat, width, (0, 0, z), camera=camera, draws=later)
            interline_stroke(branch, remaining, camera, separation, scale)


def add_layer(collection, layer, keys, draws, config, z, camera, format_name, mask_bounds,
              layouts, packed, scale, end, pending):
    layout = layouts[0]
    kind, name, origin = layer["kind"], layer["id"], config["origin"]
    if kind == "raster":
        raster_layer(collection, layer, keys, origin, z)
        return
    if kind == "street_labels":
        for feature, paths in zip(layer["features"], packed):
            street_label(collection, feature, paths, keys, layer, camera, layout, z, origin)
        return
    if kind == "route" and styled_route_layer(layer):
        styled_routes(collection, layer, packed, keys, draws, camera, layouts, z, end, scale, config, pending)
        return
    colors = {}
    shade_polygons = []
    for number, feature in enumerate(layer["features"], 1):
        properties, geometry = feature.get("properties", {}), feature["geometry"]
        label = properties.get("name", f"{name} {number}")
        color = properties.get(layer.get("color_property", ""), layer.get("color", "4de2c1"))
        if kind in {"callout", "station"}:
            callout(collection, layer, feature, origin, z, camera, format_name, keys, color, layouts)
            continue
        if color not in colors:
            colors[color] = material(name + " | " + color, color, keys, layer.get("opacity", 1))
        width = layer.get("width", 5)
        paths = []
        if kind == "boundary":
            polygons = feature_polygons(geometry, origin, layer.get("show_holes", True))
            shade_polygons.extend(polygons)
            if layer.get("fill"):
                interior = material(label + " | Translucent fill", color, keys, layer["fill"])
                map_fill(collection, label + " | Fill", polygons, interior, z - 100)
            paths = [ring + ([ring[0]] if ring[-1] != ring[0] else []) for polygon in polygons for ring in polygon]
        else:
            lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
            paths = [[project(point, origin) for point in line] for line in lines]
        stroke(collection, label, paths, colors[color], width, (0, 0, z), camera=camera, draws=draws)
    if shade_polygons and layer.get("outside_dim"):
        xmin, ymin, xmax, ymax = mask_bounds
        exterior = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
        dim = material(name + " | Outside dimming", "070c14", keys, layer["outside_dim"])
        map_fill(collection, name + " | Outside mask", shade_polygons, dim, z - 120, outside=exterior)


def step_frame(step, layers, origin, format_name, dimensions):
    preset = step.get("framing", {}).get(format_name, {})
    box = preset.get("bounds", step.get("bounds"))
    if box is not None:
        points = [project(box[:2], origin), project(box[2:], origin)]
    else:
        points = []
        for name in step["focus"]:
            layer = layers[name]
            if layer["kind"] == "raster":
                points.extend([project(layer["bounds"][:2], origin), project(layer["bounds"][2:], origin)])
            else:
                points.extend(project(point, origin) for feature in layer["features"]
                              for point in positions(feature["geometry"]))
    center = preset.get("center", step.get("center"))
    return frame_target(points, dimensions, preset.get("padding", step.get("padding", 1.25)),
                        project(center, origin) if center is not None else None, preset.get("min_scale", 0))


def animate_camera(camera, steps, timings, frames, height, scene):
    for step, (first, arrival, end), ((x, y), scale) in zip(steps, timings, frames):
        camera.location = (x, y, height)
        camera.data.ortho_scale = scale
        scene.timeline_markers.new(step["title"], frame=arrival)
        if first != arrival:
            scene.timeline_markers.new("Move to " + step["title"], frame=first)
        for frame in {arrival, end}:
            camera.keyframe_insert(data_path="location", frame=frame)
            camera.data.keyframe_insert(data_path="ortho_scale", frame=frame)


def title_cards(scene, camera, steps, timings, dimensions, metadata):
    collection = bpy.data.collections.new("Screen titles")
    scene.collection.children.link(collection)
    anchor = link(collection, "Screen coordinates", at=(0, 0, -50), parent=camera)
    for axis in (0, 1):
        scale_driver(anchor, "scale", camera, 1, axis)
    width, height = (value / max(dimensions) for value in dimensions)
    left, top = -width / 2 + 0.033, height / 2 - 0.045
    for step, (_, arrival, end) in zip(steps, timings):
        name = step["title"]
        keys = ({1: 1} if arrival == 1 else
                {1: 0, arrival - 1: 0, arrival + min(8, (end - arrival) // 3): 1})
        if end < timings[-1][2]:
            keys[max(arrival, end - min(9, (end - arrival) // 3))] = 1
            keys[end] = 0
        title = material(name + " | Heading", "f2faf9", sorted(keys.items()))
        caption(collection, name, name, title, 0.034, (left, top, 2), anchor)
        if step.get("subtitle"):
            subtitle = material(name + " | Context", "b0c6ca", sorted(keys.items()))
            caption(collection, name + " | Context", step["subtitle"], subtitle, 0.014,
                    (left, top - 0.032, 2), anchor)
        if step.get("note"):
            note = material(name + " | Map note", step.get("note_color", "c6d9df"), sorted(keys.items()))
            caption(collection, name + " | Map note", step["note"], note, 0.012,
                    (left, -height / 2 + 0.041, 2), anchor)
    if metadata.get("credit"):
        footer = material("Sources", "adc4cd", [(1, 1)])
        caption(collection, "Map sources", metadata["credit"], footer, 0.0105,
                (left, -height / 2 + 0.021, 2), anchor)


def opacity_curve(material):
    tree = material.node_tree
    if not tree or not tree.animation_data or not tree.animation_data.action:
        return None
    node = next((node for node in tree.nodes if node.label == "Layer opacity"), None)
    if node is None:
        return None
    animation = tree.animation_data
    channels = animation.action.layers[0].strips[0].channelbag(animation.action_slot)
    return channels.fcurves.find(node.inputs[0].path_from_id("default_value"))


def prepare_preview(scene):
    # Solid shading ignores node transparency. Mirror the zero-opacity
    # intervals onto viewport visibility while the material handles fades.
    curves = {mat: opacity_curve(mat) for mat in bpy.data.materials}
    visibility = {
        mat: [curve.evaluate(frame) > 1e-6 for frame in range(1, scene.frame_end + 1)]
        for mat, curve in curves.items() if curve is not None
    }
    for obj in scene.objects:
        materials = [slot.material for slot in obj.material_slots]
        if not materials or any(mat not in visibility for mat in materials):
            continue
        animation = obj.animation_data
        if animation and animation.action:
            continue  # Route badges already have viewport visibility keys.
        previous = None
        for frame, states in enumerate(zip(*(visibility[mat] for mat in materials)), 1):
            hidden = not any(states)
            if hidden != previous:
                obj.hide_viewport = hidden
                obj.keyframe_insert(data_path="hide_viewport", frame=frame)
                previous = hidden
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type = "RENDERED"
    scene.frame_set(scene.frame_start)


def build(config, format_name):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    dimensions = FORMATS[format_name]
    scene.name = "Geographic story | " + format_name.title()
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x, scene.render.resolution_y = dimensions
    scene.render.resolution_percentage = 100
    scene.render.fps = 30
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.view_transform = "Standard"
    if scene.world.node_tree is None:
        scene.world.use_nodes = True
    scene.world.node_tree.nodes.get("Background").inputs["Color"].default_value = paint(config.get("background", "14222e"))
    steps = config["steps"]
    layers = {layer["id"]: layer for layer in config["layers"]}
    timings = schedule(steps)
    frames = [step_frame(step, layers, config["origin"], format_name, dimensions) for step in steps]
    scene.frame_start, scene.frame_end = 1, timings[-1][2]
    scale = max(frame[1] for frame in frames)
    extent = bounds(center for center, _ in frames)
    mask_bounds = tuple(value + (-scale if i < 2 else scale) for i, value in enumerate(extent))
    height = max(1000, scale) + len(layers) * 400
    camera = link(scene.collection, "Map camera | " + format_name.title(), bpy.data.cameras.new("Top-down orthographic"))
    camera.data.type = "ORTHO"
    camera.data.clip_end = height * 2
    camera.data.passepartout_alpha = 0.95
    scene.camera = camera
    animate_camera(camera, steps, timings, frames, height, scene)
    packed = {name: route_paths(layer, config["origin"]) for name, layer in layers.items()
              if layer["kind"] in {"route", "street_labels"}
              and (styled_route_layer(layer) or layer["kind"] == "street_labels" or layer.get("avoid_labels"))}
    layouts = [Placement(pose, dimensions, (arrival, end))
               for pose, (_, arrival, end) in zip(frames, timings)]
    for step, layout in zip(steps, layouts):
        for name, paths in packed.items():
            layer = layers[name]
            if layer["kind"] == "street_labels" or not step["layers"].get(name):
                continue
            for number, path in enumerate(paths, 1):
                layout.add_route((name, number), path, lane_spacing(layer))
    stacking = {name: index * 400 for index, name in enumerate(layers, 1)}
    order = {"route": 0, "boundary": 0, "raster": 0, "street_labels": 1, "callout": 2, "station": 2}
    pending = []
    for layer in sorted(layers.values(), key=lambda item: order[item["kind"]]):
        name = layer["id"]
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        keys, draws = layer_events(layer, steps, timings)
        active_layouts = [layout for step, layout in zip(steps, layouts) if step["layers"].get(name)]
        add_layer(collection, layer, keys, draws, config, stacking[name], camera, format_name, mask_bounds,
                  active_layouts or layouts[:1], packed.get(name), scale, scene.frame_end, pending)
    place_route_badges(pending, camera, max(stacking.values()) + 320)
    title_cards(scene, camera, steps, timings, dimensions, config)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.region_3d.view_perspective = "CAMERA"
                space.clip_end = height * 2
                space.overlay.show_overlays = False
                space.shading.color_type = "MATERIAL"
                space.shading.background_type = "WORLD"
    prepare_preview(scene)
    return scene


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--format", required=True, choices=FORMATS)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    output = args.output.resolve()
    if output.exists():
        parser.error(f"Output already exists: {output}. Choose a fresh path to preserve edits.")
    output.parent.mkdir(parents=True, exist_ok=True)
    build(read_story(args.config), args.format)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))


if __name__ == "__main__":
    main()
