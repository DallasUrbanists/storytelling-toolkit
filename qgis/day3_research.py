"""Network service area and areal population allocation using QGIS 3.44."""
import argparse
import json
import math
from pathlib import Path
import sys

from building_footprints import osm_footprints, import_footprints
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsFillSymbol, QgsGeometry, QgsLineSymbol, QgsPointXY,
    QgsProcessingContext, QgsProject, QgsRectangle, QgsUnitTypes,
    QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes,
)

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
ALGORITHM = "native:serviceareafromlayer"
ROADS = {"residential", "living_street", "unclassified", "tertiary", "secondary",
         "primary", "service", "pedestrian", "footway", "path", "steps", "track"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def pedestrian_access(tags):
    foot = tags.get("foot")
    if foot in {"no", "private", "use_sidepath", "customers", "permit"}:
        return False
    if foot in {"yes", "designated", "permissive", "official"}:
        return True
    return (tags.get("highway") in ROADS
            and tags.get("access") not in {"no", "private", "customers", "permit"}
            and tags.get("sidewalk") not in {"no", "none", "separate"}
            and tags.get("service") != "driveway"
            and tags.get("motorroad") != "yes")


def osm_network(snapshot):
    """Use OSM geometry vertices directly. Crossings without a shared vertex stay disconnected."""
    if snapshot.get("remark") or not snapshot.get("osm3s", {}).get("timestamp_osm_base"):
        raise ValueError("A complete OSM snapshot and its timestamp are required")
    blocked = {e["id"] for e in snapshot["elements"] if e["type"] == "node"
               and (e.get("tags", {}).get("foot") in {"no", "private"}
                    or (e.get("tags", {}).get("access") in {"no", "private"}
                        and e.get("tags", {}).get("foot") not in {"yes", "designated", "permissive"})
                    or (e.get("tags", {}).get("barrier") in {"wall", "fence", "hedge", "retaining_wall"}
                        and e.get("tags", {}).get("foot") not in {"yes", "designated", "permissive"}))}
    lines = []
    for element in snapshot["elements"]:
        tags = element.get("tags", {})
        if element["type"] != "way" or not pedestrian_access(tags):
            continue
        direction = {"yes": "forward", "1": "forward", "-1": "backward"}.get(tags.get("oneway:foot"), "both")
        if len(element["nodes"]) != len(element["geometry"]):
            raise ValueError(f"Incomplete geometry in OSM way {element['id']}")
        for index, (a, b) in enumerate(zip(element["geometry"], element["geometry"][1:])):
            first, second = element["nodes"][index:index + 2]
            if first in blocked or second in blocked or a == b:
                continue
            lines.append({"type": "Feature", "geometry": {"type": "LineString",
                          "coordinates": [[p["lon"], p["lat"]] for p in (a, b)]},
                          "properties": {"osm_way_id": str(element["id"]),
                                         "direction": direction, "highway": tags["highway"]}})
    if not lines:
        raise ValueError("No pedestrian edges survived access filters")
    return {"type": "FeatureCollection", "features": lines}


def vector(path, name):
    layer = QgsVectorLayer(str(path), name, "ogr")
    if not layer.isValid() or not layer.crs().isValid() or layer.featureCount() < 1:
        raise ValueError(f"{name}: expected a nonempty vector layer with known CRS: {path}")
    return layer


def projected(layer, crs, context):
    import processing
    return processing.run("native:reprojectlayer", {"INPUT": layer, "TARGET_CRS": crs,
                                                   "OUTPUT": "memory:"}, context=context)["OUTPUT"]


def origins_for(corridor, spacing):
    origins = QgsVectorLayer(f"Point?crs={corridor.crs().authid()}", "Origins", "memory")
    features = []
    for f in corridor.getFeatures():
        for part in f.geometry().asGeometryCollection():
            length = part.length()
            intervals = max(1, math.ceil(length / spacing))
            for index in range(intervals + 1):
                origin = QgsFeature()
                origin.setGeometry(part.interpolate(length * index / intervals))
                features.append(origin)
    if len(features) < 2:
        raise ValueError("At least two distinct corridor origins are required")
    origins.dataProvider().addFeatures(features)
    origins.updateExtents()
    return origins


def service_area(network, origins, context, minutes=10, speed_kmh=4.8, snap_m=45):
    import processing
    if not all(math.isfinite(v) and v > 0 for v in (minutes, speed_kmh, snap_m)):
        raise ValueError("Duration, walking speed and maximum snap distance must be positive")
    result = processing.run(ALGORITHM, {
        "INPUT": network, "START_POINTS": origins, "STRATEGY": 0,
        "TRAVEL_COST": minutes * speed_kmh * 1000 / 60,
        "POINT_TOLERANCE": snap_m, "TOLERANCE": 0,
        "DIRECTION_FIELD": "direction", "VALUE_FORWARD": "forward", "VALUE_BACKWARD": "backward",
        "VALUE_BOTH": "both", "DEFAULT_DIRECTION": 2,
        "OUTPUT_LINES": "memory:", "OUTPUT_NON_ROUTABLE": "memory:",
    }, context=context)
    lines = [f.geometry() for f in result["OUTPUT_LINES"].getFeatures() if not f.geometry().isEmpty()]
    if not lines:
        raise ValueError("No reachable network. Check origin locations and pedestrian network coverage")
    # Native output repeats segments visited from multiple starts. Remove identical paths before noding.
    unique = {}
    for line in lines:
        for part in line.asMultiPolyline() if line.isMultipart() else [line.asPolyline()]:
            key = tuple((p.x(), p.y()) for p in part)
            if len(key) >= 2:
                unique.setdefault(min(key, key[::-1]), part)
    if not unique:
        raise ValueError("No reachable segments returned by QGIS")
    return QgsGeometry.unaryUnion([QgsGeometry.fromPolylineXY(p) for p in unique.values()]), result["OUTPUT_NON_ROUTABLE"].featureCount()


def region_layer(geom, crs, name):
    if geom.isNull() or geom.isEmpty() or not geom.isGeosValid():
        raise ValueError(f"{name}: empty or invalid derived geometry")
    geom.convertToMultiType()
    kind = QgsWkbTypes.displayString(geom.wkbType())
    layer = QgsVectorLayer(f"{kind}?crs={crs.authid()}", name, "memory")
    feature = QgsFeature()
    feature.setGeometry(geom)
    layer.dataProvider().addFeatures([feature])
    layer.updateExtents()
    return layer


def acs_values(rows):
    keys = ["state", "county", "tract", "block group"]
    header = rows[0]
    output = {}
    for raw in rows[1:]:
        row = dict(zip(header, raw, strict=True))
        population, moe = int(row["B01003_001E"]), int(row["B01003_001M"])
        key = "".join(row[k] for k in keys)
        if len(key) != 12 or key in output or population < 0 or moe < 0:
            raise ValueError(f"Invalid block-group estimate or margin for {key}")
        output[key] = population, moe
    return output


def allocate(catchment, block_groups, values, precision=100):
    rows = []
    for feature in block_groups.getFeatures():
        polygon = feature.geometry().makeValid()
        if not catchment.boundingBox().intersects(polygon.boundingBox()):
            continue
        area = polygon.area()
        overlap = catchment.intersection(polygon).area()
        if not (area > 0 and overlap > 0):
            continue
        key = str(feature["GEOID"])
        if key not in values:
            raise ValueError(f"Missing ACS estimate for intersecting block group {key}")
        population, moe = values[key]
        weight = min(1, overlap / area)
        rows.append(dict(geoid=key, population=population, moe90=moe, overlap_m2=overlap,
                         geography_m2=area, area_weight=weight, allocation=population * weight))
    if not rows:
        raise ValueError("No matching block groups overlap this catchment")
    estimate = sum(row["allocation"] for row in rows)
    return dict(estimate=estimate, rounded=int(precision * math.floor(estimate / precision + 0.5)),
                approximate_sampling_moe90=math.sqrt(sum((row["moe90"] * row["area_weight"]) ** 2 for row in rows)),
                approximate_sampling_error_excludes="spatial allocation, network coverage and polygon uncertainties",
                rows=rows)


def export_layer(layer, path, context, name, output_crs=None):
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG" if path.suffix == ".gpkg" else "GeoJSON"
    opts.layerName = name
    if path.exists() and opts.driverName == "GPKG":
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    if output_crs is not None:
        opts.ct = QgsCoordinateTransform(layer.crs(), output_crs, context.transformContext())
    error, msg, *_ = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(path), context.transformContext(), opts)
    if error != QgsVectorFileWriter.NoError:
        raise ValueError(f"Could not export {name}: {msg}")


def run(args):
    project = QgsProject.instance()
    crs = QgsCoordinateReferenceSystem(args.crs)
    equal_area = QgsCoordinateReferenceSystem("EPSG:5070")
    if not crs.isValid() or crs.isGeographic() or crs.mapUnits() != QgsUnitTypes.DistanceMeters:
        raise ValueError("Routing CRS must be projected in meters")
    project.setCrs(crs)
    project.setEllipsoid("NONE")
    context = QgsProcessingContext()
    context.setProject(project)
    context.setEllipsoid("NONE")
    config = args.input
    out = args.output
    gpkg = out / "Maple_Day_3.gpkg"
    if gpkg.exists():
        raise FileExistsError(f"Use a new output directory: {gpkg}")
    out.mkdir(parents=True, exist_ok=True)
    osm = read_json(config / "osm.json")
    write_json(args.work / "pedestrian_network.geojson", osm_network(osm))
    network = projected(vector(args.work / "pedestrian_network.geojson", "OSM pedestrian graph"), crs, context)
    corridor = projected(vector(config / "data/corridor.geojson", "Maple Avenue corridor"), crs, context)
    origins = origins_for(corridor, args.spacing)
    print(f"Routing {origins.featureCount()} origins against {network.featureCount()} pedestrian edges", flush=True)
    lines, rejected = service_area(network, origins, context, args.minutes, args.speed, args.snap)
    print(f"Reachable network: {lines.length() / 1000:.2f} km; {rejected} origins out of tolerance", flush=True)
    if rejected == origins.featureCount():
        raise ValueError("All origins rejected")
    reachable = region_layer(lines, crs, "Reachable pedestrian network")
    # The network is the reachability result. An off-network frontage width models spatial access.
    envelope = {}
    merged = lines.mergeLines()
    for width in {40, args.frontage, 90}:
        # Combining local buffers keeps GEOS from noding overlapping round caps for the
        # entire network at once. The union is mathematically the same buffer.
        paths = merged.asMultiPolyline() if merged.isMultipart() else [merged.asPolyline()]
        patches = [QgsGeometry.fromPolylineXY(path).buffer(width, 8) for path in paths]
        partial = [QgsGeometry.unaryUnion(patches[index:index + 128]) for index in range(0, len(patches), 128)]
        envelope[width] = QgsGeometry.unaryUnion(partial).makeValid()
        print(f"Frontage polygon: {width:g} m", flush=True)
    catchment = region_layer(envelope[args.frontage], crs, "10-minute walkshed estimate")
    if (config / "building-source.geojson").exists():
        buildings = import_footprints(vector(config / "building-source.geojson", "Building source"),
                                      args.building_id, args.building_source,
                                      args.verified_height_field, args.level_field)
    else:
        if not args.building_extent:
            raise ValueError("An illustrative building extent is required for OSM footprints")
        buildings = osm_footprints(osm, QgsRectangle(*args.building_extent))
    features = [("walkshed", catchment), ("pedestrian_network", network), ("reachable", reachable),
                ("building_footprints", buildings),
                ("corridor", corridor), ("origins", origins)]
    for name in ("rail", "bus", "stations", "stops", "connections", "zoning", "oak-lawn"):
        path = (config / (name + ".geojson")) if (config / (name + ".geojson")).exists() else (config / "data" / (name + ".geojson"))
        if path.exists():
            features.append((name, vector(path, name.replace("_", " ").title())))
    stats = None
    acquisition = read_json(config / "acquisition.json")
    if all((config / name).exists() for name in ("block-groups.geojson", "acs-2024.json")):
        block_groups = vector(config / "block-groups.geojson", "2024 Census block groups")
        features.append(("block_groups_2024", block_groups))
        geo = projected(block_groups, equal_area, context)
        transform = QgsCoordinateTransform(crs, equal_area, project)
        counts = acs_values(read_json(config / "acs-2024.json"))
        totals = {}
        for width, shape in envelope.items():
            shape.transform(transform)
            totals[str(width)] = allocate(shape, geo, counts)
        stats = {"baseline": totals[str(args.frontage)], "frontage_sensitivity": {
                    width: value["rounded"] for width, value in totals.items()},
                 "population_source": acquisition["acs"][0],
                 "boundary_source": acquisition["tiger"][0], "period": "2020–2024", "minutes": args.minutes,
                 "approval": {"approved_by": None, "approved_value": None}}
    else:
        stats = {"limitation": "ACS or matching TIGER block-group inputs were unavailable. No population estimate was calculated."}
    write_json(out / "population_review.json", stats)

    for name, source in features:
        export_layer(source, gpkg, context, name)
        registered = QgsVectorLayer(f"{gpkg}|layername={name}", source.name(), "ogr")
        project.addMapLayer(registered)
        project.layerTreeRoot().findLayer(registered.id()).setItemVisibilityChecked(
            name in {"walkshed", "reachable", "corridor", "origins", "stations"})
        if name == "walkshed":
            registered.renderer().setSymbol(QgsFillSymbol.createSimple(
                {"color": "103,194,163,85", "outline_color": "53,125,104,180", "outline_width": "0.24"}))
        if name in {"reachable", "corridor"}:
            registered.renderer().setSymbol(QgsLineSymbol.createSimple(
                {"line_color": "#217f7b" if name == "reachable" else "#c57c15",
                 "line_width": "0.28" if name == "reachable" else "0.9"}))
    root = project.layerTreeRoot()
    by_name = {layer.name(): layer for layer in project.mapLayers().values()}
    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder([by_name[layer.name()] for _, layer in reversed(features)])
    extent = QgsRectangle(catchment.extent())
    extent.scale(1.15)
    from qgis.core import QgsReferencedRectangle
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, crs))
    project.setTitle("Maple Avenue | Day 3 geographic research")
    if not project.write(str(out / "Maple_Research.qgz")):
        raise ValueError("Could not save QGIS project")
    export_layer(catchment, out / "walkshed.geojson", context, "walkshed", WGS84)
    export_layer(buildings, out / "buildings.geojson", context, "building_footprints", WGS84)
    write_json(out / "walkshed_method.json", {
        "source": "© OpenStreetMap contributors", "attribution": "https://www.openstreetmap.org/copyright",
        "query_url": osm["source_url"], "data_date": osm["osm3s"]["timestamp_osm_base"],
        "query": osm["query"], "corridor_source": "Day 2 City of Dallas street centerline, Mockingbird Lane to Oak Lawn Avenue",
        "algorithm": ALGORITHM, "path": "Shortest network distance with a fixed walking speed; time budget converted to meters",
        "walking_speed_kmh": args.speed, "minutes": args.minutes, "origin_spacing_m": args.spacing,
        "origins": origins.featureCount(), "non_routable_origins": rejected, "max_origin_snap_m": args.snap,
        "crs": crs.authid(), "area_weighting_crs": equal_area.authid(), "frontage_width_m": args.frontage,
        "area_km2": next(catchment.getFeatures()).geometry().area() / 1e6,
        "limits": "Tagged access, barriers and foot-specific one-way directions used. Untagged local or arterial links can lack verified sidewalks. Crossing delays, slope, gates without usable tags, and accessibility conditions are not modeled. Polygon is the dissolved width around reachable edges and is a frontage model, not parcel-by-parcel access.",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--crs", required=True)
    parser.add_argument("--speed", type=float, default=4.8)
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--spacing", type=float, default=100)
    parser.add_argument("--snap", type=float, default=45)
    parser.add_argument("--frontage", type=float, default=65)
    parser.add_argument("--building-extent", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--building-id", default="OBJECTID")
    parser.add_argument("--building-source", default="Imported footprints")
    parser.add_argument("--verified-height-field")
    parser.add_argument("--level-field")
    args = parser.parse_args()
    if any(not math.isfinite(value) or value <= 0 for value in (args.frontage, args.spacing)):
        parser.error("Frontage and origin spacing must be positive")
    args.work.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], False)
    app.initQgis()
    plugins = str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins")
    if plugins not in sys.path:
        sys.path.append(plugins)
    from processing.core.Processing import Processing
    Processing.initialize()
    run(args)
    QgsProject.instance().clear()


if __name__ == "__main__":
    main()
