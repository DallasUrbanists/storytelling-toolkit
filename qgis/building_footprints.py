"""Repair source footprint polygons and normalize stable IDs and height semantics."""
import math

from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsRectangle, QgsVectorLayer, QgsWkbTypes


def positive(value):
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def polygonal(geometry):
    valid = geometry.makeValid()
    if valid.type() == QgsWkbTypes.PolygonGeometry:
        return valid
    parts = [part for part in valid.asGeometryCollection()
             if part.type() == QgsWkbTypes.PolygonGeometry]
    return QgsGeometry.unaryUnion(parts) if parts else QgsGeometry()


def import_footprints(source, id_field, source_name, verified_height_field=None, level_field=None):
    """Pass a verified height field only after verifying its units and definition in source metadata."""
    records = {}
    for feature in source.getFeatures():
        id_ = str(feature[id_field]).strip()
        if id_ in {"", "NULL", "None"} or id_ in records:
            raise ValueError(f"Missing or duplicate source building ID: {id_}")
        geometry = polygonal(feature.geometry())
        if geometry.isEmpty():
            continue
        records[id_] = (geometry, positive(feature[verified_height_field]) if verified_height_field else None,
                        positive(feature[level_field]) if level_field else None, None)
    return footprint_layer(records, source.crs().authid(), source_name)


def footprint_layer(records, crs, source):
    output = QgsVectorLayer(f"MultiPolygon?crs={crs}", "Building footprints", "memory")
    fields = [("building_id", QVariant.String), ("source", QVariant.String),
              ("height_verified_m", QVariant.Double), ("levels", QVariant.Double),
              ("height_unverified_m", QVariant.Double)]
    output.dataProvider().addAttributes([QgsField(name, kind) for name, kind in fields])
    output.updateFields()
    features = []
    for id_, (geometry, height, levels, unverified) in records.items():
        if geometry.isEmpty():
            continue
        geometry.convertToMultiType()
        feature = QgsFeature(output.fields())
        feature.setGeometry(geometry)
        feature.setAttributes([id_, source, height, levels, unverified])
        features.append(feature)
    if not features:
        raise ValueError("No valid building footprints in selected area")
    output.dataProvider().addFeatures(features)
    output.updateExtents()
    return output


def osm_footprints(snapshot, detail):
    ways = {e["id"]: e for e in snapshot["elements"] if e["type"] == "way"}
    records = {}
    used_outline_ways = set()

    def points(way):
        from qgis.core import QgsPointXY
        return [QgsPointXY(p["lon"], p["lat"]) for p in way["geometry"]]

    def add(kind, element, geometry):
        if geometry.isEmpty() or not geometry.boundingBox().intersects(detail):
            return
        tags = element["tags"]
        height = str(tags.get("height", "")).removesuffix(" m")
        records[f"osm:{kind}:{element['id']}"] = (
            polygonal(geometry), None, positive(tags.get("building:levels")), positive(height))

    for relation in snapshot["elements"]:
        if relation["type"] != "relation" or relation["tags"].get("type") != "multipolygon":
            continue
        members = [m for m in relation["members"] if m["type"] == "way"]
        if any(m["ref"] not in ways for m in members):
            continue
        shells = {}
        for role in ("outer", "inner"):
            edges = [QgsGeometry.fromPolylineXY(points(ways[m["ref"]]))
                     for m in members if (m.get("role") or "outer") == role]
            # Polygonize chains without requiring every individual member to be closed.
            polygons = QgsGeometry.polygonize(edges).asGeometryCollection() if edges else []
            shells[role] = QgsGeometry.unaryUnion(polygons) if polygons else QgsGeometry()
        if not shells["outer"].isEmpty():
            shape = shells["outer"]
            if not shells["inner"].isEmpty():
                shape = shape.difference(shells["inner"])
            add("relation", relation, shape)
            used_outline_ways.update(m["ref"] for m in members)
    for id_, way in ways.items():
        if id_ in used_outline_ways or way["tags"].get("building") in {None, "no"}:
            continue
        outline = points(way)
        if len(outline) >= 4 and outline[0] == outline[-1]:
            add("way", way, QgsGeometry.fromPolygonXY([outline]))
    return footprint_layer(records, "EPSG:4326", "© OpenStreetMap contributors")
