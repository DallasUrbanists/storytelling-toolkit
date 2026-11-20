"""Configuration and timing for editable geographic stories."""
import json
import math
from pathlib import Path


FORMATS = {"landscape": (1920, 1080), "portrait": (1080, 1920)}
KINDS = {"boundary", "route", "callout", "station", "raster", "street_labels"}
GEOMETRIES = {
    "boundary": {"Polygon", "MultiPolygon"},
    "route": {"LineString", "MultiLineString"},
    "street_labels": {"LineString", "MultiLineString"},
    "callout": {"Point"},
    "station": {"Point"},
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


def check_route_labels(options, name):
    if not isinstance(options, dict):
        raise ValueError(f"{name}: route label settings must be an object")
    if type(options.get("duration", 64)) is not int or options.get("duration", 64) < 1:
        raise ValueError(f"{name}: route label duration must be a positive number of frames")
    size = options.get("size", 0.013)
    if type(size) not in (int, float) or not 0 < size < 1:
        raise ValueError(f"{name}: route label size must be a positive fraction")
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


def read_story(path):
    path = Path(path)
    config = json.loads(path.read_text(encoding="utf-8-sig"))
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
        if "route_labels" in layer:
            if kind != "route":
                raise ValueError(f"{name}: route_labels must be used on a route layer")
            check_route_labels(layer["route_labels"], name)
        for option in ("show_holes", "label_backing", "auto_place"):
            if option in layer and type(layer[option]) is not bool:
                raise ValueError(f"{name}: {option} must be true or false")
        if "interline" in layer:
            interline = layer["interline"]
            if kind != "route" or not isinstance(interline, dict) or any(
                    type(value) not in (int, float) or not 0 < value < float("inf")
                    for value in interline.values()):
                raise ValueError(f"{name}: interline settings must be positive numbers on a route layer")
        layer["path"] = (path.parent / layer["file"]).resolve()
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
        if kind == "route":
            route_options(layer, name, config["origin"])
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
                selected.append(select_direction(feature, options.get("direction"), f"{name}/{fid}"))
            layer["features"] = selected
        if kind in {"callout", "station"}:
            for option in ("backing_color", "leader_color", "dot_color"):
                if option in layer:
                    color_option(layer[option], f"{name}/{option}")
            for option in ("backing_corner", "backing_x_padding"):
                if option in layer and (type(layer[option]) not in (int, float) or not 0 <= layer[option] <= 0.1):
                    raise ValueError(f"{name}: {option} must be between 0 and 0.1")
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
        finish = min(begin + layer.get("fade", 12), end)
        keys[max(1, begin - 1)] = current
        keys[finish] = target
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


def route_opacity_keys(keys, draws):
    if not draws:
        return keys
    reveal = dict(keys)
    for begin, end in draws:
        if begin < end:
            target = next((value for frame, value in keys if frame >= begin and value > 0), 0)
            reveal[begin] = max(reveal.get(begin, 0), target * 0.62)
    return sorted(reveal.items())
