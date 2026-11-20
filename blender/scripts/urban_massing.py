"""Extrude repaired Polygon or MultiPolygon footprints into editable solids."""
import math

import bpy
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

from build_story import link, oriented_ring, paint
from story_config import project


def height_for(properties, floor_height_m, fallback_m):
    verified = properties.get("height_verified_m")
    levels = properties.get("levels")
    for value in (verified, levels, floor_height_m, fallback_m):
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                  or not math.isfinite(value) or value <= 0):
            raise ValueError("Building heights and levels must be positive finite numbers")
    if verified is not None:
        return verified, "verified"
    if levels is not None:
        return levels * floor_height_m, "levels × assumed floor height"
    return fallback_m, "illustrative fallback"


def massing_material():
    mat = bpy.data.materials.new("Off-white massing | object alpha")
    mat.diffuse_color = paint("ede8df")
    mat.surface_render_method = "DITHERED"
    mat.use_backface_culling = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = mat.diffuse_color
    bsdf.inputs["Roughness"].default_value = 0.8
    info = nodes.new("ShaderNodeObjectInfo")
    links.new(info.outputs["Alpha"], bsdf.inputs["Alpha"])
    return mat


def geometry_parts(geometry):
    kind = geometry["type"]
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError(f"Expected polygonal footprint, found {kind}")


def extrude(footprint, height):
    """Use constrained triangulation to preserve concavity and courtyards."""
    points, loops = [], []
    for index, ring in enumerate(footprint):
        outline = oriented_ring(ring, counterclockwise=(index == 0))
        if len(set(outline)) < 3:
            raise ValueError("Footprint ring has fewer than three distinct points")
        loops.append(list(range(len(points), len(points) + len(outline))))
        points.extend(Vector(point) for point in outline)
    outer_edges = [(a, b) for loop in loops for a, b in zip(loop, loop[1:] + loop[:1])]
    vertices, edges, faces, _, edge_origins, _ = delaunay_2d_cdt(points, outer_edges, loops, 2, 0.0001, True)
    if not faces:
        raise ValueError("Could not triangulate a footprint")
    # Inner constraints produce their own faces. Drop roof triangles whose centroids fall inside a hole.
    def in_loop(point, loop):
        x, y = point
        inside = False
        for ia, ib in zip(loop, loop[1:] + loop[:1]):
            ax, ay = points[ia]
            bx, by = points[ib]
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                inside = not inside
        return inside
    roof = []
    for face in faces:
        center = sum((vertices[i] for i in face), Vector((0, 0))) / len(face)
        if in_loop(center, loops[0]) and not any(in_loop(center, hole) for hole in loops[1:]):
            roof.append(face)
    if not roof:
        raise ValueError("Triangulated roof is empty")
    n = len(vertices)
    coordinates = [(v.x, v.y, z) for z in (0, height) for v in vertices]
    surfaces = [tuple(reversed(face)) for face in roof] + [tuple(i + n for i in face) for face in roof]
    # Derive side walls from correctly oriented roof boundary edges, including interior holes.
    counts = {}
    for face in roof:
        for a, b in zip(face, face[1:] + face[:1]):
            key = tuple(sorted((a, b)))
            counts[key] = None if key in counts else (a, b)
    surfaces.extend((a, b, b + n, a + n) for edge in counts.values() if edge is not None for a, b in [edge])
    return coordinates, surfaces


def create_massing(collection, footprints, origin, ground_z=0, floor_height_m=3.2, fallback_m=7,
                   overrides=None):
    mat = massing_material()
    objects, seen = [], set()
    for feature in footprints["features"]:
        props = feature["properties"]
        building_id = props.get("building_id")
        if not building_id or building_id in seen:
            raise ValueError(f"Missing or duplicate building ID: {building_id}")
        seen.add(building_id)
        polygons = [[list(map(lambda c: project(c, origin), ring)) for ring in part]
                    for part in geometry_parts(feature["geometry"])]
        anchor = polygons[0][0][0]
        height, method = height_for(props, floor_height_m, fallback_m)
        vertices, faces = [], []
        for part in polygons:
            flat = [[(x - anchor[0], y - anchor[1]) for x, y in ring] for ring in part]
            points, sides = extrude(flat, height)
            faces.extend(tuple(len(vertices) + i for i in side) for side in sides)
            vertices.extend(points)
        mesh = bpy.data.meshes.new(str(building_id))
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        mesh.materials.append(mat)
        obj = link(collection, str(building_id), mesh, (*anchor, ground_z))
        obj["building_id"] = str(building_id)
        obj["footprint_source"] = props.get("source", "unspecified")
        obj["height_m"] = height
        obj["height_method"] = method
        obj["visibility_override"] = (overrides or {}).get(building_id, "auto")
        if props.get("height_unverified_m"):
            obj["height_unverified_m"] = props["height_unverified_m"]
        objects.append(obj)
    if not objects:
        raise ValueError("No building footprints")
    return objects
