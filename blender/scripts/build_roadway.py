"""Build an editable, dimension-aware roadway shot in a new Blender scene."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from bpy_extras.anim_utils import action_get_channelbag_for_slot
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roadway_model import load_model, positive
from story_config import FORMATS, project
from urban_camera import bake_visibility, key_camera, sample_subject

COLORS = {
    "travel": (0.072, 0.085, 0.103), "turn": (0.102, 0.111, 0.117),
    "bike": (0.046, 0.265, 0.193), "buffer": (0.166, 0.203, 0.178),
    "parking": (0.11, 0.13, 0.16), "sidewalk": (0.57, 0.56, 0.51),
    "curb": (0.82, 0.79, 0.71), "median": (0.29, 0.35, 0.21),
    "refuge": (0.57, 0.56, 0.51), "furnishing": (0.28, 0.32, 0.23),
    "ground": (0.12, 0.15, 0.16), "white": (0.90, 0.92, 0.88),
    "yellow": (0.98, 0.65, 0.16), "ink": (0.012, 0.024, 0.033),
    "accent": (0.34, 0.88, 0.65), "car": (0.81, 0.26, 0.083),
    "glass": (0.035, 0.067, 0.087),
}


def material(name, color, flat=False):
    mat = bpy.data.materials.new(f"Roadway | {name}")
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    if flat:
        nodes = mat.node_tree.nodes
        emit = nodes.new("ShaderNodeEmission")
        emit.inputs[0].default_value = (*color, 1)
        mat.node_tree.links.new(emit.outputs[0], nodes.get("Material Output").inputs[0])
    else:
        surface = mat.node_tree.nodes.get("Principled BSDF")
        surface.inputs["Base Color"].default_value = (*color, 1)
        surface.inputs["Roughness"].default_value = 0.81
    return mat


def mesh(collection, name, vertices, faces, mat, parent=None):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    data.materials.append(mat)
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.parent = parent
    return obj


def box(col, name, xyz, dimensions, mat, parent=None):
    x, y, z = [d / 2 for d in dimensions]
    vertices = [(-x,-y,-z),(x,-y,-z),(x,y,-z),(-x,y,-z),
                (-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)]
    faces = [(3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    item = mesh(col, name, vertices, faces, mat, parent)
    item.location = xyz
    return item


def collection(scene, name):
    col = bpy.data.collections.new(name)
    scene.collection.children.link(col)
    return col


def empty(col, name, parent=None):
    obj = bpy.data.objects.new(name, None)
    col.objects.link(obj)
    obj.parent = parent
    return obj


def driver(obj, path, index, control, variables, expression):
    curve = obj.driver_add(path, index)
    curve.driver.expression = expression
    for var_name, prop in variables.items():
        variable = curve.driver.variables.new()
        variable.name = var_name
        variable.type = "SINGLE_PROP"
        variable.targets[0].id = control
        variable.targets[0].data_path = f'["{prop}"]'


def section_geometry(col, root, slots, length, mats):
    control = empty(col, "Section controls | dimensions in meters", root)
    control["progress"] = 0.0
    control.id_properties_ui("progress").update(min=0.0, max=1.0)
    control["Edit widths"] = "Edit unlocked shared edges. Keep edges in order. JSON validates all dimension totals."
    anchors = []
    for index, (old, new, x0, x1, w0, w1) in enumerate(slots):
        for phase, item, x, width in (("existing", old, x0, w0), ("proposed", new, x1, w1)):
            key = f"{phase} edge {index:02d}"
            control[key] = round(x, 10)
            control[f"{phase} edge {index + 1:02d}"] = round(x + width, 10)
            if item:
                control.id_properties_ui(key).update(description=f"Left edge of {item.id}. {item.source}")
        sides = {"a": f"existing edge {index:02d}", "b": f"proposed edge {index:02d}",
                 "c": f"existing edge {index + 1:02d}", "d": f"proposed edge {index + 1:02d}",
                 "p": "progress"}
        item = new or old
        strip = box(col, f"Lane | {item.id}", (0,0,-.075), (1,length,.15), mats[item.kind], root)
        for phase, endpoint in (("existing", old), ("proposed", new)):
            if endpoint:
                for field in ("id", "kind", "direction", "width", "zone", "source", "locked", "derived"):
                    value = getattr(endpoint, field)
                    if value is not None:
                        strip[f"{phase} {field}"] = value
        strip["mapping"] = ("appears" if old is None else "disappears" if new is None else
                            "persists" if old == new else "transforms")
        driver(strip, "location", 0, control, sides, "((a+c)*(1-p)+(b+d)*p)/2")
        driver(strip, "scale", 0, control, sides, "max(0,(c-a)*(1-p)+(d-b)*p)")
        edge = empty(col, f"Shared boundary | {item.id}", root)
        driver(edge, "location", 0, control, {"a": sides["a"], "b": sides["b"], "p": "progress"}, "a*(1-p)+b*p")
        anchors.append((strip, edge))
    return control, anchors


def visible(item, first, last, end):
    for frame, hidden in [(1, first > 1), (max(1,first), False), (last, False), (min(last+1,end+1), True)]:
        item.hide_render = hidden
        item.keyframe_insert(data_path="hide_render", frame=frame)
        item.hide_viewport = hidden
        item.keyframe_insert(data_path="hide_viewport", frame=frame)


def arrow(col, name, x, y, direction, mat, parent, turn=False):
    shape = [(-.09,-.85),(.09,-.85),(.09,.29),(.34,.29),(0,.98),(-.34,.29),(-.09,.29)]
    if turn:
        shape = [(-.09,-.85),(.09,-.85),(.09,.30),(-.31,.30),(-.31,.07),
                 (-.78,.40),(-.31,.76),(-.31,.52),(-.09,.52)]
    sign = -1 if direction == "reverse" else 1
    vertices = [(x + sign*a, y + sign*b, .115) for a,b in shape]
    return mesh(col, name, vertices, [tuple(range(len(shape)))], mat, parent)


def markings(col, anchors, slots, mats, length, morph_start, morph_end, end):
    for column, phase, first, last in ((0,"existing",1,morph_start-1),
                                        (1,"proposed",morph_start,end)):
        pairs = [(slot[column], strip, edge) for slot,(strip,edge) in zip(slots, anchors)
                 if slot[column] is not None]
        previous = None
        for element, strip, edge in pairs:
            before, previous = previous, element
            if not element or element.kind not in {"travel", "turn", "bike", "buffer"}:
                if not before or before.kind != "bike":
                    continue
            if element.kind != "buffer":
                for distance in (-length*.27, 0, length*.27) if element.direction else ():
                    item = arrow(col, f"{phase} arrow | {element.id}", 0, distance,
                                 element.direction, mats["yellow" if element.kind == "turn" else "white"],
                                 strip, turn=element.kind == "turn")
                    if element.kind == "turn":
                        alternate = arrow(col, f"{phase} opposing turn | {element.id}", .06,
                                          distance+2.15, "reverse", mats["yellow"], strip, turn=True)
                        visible(alternate, max(first, morph_end-14), last, end)
                    visible(item, max(first, morph_end-14) if element.kind == "turn" else first, last, end)
            if before and (element.kind == "turn" or before.kind == "turn" or
                           before.kind == element.kind == "travel" and element.direction != before.direction):
                item = box(col, f"{phase} center line",(-.11,0,.027),(.105,length,.014),mats["yellow"],edge)
                visible(item,first,last,end)
                spacings = range(-int(length//2)+3, int(length//2)-2, 6)
                for position in spacings:
                    item = box(col, f"{phase} center second line",(.11,position,.027),
                               (.105,2.8 if phase=="proposed" else 6,.014),mats["yellow"],edge)
                    visible(item, first,last,end)
            elif before and before.kind == element.kind == "travel":
                for position in range(-int(length//2)+3,int(length//2)-2,6):
                    item = box(col, "White lane dash",(0,position,.027),(.10,2.3,.014),mats["white"],edge)
                    visible(item,first,last,end)
            elif before and ({before.kind,element.kind} & {"bike","buffer"}):
                item = box(col,"Bike facility edge",(0,0,.027),(.095,length,.014),mats["white"],edge)
                visible(item,max(first,morph_end-15),last,end)
            if element.kind == "buffer":
                for position in range(-int(length//2)+2,int(length//2)-1,2):
                    item = box(col, "Buffer hatch", (0,position,.103), (.76,.18,.012), mats["white"], strip)
                    item.rotation_euler.z = .36
                    visible(item, morph_end-9,last,end)


def path_vehicle(col, root, strip, element, model, mats, length, start, stop, end):
    required = {"bike": .67, "car": 1.72, "bus": 2.47}[model]
    if element.width < required + .15:
        raise ValueError(f"{model} too wide for {element.id}")
    route = bpy.data.curves.new(f"{model} route | {element.id}", "CURVE")
    route.dimensions = "3D"
    route.use_path = True
    spline = route.splines.new("POLY")
    spline.points.add(1)
    sign = -1 if element.direction == "reverse" else 1
    spline.points[0].co = (0,-sign*(length/2-4),0,1)
    spline.points[1].co = (0, sign*(length/2-4),0,1)
    path = bpy.data.objects.new(route.name, route)
    col.objects.link(path)
    path.parent = root
    driver(path, "location", 0, strip, {}, "0")
    curve = path.animation_data.drivers.find("location", index=0)
    variable = curve.driver.variables.new()
    variable.name, variable.type = "lane", "TRANSFORMS"
    variable.targets[0].id = strip
    variable.targets[0].transform_type = "LOC_X"
    variable.targets[0].transform_space = "LOCAL_SPACE"
    curve.driver.expression = "lane"
    vehicle = empty(col, f"{model.title()} | {element.id}")
    follow = vehicle.constraints.new("FOLLOW_PATH")
    follow.target = path
    follow.use_fixed_location = True
    follow.use_curve_follow = True
    follow.forward_axis = "FORWARD_Y"
    follow.up_axis = "UP_Z"
    for frame, value in [(start,0.0),(stop,1.0)]:
        follow.offset_factor = value
        follow.keyframe_insert(data_path="offset_factor",frame=frame)
    bag = action_get_channelbag_for_slot(vehicle.animation_data.action, vehicle.animation_data.action_slot)
    for fcurve in bag.fcurves:
        for key in fcurve.keyframe_points:
            key.interpolation = "LINEAR"
    parts = []
    if model == "bike":
        for y in (-.53,.53):
            wheel = box(col, "Bicycle tire", (0,y,.29), (.075,.56,.56),mats["glass"],vehicle)
            bevel = wheel.modifiers.new("Round wheel silhouette", "BEVEL")
            bevel.width, bevel.segments = .25, 3
            parts.append(wheel)
        parts += [box(col, "Bike frame",(0,0,.46),(.09,1.0,.13),mats["yellow"],vehicle),
                  box(col,"Rider",(0,-.08,.95),(.41,.42,.66),mats["car"],vehicle),
                  box(col,"Helmet",(0,.05,1.39),(.26,.27,.22),mats["white"],vehicle),
                  box(col,"Handlebar",(0,.52,.82),(.63,.08,.06),mats["glass"],vehicle)]
    else:
        bus = model == "bus"
        w, l, h = (2.45,9.3,2.85) if bus else (1.70,4.05,.78)
        parts += [box(col,"Vehicle body",(0,0,h/2+.27),(w,l,h),mats["car"],vehicle),
                  box(col,"Vehicle glazing",(0,0,h*.69+.41),(w*.89,l*(.91 if bus else .54),h*.43),mats["glass"],vehicle)]
        for side in (-1,1):
            for axle in (-1,1):
                parts.append(box(col,"Wheel",(side*w*.45,axle*l*.31,.27),(.22,.54,.52),mats["ink"],vehicle))
        for part in parts:
            bevel = part.modifiers.new("Lightly rounded silhouette", "BEVEL")
            bevel.width, bevel.segments = .14, 2
    for part in parts:
        visible(part,start,stop,end)


def text(col, camera, value, x, y, size, mat):
    data = bpy.data.curves.new(value, "FONT")
    data.body, data.size = value, size
    data.materials.append(mat)
    obj = bpy.data.objects.new(value, data)
    col.objects.link(obj)
    obj.parent = camera
    obj.location = (x,y,-5)
    return obj


def framing_overlay(scene, camera, cfg, col, mats, scale, morph_start, morph_end, close):
    portrait = scene.render.resolution_x < scene.render.resolution_y
    w, h = (scale*9/16,scale) if portrait else (scale,scale*9/16)
    base = min(w,h)
    x, y = -w*.455, h*.405
    box(col,"Header backing",(0,h*.397,-5.08),(w*.94,h*.146,.02),mats["ink"],camera)
    text(col,camera,cfg.get("kicker","MAPLE AVENUE SAFETY PROJECT"),x,y+base*.024,base*.025,mats["accent"])
    text(col,camera,cfg["title"],x,y-base*.042,base*.070,mats["white"])
    box(col,"Caption backing",(0,-h*.400,-5.08),(w*.94,h*.155,.02),mats["ink"],camera)
    variants = [
        (cfg.get("existing_label","Existing: four travel lanes"),1,morph_start-1),
        (cfg.get("morph_label","Reallocating the same road space"),morph_start,morph_end-1),
        (cfg.get("proposed_label","Two through lanes + a center turn lane"),morph_end,close-1),
        (cfg.get("closing_label","The proposal also adds bike lanes"),close,scene.frame_end),
    ]
    for label, first, last in variants:
        item = text(col,camera,label,x,-h*.397,base*(.037 if portrait else .046),mats["white"])
        visible(item,first,last,scene.frame_end)
    text(col,camera,cfg["disclosure"],x,-h*.440,base*.027,mats["accent"])


def ground_point(root, x, y, z=0):
    return root.matrix_world @ Vector((x,y,z))


def import_buildings(scene, source, root, length, camera, row, config):
    mass = collection(scene, "Day 4 | Geographic building massing with visibility overrides")
    buildings = []
    for original, matrix in source:
        points = [root.matrix_world.inverted() @ (matrix @ Vector(corner)) for corner in original.bound_box]
        if min(p.x for p in points) > 45 or max(p.x for p in points) < -45:
            continue
        if min(p.y for p in points) > length or max(p.y for p in points) < -length:
            continue
        clone = original.copy()
        clone.name = f"Roadway | {original.name}"
        clone.animation_data_clear()
        clone.parent = None
        clone.matrix_world = matrix
        clone.color[3] = 1
        if original.get("source_id") in config.get("visibility_overrides",{}):
            clone["visibility_override"] = config["visibility_overrides"][original["source_id"]]
        mass.objects.link(clone)
        buildings.append(clone)
    bpy.context.view_layer.update()
    targets = sample_subject([[ground_point(root,0,-length/2,.07), ground_point(root,0,length/2,.07)]],
                             spacing=2.5,half_width=row/2)
    if buildings:
        hits = bake_visibility(scene,camera,buildings,targets,1,scene.frame_end,
                               mode=config.get("visibility","hide"))
        scene["automatic blockers"] = sum(bool(frames) for frames in hits.values())
    scene["context building count"] = len(buildings)


def build(config, format_name):
    primary = bpy.context.scene
    source_mass = primary.collection.children.get("Day 3 | editable geographic stage")
    source_mass = source_mass.children.get("Generated building volumes") if source_mass else None
    building_poses = []
    if source_mass and config.get("geography"):
        original_frame = primary.frame_current
        primary.frame_set(primary.frame_end)
        building_poses = [(obj,obj.matrix_world.copy()) for obj in source_mass.objects]
        primary.frame_set(original_frame)
    slots, roads, rows = load_model(config)
    length = positive(config["length_m"],"Roadway length")
    timing = config["timing"]
    intervals = [timing[key] for key in ("hold_frames","morph_frames","reveal_frames","closing_frames")]
    if any(type(n) is not int or n < 20 for n in intervals):
        raise ValueError("Shot intervals must each be at least 20 frames")
    morph_start, morph_end, close, end = [1 + sum(intervals[:i]) for i in range(1,5)]
    scene = bpy.data.scenes.new("Roadway redesign")
    bpy.context.window.scene = scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = FORMATS[format_name]
    scene.render.resolution_percentage = 100
    scene.render.fps, scene.frame_end = 30, end-1
    scene.unit_settings.system = "METRIC"
    scene.view_settings.view_transform = "Standard"
    scene.world = bpy.data.worlds.new("Roadway sky")
    scene.world.color = (.26,.26,.26)
    mats = {k:material(k,v,k in {"ink","accent","white","yellow","ground"}) for k,v in COLORS.items()}
    col = collection(scene,"Editable roadway and controls")
    root = empty(col,"Roadway origin and bearing")
    geographic = config.get("geography")
    if geographic:
        a,b = [Vector((*project(p,geographic["origin"]),0)) for p in geographic["centerline"]]
        root.location = (a+b)/2
        root.rotation_euler.z = math.atan2(-(b-a).x,(b-a).y)
        scene["geographic reference"] = geographic["label"]
    bpy.context.view_layer.update()
    box(col,"Ground",(0,0,-.22),(300,300,.25),mats["ground"],root)
    control, anchors = section_geometry(col,root,slots,length,mats)
    control["existing curb-to-curb m"], control["proposed curb-to-curb m"] = roads
    control["existing right-of-way m"], control["proposed right-of-way m"] = rows
    for frame, progress in ((1,0),(morph_start,0),(morph_end,1),(scene.frame_end,1)):
        control["progress"] = float(progress)
        control.keyframe_insert(data_path='["progress"]',frame=frame)
    bag = action_get_channelbag_for_slot(control.animation_data.action,control.animation_data.action_slot)
    easing = timing.get("easing","smooth")
    if easing not in {"smooth","linear"}:
        raise ValueError("Use smooth or linear easing")
    for key in bag.fcurves.find('["progress"]').keyframe_points:
        key.interpolation = "LINEAR" if easing == "linear" else "BEZIER"
        key.handle_left_type = key.handle_right_type = "AUTO_CLAMPED"
    markings(collection(scene,"Editable lane markings"),anchors,slots,mats,length,morph_start,morph_end,scene.frame_end)
    vcol = collection(scene,"Low-poly vehicles and editable paths")
    for (strip,_),(old,new,*_) in zip(anchors,slots):
        for phase, element, start, stop in (("existing",old,1,morph_start-5),
                                             ("proposed",new,morph_end+2,close-1)):
            selected = config.get("vehicles",{}).get(phase,{})
            if element and element.id in selected:
                model = selected.get(element.id) if isinstance(selected,dict) else ("bike" if element.kind=="bike" else "car")
                path_vehicle(vcol,root,strip,element,model,mats,length,start,stop,scene.frame_end)
    light = bpy.data.lights.new("Soft directional key","SUN")
    light.energy, light.angle = 2.25, math.radians(12)
    lamp = bpy.data.objects.new(light.name,light)
    col.objects.link(lamp)
    lamp.rotation_euler = (.44,-.45,-.5)
    camera_data = bpy.data.cameras.new("Roadway orthographic camera")
    camera_data.type, camera_data.clip_end = "ORTHO", 600
    camera = bpy.data.objects.new(camera_data.name,camera_data)
    col.objects.link(camera)
    scene.camera = camera
    cfg = config["camera"][format_name]
    bearing = cfg["bearing"] - math.degrees(root.rotation_euler.z)
    scale, tilt = cfg["scale"], cfg["tilt"]
    target = ground_point(root,*cfg.get("target",[0,0,0]))
    key_camera(camera,1,target,scale,bearing-6,tilt-4,115)
    key_camera(camera,morph_start,target,scale,bearing,tilt,115)
    key_camera(camera,scene.frame_end,target,scale,bearing+4,tilt,115)
    framing_overlay(scene,camera,config,collection(scene,"Editable roadway titles"),mats,scale,morph_start,morph_end,close)
    for name, frame in (("Existing street",1),("Reallocate roadway",morph_start),
                        ("Proposed street",morph_end),("Closing caption",close)):
        scene.timeline_markers.new(name,frame=frame)
    if building_poses:
        import_buildings(scene,building_poses,root,length,camera,max(roads),config)
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
    build(json.loads(args.config.read_text(encoding="utf-8")),args.format)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))


if __name__ == "__main__":
    main()

