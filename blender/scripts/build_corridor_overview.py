"""Add a Blender planning-map shot using a source-backed corridor and named locations."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_roadway import box, collection, material, mesh, text, visible
from roadway_model import validate_segments
from story_config import FORMATS, frame_target, project
from urban_camera import key_camera


def stroke(col, name, points, width, mat, height):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.bevel_depth = width / 2
    data.bevel_resolution = 2
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for vertex, (x, y) in zip(spline.points, points):
        vertex.co = (x, y, height, 1)
    data.materials.append(mat)
    obj = bpy.data.objects.new(name, data)
    col.objects.link(obj)
    return obj


def xy_paths(path, origin):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    for feature in data["features"]:
        geo = feature["geometry"]
        parts = [geo["coordinates"]] if geo["type"] == "LineString" else geo["coordinates"]
        for points in parts:
            yield [project(point, origin) for point in points]


def street_context(col, paths, mat):
    vertices, faces = [], []
    for path in paths:
        for (ax, ay), (bx, by) in zip(path, path[1:]):
            dx, dy = bx-ax, by-ay
            length = math.hypot(dx,dy)
            if length <= .01:
                continue
            nx, ny = -dy / length * 2.5, dx / length * 2.5
            start = len(vertices)
            vertices.extend(((ax+nx,ay+ny,0),(ax-nx,ay-ny,0),(bx-nx,by-ny,0),(bx+nx,by+ny,0)))
            faces.append(tuple(range(start,start+4)))
    if faces:
        mesh(col,"Context streets | flat centerline strokes",vertices,faces,mat)


def build(config, source, orientation):
    segments = config["segments"]
    validate_segments(segments, set(config["configurations"]))
    origin = config["origin"]
    paths = list(xy_paths(source / config["corridor"], origin))
    bounds = [point for path in paths for point in path]
    center, scale = frame_target(bounds, FORMATS[orientation], 1.31)
    scene = bpy.data.scenes.new("Corridor planning overview")
    bpy.context.window.scene = scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = FORMATS[orientation]
    scene.render.fps = 30
    scene.frame_end = 198
    scene.view_settings.view_transform = "Standard"
    col = collection(scene, "Source-backed map and editable editorial labels")
    dark = material("Overview navy", (.009,.023,.037), True)
    street = material("Street context", (.025,.061,.083), True)
    green = material("Bike lane concept", (.17,.74,.48), True)
    orange = material("Planning callout", (.98,.57,.15), True)
    white = material("Overview text", (.88,.93,.92), True)
    box(col,"Map ground",(*center,-8),(24000,24000,1),dark)
    if config.get("context"):
        street_context(col,xy_paths(source / config["context"],origin),street)
    for path in paths:
        stroke(col,"City GIS Maple Avenue centerline",path,31,green,23)
    camera_data = bpy.data.cameras.new("Corridor overhead")
    camera_data.type, camera_data.clip_end = "ORTHO", 15000
    camera = bpy.data.objects.new(camera_data.name,camera_data)
    col.objects.link(camera)
    scene.camera = camera
    w,h = (scale*9/16,scale) if orientation=="portrait" else (scale,scale*9/16)
    for frame, target, bearing in ((1,center,0),(61,center,0),(132,center,5),
                                  (198,project(config["transition_anchor"],origin),13)):
        key_camera(camera,frame,(*target,0),scale,bearing,0,7000)
    box(col,"Header",(0,h*.413,-5.1),(w*.94,h*.13,.02),dark,camera)
    box(col,"Footer",(0,-h*.398,-5.1),(w*.94,h*.16,.02),dark,camera)
    base = min(w,h)
    x = -w*.45
    text(col,camera,"MAPLE AVENUE SAFETY PROJECT",x,h*.436,base*.024,green)
    text(col,camera,"Bike lanes along Maple",x,h*.377,base*.060,white)
    text(col,camera,"City of Dallas 2024 planning exhibit",x,-h*.457,base*.027,green)
    for feature in config["callouts"]:
        first, last = feature["frames"]
        if feature.get("anchor"):
            px,py = project(feature["anchor"], origin)
            radius = scale * .011
            coords = [(px+radius*math.cos(i*math.tau/24),py+radius*math.sin(i*math.tau/24))
                      for i in range(25)]
            ring = stroke(col,feature["label"], coords, max(7,scale*.0035), orange, 55)
            visible(ring,first,last,scene.frame_end)
        label = text(col,camera,feature["label"],x,-h*.387,base*.040,white)
        visible(label,first,last,scene.frame_end)
        scene.timeline_markers.new(feature["label"],frame=first)
    scene.frame_set(1)
    return scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--format",choices=FORMATS,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    if args.output.exists():
        raise FileExistsError(f"Use a new output path: {args.output}")
    build(json.loads(args.config.read_text(encoding="utf-8-sig")),args.config.parent,args.format)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))


if __name__ == "__main__":
    main()
