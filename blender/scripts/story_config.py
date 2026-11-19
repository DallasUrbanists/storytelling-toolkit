"""Configuration and timing for editable geographic stories."""
import json
import math
from pathlib import Path


FORMATS = {"landscape": (1920, 1080), "portrait": (1080, 1920)}
KINDS = {"boundary", "route", "callout", "station", "raster"}
GEOMETRIES = {
    "boundary": {"Polygon", "MultiPolygon"},
    "route": {"LineString", "MultiLineString"},
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
        for feature in layer["features"]:
            geometry = feature["geometry"]
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
