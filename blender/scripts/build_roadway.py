"""Build an editable, dimension-aware roadway shot in a new Blender scene."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from bpy_extras.anim_utils import action_get_channelbag_for_slot
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roadway_model import load_model, positive
from traffic_paths import driveway_center, driveway_layout
from roadway_traffic import animate_traffic, motor_mesh
from protected_simulation import install_users
from traffic_paths import SIZES
from roadway_crossing import style_config, turn_outline, without, install_crossing
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
        strip = box(col, f"Lane | {item.id}", (0,0,0), (1,length,.15), mats[item.kind], root)
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


def paint_phase(material_base, root, direction, length, first, last, incoming):
    """Keep the paint geometry fixed and reveal it with a moving longitudinal mask."""
    mat = material_base.copy()
    mat.name = f"{material_base.name} | {'apply' if incoming else 'remove'} {direction}"
    mat.surface_render_method = "BLENDED"
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    output = nodes.get("Material Output")
    original = output.inputs["Surface"].links[0].from_socket
    coordinates = nodes.new("ShaderNodeTexCoord")
    coordinates.object = root
    axes = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coordinates.outputs["Object"], axes.inputs[0])
    mask = nodes.new("ShaderNodeMath")
    visible_below = (direction == "forward") == incoming
    mask.operation = "LESS_THAN" if visible_below else "GREATER_THAN"
    links.new(axes.outputs["Y"], mask.inputs[0])
    extent = length / 2 + .01
    sign = 1 if direction == "forward" else -1
    front = mask.inputs[1]
    for frame, value in ((first, -sign * extent), (last, sign * extent)):
        front.default_value = value
        front.keyframe_insert(data_path="default_value", frame=frame)
    anim = mat.node_tree.animation_data
    for curve in action_get_channelbag_for_slot(anim.action, anim.action_slot).fcurves:
        for key in curve.keyframe_points:
            key.interpolation = "LINEAR"
    mix = nodes.new("ShaderNodeMixShader")
    links.new(mask.outputs[0], mix.inputs[0])
    links.new(nodes.new("ShaderNodeBsdfTransparent").outputs[0], mix.inputs[1])
    links.new(original, mix.inputs[2])
    links.new(mix.outputs[0], output.inputs["Surface"])
    return mat


def arrow_paint(base, start, stop, incoming):
    mat = base.copy()
    mat.name = "Roadway | White arrows " + ("proposed" if incoming else "existing")
    mat.surface_render_method = "BLENDED"
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    output = nodes.get("Material Output")
    original = output.inputs["Surface"].links[0].from_socket
    mix = nodes.new("ShaderNodeMixShader")
    links.new(nodes.new("ShaderNodeBsdfTransparent").outputs[0], mix.inputs[1])
    links.new(original, mix.inputs[2])
    links.new(mix.outputs[0], output.inputs["Surface"])
    amount=style_config()["arrow_opacity"]
    for frame, opacity in ((start, 0 if incoming else amount), (stop, amount if incoming else 0)):
        mix.inputs[0].default_value = opacity
        mix.inputs[0].keyframe_insert(data_path="default_value", frame=frame)
    return mat


def follow_lane_center(obj, strip):
    curve = obj.driver_add("location", 0)
    variable = curve.driver.variables.new()
    variable.name, variable.type = "lane", "TRANSFORMS"
    variable.targets[0].id = strip
    variable.targets[0].transform_type = "LOC_X"
    variable.targets[0].transform_space = "LOCAL_SPACE"
    curve.driver.expression = "lane"


def arrow(col, name, y, direction, mat, root, strip, turn=False, bike=False):
    height = .78 if bike else 1
    sign = -1 if direction == "reverse" else 1
    if turn:
        shape = turn_outline(style_config())
    else:
        width = .65 if bike else 1
        shape = [(width*x,y) for x,y in
                 ((-.12,-.85),(.12,-.85),(.12,.23),(.39,.23),(0,.95),(-.39,.23),(-.12,.23))]
    vertices = [(sign*x,y+sign*v*height,.025) for x,v in shape]
    result = mesh(col,name,vertices,[tuple(range(len(vertices)))],mat,root)
    follow_lane_center(result,strip)
    return result


def split_at_driveways(start, end, cuts, dashed):
    result = []
    for a,b in cuts:
        if start<a:
            result.append((start,a))
        if dashed:
            result.extend((a+.18+1.47*i, min(a+.98+1.47*i,b))
                          for i in range(math.ceil((b-a)/1.47)) if a+.18+1.47*i<b)
        start=b
    if start<end:
        result.append((start,end))
    return result


def markings(col, anchors, slots, mats, root, length, design_length, cuts, phases,
             crossing=False, turn_pairs=None, driveway_arrows=None):
    arrow_start, arrow_out, old_end, lanes_end, paint_end, arrows_end = phases
    for column, phase, start, stop in ((0,"Existing",arrow_out,old_end),
                                       (1,"Proposed",lanes_end,paint_end)):
        incoming = bool(column)
        fade = (paint_end,arrows_end) if incoming else (arrow_start,arrow_out)
        arrows = arrow_paint(mats["white"],*fade,incoming)
        inks = {}
        def ink(key, direction):
            if (key,direction) not in inks:
                inks[key,direction] = paint_phase(mats[key],root,direction,length,start,stop,incoming)
            return inks[key,direction]

        def line(name, edge, spans, color, direction, x=0, width=.105):
            if incoming and crossing:
                cut=6.68 if color=="yellow" else 3.04
                spans=without(spans,crossing["center_m"]-cut,crossing["center_m"]+cut)
            for a,b in spans:
                box(col,name,(x,(a+b)/2,.015),(width,b-a,.008),ink(color,direction),edge)

        half = length/2
        full = [(-half,half)]
        dashes = [(y,min(y+2.45,half)) for y in range(math.ceil(-half),math.floor(half),6)]
        pairs = [(slot[column], strip, edge, slot[2+column])
                 for slot,(strip,edge) in zip(slots, anchors) if slot[column]]
        for i,(element,strip,edge,boundary_x) in enumerate(pairs):
            side_cuts = cuts["left" if boundary_x < 0 else "right"]
            if element.kind in {"travel","bike","turn"} and element.direction:
                if element.kind=="turn":
                    style=style_config()
                    gap=style["opposing_tail_gap_ft"]*.3048
                    center=(design_length*.228 if crossing else 0.)
                    poses = [(center-gap/2,"reverse"),(center+gap/2,"forward")]
                    if driveway_arrows:
                        # For a left turn from +Y travel the arrow points to local -X.
                        # Its head reaches the driveway station and its tail stays upstream.
                        arrow_length = style["turn_arrow_length_ft"] * .3048
                        for (side, end), station in driveway_arrows.items():
                            sign = 1 if side == "left" else -1
                            direction = "forward" if sign == 1 else "reverse"
                            marking = arrow(col, f"{phase} arrow | {element.id} | {side} {end}",
                                            station-sign*arrow_length,direction,arrows,root,strip,turn=True)
                            marking["driveway side"] = side
                            marking["driveway end"] = end
                        poses = []
                    elif turn_pairs is not None:
                        poses = []
                        arrow_length = style["turn_arrow_length_ft"] * .3048
                        for pair in turn_pairs:
                            middle = pair["center_m"]
                            if pair.get("heads_face"):
                                reach = gap / 2 + arrow_length
                                poses.extend(((middle-reach, "forward"), (middle+reach, "reverse")))
                            else:
                                poses.extend(((middle-gap/2, "reverse"), (middle+gap/2, "forward")))
                else:
                    poses=[(y,element.direction) for y in (-design_length*.24,design_length*.24)]
                for y,direct in poses:
                    arrow(col,f"{phase} arrow | {element.id}",y,direct,arrows,root,strip,
                          turn=element.kind=="turn",bike=element.kind=="bike")
            if element.kind in {"bike","buffer"}:
                adjacent = element.direction
                if adjacent not in ("forward","reverse"):
                    adjacent = "reverse" if i<len(pairs)/2 else "forward"
                box(col,f"{phase} surface color | {element.id}",(0,0,.003),
                    (1,length,.003),ink(element.kind,adjacent),strip)
                if element.kind=="buffer":
                    for y in range(math.ceil(-half),math.floor(half),2):
                        if any(a-.25<y<b+.25 for a,b in side_cuts) or (crossing and abs(y-crossing["center_m"])<3.3):
                            continue
                        hatch=box(col,"Buffer hatch",(0,y,.015),(.82,.12,.008),ink("white",adjacent),strip)
                        hatch.rotation_euler.z=.36
            if not i:
                continue
            previous=pairs[i-1][0]
            direction = next((value for value in (element.direction,previous.direction) if value in ("forward","reverse")),
                             "reverse" if i<len(pairs)/2 else "forward")
            if previous.kind=="turn" or element.kind=="turn":
                inside = 1 if element.kind=="turn" else -1
                line(f"{phase} solid yellow outside center lane",edge,full,"yellow",direction,-inside*.11)
                line(f"{phase} dashed yellow inside center lane",edge,dashes,"yellow",direction,inside*.11)
            elif previous.kind==element.kind=="travel":
                if element.direction==previous.direction:
                    line(f"{phase} white lane dash",edge,dashes,"white",direction)
                else:
                    line("Existing double yellow | reverse",edge,full,"yellow",previous.direction,-.11)
                    line("Existing double yellow | forward",edge,full,"yellow",element.direction,.11)
            elif {previous.kind,element.kind}&{"bike","buffer"}:
                line(f"{phase} bike facility edge",edge,split_at_driveways(-half,half,side_cuts,True),"white",direction)


def path_vehicle(col, root, strip, element, model, mats, length, start, stop, end):
    model = {"car":"sedan","bus":"transit bus"}.get(model,model)
    required = .67 if model=="bike" else SIZES[model][0]
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
        body=bpy.data.objects.new(model,motor_mesh(model,mats))
        col.objects.link(body)
        body.parent=vehicle
        bevel=body.modifiers.new("Small edge bevel","BEVEL")
        bevel.width,bevel.segments=.045,1
        parts.append(body)
    for part in parts:
        visible(part,start,stop,end)


def text(col, camera, value, x, y, size, mat):
    data = bpy.data.curves.new(value, "FONT")
    data.body, data.size = value, size
    data.materials.append(mat)
    obj = bpy.data.objects.new(value, data)
    col.objects.link(obj)
    obj.parent = camera
    obj.location = (x, y, -5)
    return obj


def roadway_length(scene, root, design_length, width, thickness):
    """Find the minimum slab length that hides both ends at every camera pose."""
    needed = design_length / 2
    corners = [(x,z) for x in (-width/2,width/2) for z in (-thickness,0)]
    for frame in range(scene.frame_start,scene.frame_end+1):
        scene.frame_set(frame)
        project_view = lambda p: world_to_camera_view(scene,scene.camera,root.matrix_world @ Vector(p))
        origin = project_view((0,0,0))
        delta = project_view((0,1,0))-origin
        bases = [project_view((x,0,z)) for x,z in corners]
        for side in (-1,1):
            limits = []
            for axis in (0,1):
                slope=delta[axis]*side
                if abs(slope)>1e-6:
                    boundary=1.01 if slope>0 else -.01
                    limits.append(max((boundary-p[axis])/slope for p in bases))
            needed=max(needed,min(limits))
    return 2*math.ceil(needed+1)


def build_strip_mesh(strip, spans, thickness, ink):
    vertices, faces = [], []
    for a,b in spans:
        base=len(vertices)
        vertices.extend((x,y,z) for z in (-thickness,0) for x,y in
                        ((-.5,a),(.5,a),(.5,b),(-.5,b)))
        faces.extend(tuple(base+i for i in face) for face in
                     ((3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)))
    old=strip.data
    data=bpy.data.meshes.new(strip.name)
    data.from_pydata(vertices,[],faces)
    data.materials.append(ink)
    strip.data=data
    strip.location.z=0
    if old.users==0:
        bpy.data.meshes.remove(old)


def rounded_slabs(obj, slices, thickness):
    """Loft the strips on each side of a curved driveway return."""
    vertices, faces = [], []
    slices=sorted(slices)
    for (x0,ys0),(x1,ys1) in zip(slices,slices[1:]):
        for i in range(0,len(ys0),2):
            base=len(vertices)
            perimeter=((x0,ys0[i]),(x1,ys1[i]),(x1,ys1[i+1]),(x0,ys0[i+1]))
            vertices.extend((x,y,z) for z in (-thickness,0) for x,y in perimeter)
            faces.extend(tuple(base+j for j in face) for face in
                         ((3,2,1,0),(4,5,6,7),(0,1,5,4),(2,3,7,6)))
    old=obj.data
    data=bpy.data.meshes.new(obj.name)
    data.from_pydata(vertices,[],faces)
    data.materials.append(old.materials[0])
    obj.data=data
    obj.location.z=0
    if old.users==0:bpy.data.meshes.remove(old)


def prepare_roadway(scene, root, control, anchors, slots, rows, mats, design_length, morph_start,
                    morph_end, crossing=False, driveway_shifts=None, turn_pairs=None,
                    turn_arrows_at_driveways=False, driveway=None):
    """Update surfaces, property-driven geometry and editable paint on a roadway scene."""
    driveway = driveway or {}
    thickness=max((e.width for slot in slots for e in slot[:2] if e and e.kind=="sidewalk"),default=.12)
    length = roadway_length(scene,root,design_length,max(rows),thickness)
    half=length/2
    _,throat,flare=driveway_layout(design_length)
    throat=positive(driveway.get("width_m",throat),"Driveway width")
    flare=positive(driveway.get("radius_m",flare),"Driveway corner radius")
    mouth=throat+2*flare
    positions = {side: [driveway_center(design_length, side, end, driveway_shifts)
                        for end in (-1, 1)] for side in ("left", "right")}
    cuts = {side: [(center-mouth/2, center+mouth/2) for center in centers]
            for side, centers in positions.items()}
    walking={"sidewalk","curb"}
    for (strip,_),slot in zip(anchors,slots):
        element=slot[1] or slot[0]
        outside=element.kind in walking and element.zone in ("left","right")
        spans=split_at_driveways(-half,half,cuts[element.zone],False) if outside else [(-half,half)]
        base_ink=mats["travel"] if element.kind in {"turn","bike","buffer"} else mats[element.kind]
        build_strip_mesh(strip,spans,thickness,base_ink)
    pavement=collection(scene,"Driveways | illustrative positions")
    for side in ("left","right"):
        sidewalk_slots=[i for i,slot in enumerate(slots) if any(e and e.zone==side and e.kind in walking for e in slot[:2])]
        if not sidewalk_slots:
            continue
        # Each apron joins the road at the same dynamic outside boundary as the curb.
        start,stop=min(sidewalk_slots),max(sidewalk_slots)+1
        edges={"a":f"existing edge {start:02d}","b":f"proposed edge {start:02d}",
               "c":f"existing edge {stop:02d}","d":f"proposed edge {stop:02d}","p":"progress"}
        side_sign = -1 if side=="left" else 1
        widths=[(slots[i][0] or slots[i][1]).width for i in sidewalk_slots]
        total=sum(widths)
        curb_location=0
        for i in (sidewalk_slots if side=="right" else reversed(sidewalk_slots)):
            strip=anchors[i][0]
            strip_width=(slots[i][0] or slots[i][1]).width
            def contours(d):
                inset=flare-math.sqrt(max(0,flare**2-max(0,flare-d)**2))
                pad=throat/2+inset
                low, high = positions[side]
                return [-half,low-pad,low+pad,high-pad,high+pad,half]
            slices=[((u-.5)*side_sign,contours(curb_location+strip_width*u)) for u in [j/20 for j in range(21)]]
            rounded_slabs(strip,slices,thickness)
            curb_location+=strip_width
        for index,(a,b) in enumerate(cuts[side],1):
            driveway=box(pavement,f"Driveway | {side} {index}",(0,(a+b)/2,-thickness/2),
                         (1,b-a,thickness),mats["travel"],root)
            slices=[]
            for j in range(33):
                u=j/32
                d=total*u
                flare_width=flare-math.sqrt(max(0,flare**2-max(0,flare-d)**2))
                pad=throat/2+flare_width
                mid=(a+b)/2
                slices.append(((u-.5)*side_sign,[mid-pad,mid+pad]))
            rounded_slabs(driveway,slices,thickness)
            driveway.location.y=0
            # Continue each access beyond the frame so vehicles drive on pavement.
            approach=box(pavement,f"Driveway approach | {side} {index}",(0,mid,-thickness/2),
                         (90,throat,thickness),mats["travel"],root)
            outside="a*(1-p)+b*p" if side=="left" else "c*(1-p)+d*p"
            driver(approach,"location",0,control,edges,f"({outside})+({side_sign*45})")
            driver(driveway,"location",0,control,edges,"((a+c)*(1-p)+(b+d)*p)/2")
            driver(driveway,"scale",0,control,edges,"max(0,(c-a)*(1-p)+(d-b)*p)")
    ground=next((obj for obj in root.children if obj.name.split(".")[0]=="Ground"),None)
    if ground:
        ground.location.z=-thickness-.126

    span=morph_end-morph_start
    phases=(morph_start,*(morph_start+round(span*t) for t in (.16,.43,.60,.88,1)))
    _,_,old_end,lanes_end,_,_=phases
    # Geometry reallocates only in the gap between the two paint passes.
    curve=action_get_channelbag_for_slot(control.animation_data.action,control.animation_data.action_slot).fcurves.find('["progress"]')
    first,last=curve.keyframe_points[1],curve.keyframe_points[2]
    first.co.x, last.co.x = old_end,lanes_end
    curve.update()
    driveway_arrows = None
    if turn_arrows_at_driveways:
        driveway_arrows = {
            (side,end): center for side,centers in positions.items()
            if any(e and e.zone == side and e.kind in walking for slot in slots for e in slot[:2])
            for end,center in zip((-1,1),centers)
        }
    markings(collection(scene,"Editable lane markings"),anchors,slots,mats,root,length,
             design_length,cuts,phases,crossing,turn_pairs,driveway_arrows)
    if crossing:
        protected = collection(scene,"Protected midblock crossing")
        component=empty(protected,"Crossing placement | move with paths",root)
        component.location.y=crossing["center_m"]
        install_crossing(protected,component,slots,mats,phases,crossing.get("refuge_width_m"))
    for label,frame in zip(("Arrows fade","Wipe existing paint","Reallocate unmarked lanes",
                            "Apply proposed paint","Arrows return","Proposed street"),phases):
        existing=scene.timeline_markers.get(label)
        if existing:
            existing.frame=frame
        else:
            scene.timeline_markers.new(label,frame=frame)
    scene["Roadway thickness m"]=thickness
    scene["Visible design segment m"]=design_length
    scene["Extended slab length m"]=length
    return length


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
        if original.get("building_id") in config.get("visibility_overrides",{}):
            clone["visibility_override"] = config["visibility_overrides"][original["building_id"]]
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
    stage = primary.collection.children.get("Day 3 | editable geographic stage")
    source_mass = stage.children.get("Generated building volumes") if stage else None
    building_poses = []
    if source_mass and config.get("geography") and config.get("show_buildings", True):
        original_frame = primary.frame_current
        primary.frame_set(primary.frame_end)
        ground = stage.children.get("Geographic ground layers")
        floor = next((obj for obj in ground.objects if obj.name.split(".")[0] == "Ground"), None) if ground else None
        # Day 3 places its map on a lower Z plane to isolate it from Day 2.
        # Keep geographic X/Y and bring the entire massing stage to the new road surface.
        ground_z = floor.matrix_world.translation.z if floor else 0
        for obj in source_mass.objects:
            pose = obj.matrix_world.copy()
            pose[2][3] -= ground_z
            building_poses.append((obj,pose))
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
    scene.eevee.shadow_ray_count = 6
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
    light = bpy.data.lights.new("Soft directional key","SUN")
    light.energy, light.angle = 2.25, math.radians(3)
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
    for name, frame in (("Existing street",1),("Reallocate roadway",morph_start),
                        ("Proposed street",morph_end),("Final design hold",close)):
        scene.timeline_markers.new(name,frame=frame)
    crossing = config.get("midblock_crossing")
    crossing = {"center_m":0,**crossing} if crossing is not None else None
    extended = prepare_roadway(scene,root,control,anchors,slots,rows,mats,length,morph_start,
                               morph_end,crossing,
                               config.get("driveway_shifts_m"),config.get("turn_arrow_pairs"),
                               config.get("turn_arrows_at_driveways",False),config.get("driveway"))
    vcol = collection(scene,"Low-poly vehicles and editable paths")
    from roadway_traffic import motor_mesh, register_vehicle_asset
    from active_travel_assets import materials_for, ride_parts, walker_parts, wheelchair_parts
    for model in SIZES:
        register_vehicle_asset(model,motor_mesh(model,mats))
    palette=materials_for(mats,0)
    for model in ("road bike","cargo bike","e-bike","electric scooter"):
        register_vehicle_asset(model,ride_parts(model).mesh(model,palette))
    for model,parts in (("pedestrian",walker_parts()),("pedestrian with rollator",walker_parts(rollator=True)),
                        ("wheelchair user",wheelchair_parts())):
        from active_travel_assets import Parts
        combined=Parts()
        for _,offset,part,_ in parts:
            start=len(combined.vertices)
            combined.vertices.extend(tuple(a+b for a,b in zip(v,offset)) for v in part.vertices)
            combined.faces.extend(tuple(i+start for i in face) for face in part.faces)
            combined.inks.extend(part.inks)
        register_vehicle_asset(model,combined.mesh(model,palette))
    for (strip,_),(old,new,*_) in zip(anchors,slots):
        for phase, element, start, stop in (("existing",old,1,morph_start-5),
                                             ("proposed",new,morph_end+2,close-1)):
            selected = config.get("vehicles",{}).get(phase,{})
            if phase=="proposed" and config.get("midblock_crossing"):
                continue
            if phase=="existing" and config.get("vehicles",{}).get("traffic_cues"):
                continue
            if element and element.id in selected:
                model = selected.get(element.id) if isinstance(selected,dict) else ("bike" if element.kind=="bike" else "car")
                path_vehicle(vcol,root,strip,element,model,mats,extended+24,start,stop,scene.frame_end)
    if config.get("vehicles",{}).get("traffic_cues"):
        animate_traffic(scene,vcol,root,config,slots,mats)
    if config.get("midblock_crossing"):
        install_users(scene,root,config,slots,mats)
    if building_poses:
        import_buildings(scene,building_poses,root,extended,camera,max(roads),config)
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

