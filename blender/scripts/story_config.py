"""Configuration and timing for editable geographic stories."""
import json
import math
from pathlib import Path


FORMATS = {"landscape": (1920, 1080), "portrait": (1080, 1920)}
MAPLE_BUS_BADGE_REVEAL_FRAMES = 6
BLENDER_HOME = Path(__file__).resolve().parents[1]
KINDS = {"boundary", "route", "callout", "station", "raster", "street_labels", "municipalities"}
GEOMETRIES = {
    "boundary": {"Polygon", "MultiPolygon"},
    "route": {"LineString", "MultiLineString"},
    "street_labels": {"LineString", "MultiLineString"},
    "callout": {"Point"},
    "station": {"Point"},
    "municipalities": {"Point", "Polygon", "MultiPolygon"},
}


def project(coordinate, origin):
    lon, lat = coordinate[:2]
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("Expected WGS 84 longitude/latitude")
    lon0, lat0 = origin
    return (111320 * math.cos(math.radians(lat0)) * (lon - lon0), 111320 * (lat - lat0))


def bounds(points):
    x, y = zip(*points)
    return min(x), min(y), max(x), max(y)


def frame_target(points, dimensions, padding, center=None, min_scale=0):
    xmin, ymin, xmax, ymax = bounds(points)
    x, y = center if center is not None else ((xmin + xmax) / 2, (ymin + ymax) / 2)
    long_edge = max(dimensions)
    width, height = (value / long_edge for value in dimensions)
    scale = max(
        2 * max(abs(xmin - x), abs(xmax - x)) / width * padding,
        2 * max(abs(ymin - y), abs(ymax - y)) / height * padding,
        min_scale,
        1,
    )
    return (x, y), scale


def positions(geometry):
    kind, coordinates = geometry["type"], geometry["coordinates"]
    if kind == "Point":
        yield coordinates
        return
    if kind == "LineString":
        parts = [coordinates]
    elif kind in {"Polygon", "MultiLineString"}:
        parts = coordinates
    else:
        if kind != "MultiPolygon":
            raise ValueError(f"Unsupported GeoJSON geometry {kind}")
        parts = [ring for polygon in coordinates for ring in polygon]
    if not parts:
        raise ValueError(f"Empty {kind} coordinates")
    for part in parts:
        if kind in {"Polygon", "MultiPolygon"}:
            if len(part) < 4 or part[0][:2] != part[-1][:2] or len({tuple(p[:2]) for p in part}) < 3:
                raise ValueError("Polygon rings require at least three distinct positions and a closing point")
        elif len(part) < 2:
            raise ValueError("LineStrings require at least two positions")
        yield from part


def municipality_center(geometry, origin):
    """Project a published center point, or find the full boundary's area centroid."""
    if geometry["type"] == "Point":
        return project(geometry["coordinates"], origin)
    parts = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        parts = [parts]
    weight = x = y = 0.0
    for polygon in parts:
        for i, ring in enumerate(polygon):
            points = [project(p, origin) for p in ring]
            edges = list(zip(points, points[1:]))
            cross = [a[0] * b[1] - b[0] * a[1] for a, b in edges]
            area = sum(cross)
            if abs(area) < 1e-9:
                continue
            signed = (1 if i == 0 else -1) * abs(area)
            weight += signed
            x += signed * sum((a[0] + b[0]) * k for (a, b), k in zip(edges, cross)) / (3 * area)
            y += signed * sum((a[1] + b[1]) * k for (a, b), k in zip(edges, cross)) / (3 * area)
    if weight <= 0:
        raise ValueError("Municipality geometry needs a nonempty polygon")
    return x / weight, y / weight


def check_padding(value, name):
    if value != "character" and (type(value) not in (int, float) or not 0 <= value <= 0.1):
        raise ValueError(f"{name}: expected 'character' or a fraction from 0 to 0.1")


def check_route_labels(options, name):
    if not isinstance(options, dict):
        raise ValueError(f"{name}: route label settings must be an object")
    if type(options.get("duration", 64)) is not int or options.get("duration", 64) < 1:
        raise ValueError(f"{name}: route label duration must be a positive number of frames")
    size = options.get("size", 0.013)
    if type(size) not in (int, float) or not 0 < size < 1:
        raise ValueError(f"{name}: route label size must be a positive fraction")
    if "uppercase" in options and type(options["uppercase"]) is not bool:
        raise ValueError(f"{name}: route label uppercase must be true or false")
    if options.get("text_weight", "regular") not in ("regular", "bold"):
        raise ValueError(f"{name}: route label text_weight must be regular or bold")
    if type(options.get("square_minimum", False)) is not bool:
        raise ValueError(f"{name}: route label square_minimum must be true or false")
    if type(options.get("reveal_frames", 0)) is not int or options.get("reveal_frames", 0) < 0:
        raise ValueError(f"{name}: route label reveal_frames must be a nonnegative frame count")
    if "corner" in options and (type(options["corner"]) not in (int, float) or not 0 <= options["corner"] <= 0.1):
        raise ValueError(f"{name}: route label corner must be between 0 and 0.1")
    if "x_padding" in options:
        check_padding(options["x_padding"], f"{name}: route label x_padding")
    windows = options.get("windows", [])
    if not isinstance(windows, list):
        raise ValueError(f"{name}: route label windows must be a list")
    for pair in windows:
        if (not isinstance(pair, list) or len(pair) != 2
                or any(type(value) is not int for value in pair) or not 1 <= pair[0] <= pair[1]):
            raise ValueError(f"{name}: each route label window must be two increasing positive frames")


def color_option(value, name):
    if not isinstance(value, str) or len(value.removeprefix("#")) != 6 or any(
            c not in "0123456789abcdefABCDEF" for c in value.removeprefix("#")):
        raise ValueError(f"{name}: expected a six-digit hex color")


def route_options(options, name, origin):
    if "color" in options:
        color_option(options["color"], name)
    if "opacity" in options:
        value = options["opacity"]
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError(f"{name}: opacity must be between 0 and 1")
    if "trace" in options and (type(options["trace"]) is not int or options["trace"] < 0):
        raise ValueError(f"{name}: trace must be a nonnegative integer frame count")
    if "trace_origin" in options:
        point = options["trace_origin"]
        if (not isinstance(point, list) or len(point) != 2
                or any(type(value) not in (int, float) for value in point)):
            raise ValueError(f"{name}: trace_origin must be a [longitude, latitude] pair")
        project(point, origin)


def select_direction(feature, selector, name):
    if selector in (None, "all"):
        return feature
    if not isinstance(selector, str):
        raise ValueError(f"{name}: direction must be 'all', a GTFS direction ID or headsign")
    options = feature.get("properties", {}).get("directions", [])
    matches = [option for option in options if selector == option["direction_id"]
               or selector.casefold() == option["headsign"].casefold()]
    if len(matches) != 1:
        names = ", ".join(f"{option['direction_id']} ({option['headsign']})" for option in options)
        raise ValueError(f"{name}: direction {selector!r} needs one match. Available directions: {names or 'none'}")
    result = dict(feature)
    result["geometry"] = matches[0]["geometry"]
    return result


def apply_style_preset(config):
    preset = config.setdefault("style_preset", "maple")
    if preset is None:
        return
    if preset != "maple":
        raise ValueError(f"Unknown style_preset: {preset!r}")
    style = json.loads((BLENDER_HOME / "presets/maple.json").read_text(encoding="utf-8"))
    config.setdefault("editorial_text", style["editorial_text"])
    for layer in config["layers"]:
        if (layer["kind"] in {"boundary", "route", "raster"} and not layer.get("delay")
                and not layer.get("trace") and "route_labels" not in layer):
            layer.setdefault("opening_visible", True)
        if layer["kind"] in {"callout", "station"}:
            defaults = {
                "label_backing": True, "auto_place": True, "text_weight": "bold",
                "animate_callout": True,
                "backing_corner": 0, "backing_x_padding": "character",
                "backing_color": "ffffff", "leader_color": "ffffff",
                "dot_color": "ffffff", "casing_color": "ffffff",
            }
            for key, value in defaults.items():
                layer.setdefault(key, value)
        if layer["kind"] == "route":
            mode = layer.get("route_mode")
            if mode in ("bus", "rail"):
                for key, value in style[mode].items():
                    if key == "route_overrides":
                        if layer.get("source") == "dart-rail":
                            overrides = layer.setdefault(key, {})
                            for service, defaults in value.items():
                                if "select" not in layer or service in layer["select"]:
                                    user = overrides.setdefault(service, {})
                                    for option, setting in defaults.items():
                                        user.setdefault(option, setting)
                    else:
                        layer.setdefault(key, value)
            if mode in ("bus", "rail"):
                layer.setdefault("route_labels", {})
            if isinstance(layer.get("route_labels"), dict):
                padding = 0.0015 if layer.get("route_mode") == "bus" else "character"
                for key, value in {"uppercase": True, "corner": 0, "x_padding": padding}.items():
                    layer["route_labels"].setdefault(key, value)
                if mode in ("bus", "rail"):
                    layer["route_labels"].setdefault("text_weight", "bold")
                    layer["route_labels"].setdefault("square_minimum", True)
                if mode == "bus":
                    layer["route_labels"].setdefault("reveal_frames", MAPLE_BUS_BADGE_REVEAL_FRAMES)
                layer.setdefault("trace", 30)


def read_story(path):
    path = Path(path)
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    for layer in config["layers"]:
        if layer.get("source") == "dart-rail":
            if layer["kind"] != "route":
                raise ValueError("The dart-rail source requires a route layer")
            layer["route_mode"] = "rail"
    apply_style_preset(config)
    layers = config["layers"]
    if not layers or not config["steps"]:
        raise ValueError("A story needs at least one layer and one step")
    layer_ids = {layer["id"] for layer in layers}
    if len(layer_ids) != len(layers):
        raise ValueError("Layer IDs must be unique")
    for layer in layers:
        name, kind = layer["id"], layer["kind"]
        if kind not in KINDS:
            raise ValueError(f"{name}: unknown layer kind {kind!r}")
        for option in ("delay", "fade", "trace"):
            value = layer.get(option, 0)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name}: {option} must be a nonnegative integer frame count")
        if "trace_easing" in layer and (kind != "route" or layer["trace_easing"] not in ("default", "ease_out")):
            raise ValueError(f"{name}: route trace_easing must be default or ease_out")
        if "shared_trace_speed" in layer and (kind != "route" or type(layer["shared_trace_speed"]) is not bool):
            raise ValueError(f"{name}: shared_trace_speed must be a boolean on a route layer")
        if "trace_stagger" in layer and (type(layer["trace_stagger"]) is not int or layer["trace_stagger"] < 0):
            raise ValueError(f"{name}: trace_stagger must be a nonnegative frame count")
        if kind == "municipalities" and layer.get("placement", "center") not in ("center", "dynamic"):
            raise ValueError(f"{name}: municipality placement must be 'center' or 'dynamic'")
        if "route_labels" in layer:
            if kind != "route":
                raise ValueError(f"{name}: route_labels must be used on a route layer")
            check_route_labels(layer["route_labels"], name)
        for option in ("show_holes", "label_backing", "auto_place", "opening_visible", "animate_callout"):
            if option in layer and type(layer[option]) is not bool:
                raise ValueError(f"{name}: {option} must be true or false")
        if "interline" in layer:
            interline = layer["interline"]
            if kind != "route" or not isinstance(interline, dict) or any(
                    type(value) not in (int, float) or not 0 < value < float("inf")
                    for value in interline.values()):
                raise ValueError(f"{name}: interline settings must be positive numbers on a route layer")
        layer["path"] = (BLENDER_HOME / "assets/dart-rail.geojson" if layer.get("source") == "dart-rail"
                         else (path.parent / layer["file"]).resolve())
        if kind == "raster":
            if not layer["path"].is_file():
                raise ValueError(f"{name}: raster file is missing")
            continue
        data = json.loads(layer["path"].read_text(encoding="utf-8-sig"))
        if data["type"] != "FeatureCollection":
            raise ValueError(f"{name}: expected a GeoJSON FeatureCollection")
        crs = data.get("crs")
        if crs and not crs["properties"]["name"].upper().endswith(("CRS84", ":4326")):
            raise ValueError(f"{name}: export this layer as WGS 84 from QGIS")
        include = layer.get("select")
        layer["features"] = [
            feature for feature in data["features"]
            if include is None or feature.get("properties", {}).get("id") in include
        ]
        if not layer["features"]:
            raise ValueError(f"{name}: no selected features")
        if "route_mode" in layer and (kind != "route" or layer["route_mode"] not in ("bus", "rail")):
            raise ValueError(f"{name}: route_mode must be 'bus' or 'rail' on a route layer")
        if "uniform_color" in layer:
            if kind != "route":
                raise ValueError(f"{name}: uniform_color is only supported on a route layer")
            color_option(layer["uniform_color"], f"{name}/uniform_color")
        if kind == "route":
            route_options(layer, name, config["origin"])
            select = layer.get("direction", "all")
            if not isinstance(select, str) or not select.strip():
                raise ValueError(f"{name}: direction must be 'all', a GTFS direction ID or headsign")
            overrides = layer.get("route_overrides", {})
            if not isinstance(overrides, dict):
                raise ValueError(f"{name}: route_overrides must be an object keyed by feature id")
            ids = {feature.get("properties", {}).get("id") for feature in layer["features"]}
            if set(overrides) - ids:
                raise ValueError(f"{name}: unknown route IDs {sorted(set(overrides) - ids)}")
            selected = []
            for feature in layer["features"]:
                fid = feature.get("properties", {}).get("id")
                options = overrides.get(fid, {})
                if not isinstance(options, dict) or set(options) - {"trace", "trace_origin", "direction", "color", "opacity"}:
                    raise ValueError(f"{name}/{fid}: invalid route override")
                route_options(options, f"{name}/{fid}", config["origin"])
                selected.append(select_direction(feature, options.get("direction", select), f"{name}/{fid}"))
            layer["features"] = selected
        if kind in {"callout", "station"}:
            for option in ("backing_color", "leader_color", "dot_color", "casing_color"):
                if option in layer:
                    color_option(layer[option], f"{name}/{option}")
            corner = layer.get("backing_corner", 0)
            if type(corner) not in (int, float) or not 0 <= corner <= 0.1:
                raise ValueError(f"{name}: backing_corner must be between 0 and 0.1")
            if "backing_x_padding" in layer:
                check_padding(layer["backing_x_padding"], f"{name}/backing_x_padding")
        for feature in layer["features"]:
            geometry = feature["geometry"]
            properties = feature.get("properties", {})
            if kind == "route" and "route_label_timing" in properties:
                check_route_labels(properties["route_label_timing"], name)
            if geometry["type"] not in GEOMETRIES[kind]:
                raise ValueError(f"{name}: {geometry['type']} is unsupported for {kind}")
            for coordinate in positions(geometry):
                project(coordinate, config["origin"])
    for step in config["steps"]:
        visibility = step["layers"]
        for layer in layers:
            if layer["kind"] == "municipalities":
                enabled = config.get("municipality_labels", True) and step.get("municipality_labels", True)
                visibility.setdefault(layer["id"], 1)
                if not enabled or not layer.get("labels", True):
                    visibility[layer["id"]] = 0
        missing = (set(visibility) | set(step.get("focus", []))) - layer_ids
        if missing:
            raise ValueError(f"{step['title']}: unknown layers {sorted(missing)}")
        if any(not 0 <= value <= 1 for value in visibility.values()):
            raise ValueError("Layer opacity must be between 0 and 1")
        if not step.get("focus") and "bounds" not in step:
            raise ValueError(f"{step['title']}: provide focus layers or bounds")
    schedule(config["steps"])
    return config


def schedule(steps):
    """Each step owns its incoming transition and following hold."""
    last_end = 0
    result = []
    for step in steps:
        hold, transition = step["hold"], step.get("transition", 0)
        if type(hold) is not int or hold < 1 or type(transition) is not int or transition < 0:
            raise ValueError("Hold must be positive and transition must be nonnegative integer frames")
        first = last_end + 1
        arrival = first + transition if result else first
        last_end = arrival + hold - 1
        result.append((first, arrival, last_end))
    return result


def outgoing_fade_end(first, arrival):
    return first + (arrival - first) / 2


def layer_events(layer, steps, timings):
    """Return opacity keys and draw-on intervals for a layer."""
    keys, draws = {1: 0}, []
    current = 0
    for step, (first, arrival, end) in zip(steps, timings):
        target = step["layers"].get(layer["id"], 0)
        if target == current:
            continue
        if current == 0:
            begin = min(arrival + layer.get("delay", 0), end)
        else:
            begin = first
        outgoing = target == 0 and arrival > first
        finish = outgoing_fade_end(first, arrival) if outgoing else min(begin + layer.get("fade", 12), end)
        keys[begin if outgoing else max(1, begin - 1)] = current
        keys[finish] = target
        if begin == 1 and layer.get("opening_visible"):
            keys[1] = target
        if current == 0 and layer.get("trace", 0):
            draws.append((begin, min(begin + layer["trace"], end)))
        current = target
    return sorted(keys.items()), draws


def route_starts(keys, draws):
    if draws:
        return [begin for begin, _ in draws]
    starts = [previous + 1 for (previous, opacity), (_, target) in zip(keys, keys[1:]) if opacity == 0 < target]
    return ([keys[0][0]] if keys[0][1] else []) + starts


def badge_keys(options, starts, end):
    windows = options.get("windows")
    if windows is None:
        duration = options.get("duration", 64)
        windows = [(first, first + duration - 1) for first in starts]
    return {frame: int(any(first <= frame <= last for first, last in windows))
            for frame in sorted({1, *(first for first, _ in windows if first <= end),
                                *(last + 1 for _, last in windows if last < end)})}


def shared_trace_intervals(lengths_by_route, baseline_frames, stagger=0):
    """Return each spline's start/end offset in frames at a single distance per frame."""
    totals = [sum(parts) for parts in lengths_by_route]
    if not baseline_frames or not any(totals):
        return [[] for _ in totals]
    speed = min(length for length in totals if length > 0) / baseline_frames
    result = []
    for index, parts in enumerate(lengths_by_route):
        frame = index * stagger
        intervals = []
        for length in parts:
            end = frame + length / speed
            intervals.append((frame, end))
            frame = end
        result.append(intervals)
    return result


def badge_opacity_keys(timing, reveal_frames):
    if not reveal_frames:
        return [(1, 1)]
    keys = {1: 0}
    entries = []
    for frame, visible in sorted(timing.items()):
        if not entries or entries[-1][1] != visible:
            entries.append((frame, visible))
    for i, (frame, visible) in enumerate(entries):
        keys[frame] = 0
        if visible:
            limit = entries[i+1][0]-1 if i+1 < len(entries) else frame+reveal_frames
            keys[min(frame+reveal_frames,limit)] = 1
            if i+1 < len(entries):
                keys[limit] = 1
    return sorted(keys.items())


def route_opacity_keys(keys, draws):
    if not draws:
        return keys
    reveal = dict(keys)
    for begin, end in draws:
        if begin < end:
            target = next((value for frame, value in keys if frame >= begin and value > 0), 0)
            reveal[begin] = max(reveal.get(begin, 0), target * 0.62)
    return sorted(reveal.items())
