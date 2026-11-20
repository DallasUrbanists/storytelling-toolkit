"""Reusable low-poly vehicle silhouettes and editable traffic animation."""
import math
import bpy
import numpy as np
from bpy_extras.anim_utils import action_get_channelbag_for_slot
from traffic_paths import SIZES, sample_movement


def motor_mesh(model, mats):
    width, length, height = SIZES[model]
    verts, faces, inks = [], [], []
    materials=[mats[k] for k in ("car","glass","ink","white")]
    def block(x,y,z,w,l,h,ink=0,top=None):
        # z is the base. The upper rectangle can taper or lean independently.
        base=len(verts)
        tw,tl,shift=top or (w,l,0.)
        for a,b,dy,dz in ((w,l,0.,0.),(tw,tl,shift,h)):
            for xx,yy in ((-1,-1),(1,-1),(1,1),(-1,1)):
                verts.append((x+xx*a/2,y+dy+yy*b/2,z+dz))
        for face in ((3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)):
            faces.append(tuple(base+i for i in face)); inks.append(ink)
    def cab(y,l,base,roof,front_lean=.12):
        block(0,y,base,width*.92,l,roof-base,1,(width*.80,l*.77,-front_lean))
        block(0,y-front_lean,roof-.035,width*.83,l*.79,.075)
        for side in (-1,1):
            block(side*width*.433,y-.10*l,base+.03,.07,.09,(roof-base)*.91)
    def wheels(axles,r):
        for y in axles:
            for side in (-1,1):
                base=len(verts)
                for dx in (-.12,.12):
                    for angle in range(0,360,45):
                        rad=math.radians(angle)
                        verts.append((side*(width*.485-.12)+dx,y+r*math.sin(rad),r+r*math.cos(rad)))
                faces.extend([tuple(base+i for i in reversed(range(8))),tuple(base+8+i for i in range(8))])
                for i in range(8):
                    j=(i+1)%8
                    faces.append((base+i,base+j,base+8+j,base+8+i))
                inks.extend([2]*10)
    if model in {"sedan","SUV","minivan","pickup"}:
        belt=height*.62
        block(0,0,.28,width,length,belt-.28,0,(width*.96,length*.98,0))
        cabin={"sedan":(.0,.58),"SUV":(-.055,.70),"minivan":(-.06,.77),"pickup":(.105,.42)}[model]
        cab(cabin[0]*length,cabin[1]*length,belt,height)
        if model=="pickup":
            block(0,-.30*length,belt+.01,width*.80,length*.31,.05,2)
            for side in (-1,1):
                block(side*width*.46,-.31*length,belt,.11,length*.34,.14)
            block(0,-.473*length,belt,width*.94,.12,.14)
        if model=="SUV":
            for side in (-1,1):
                block(side*width*.28,-.18,height+.035,.06,length*.41,.055,2)
        wheels([-.31*length,.32*length],.32)
    elif model in {"transit bus","school bus"}:
        school=model=="school bus"
        cabin_length=length-(1.25 if school else 0)
        middle=(cabin_length-length)/2
        block(0,0,.39,width,length,height*.43,0)
        block(0,middle,height*.40,width,cabin_length,height*.56)
        front=middle+cabin_length/2
        # A sloped windshield reads as glass even when the high camera sees the front from above.
        cap=height*.96
        block(0,front-.21,height*.68,width*.90,.56,cap-height*.68+.015,1,
              (width*.85,.34,-.12))
        block(0,front+.015,height*.49,width*.87,.06,height*.34,1)
        rear=middle-cabin_length/2
        block(0,rear-.018,height*.54,width*.79,.04,height*.25,1)
        if not school:
            block(0,front+.05,height*.84,width*.57,.04,.15,2)
        else:
            for side in (-1,1):
                block(side*width*.38,rear-.04,height*.83,.25,.06,.10,2)
                block(side*width*.38,front+.04,height*.86,.25,.06,.10,2)
                block(side*width*.49,middle,height*.40,.06,cabin_length*.96,.12,2)
        for side in (-1,1):
            n=7 if school else 6
            for j in range(n):
                y=middle+cabin_length*((j+.5)/n-.5)
                block(side*width*.503,y,height*.52,.035,cabin_length/n*.81,height*.28,1)
        for y in ((-.23,.14) if not school else (-.12,)):
            block(0,middle+y*cabin_length,height*.96,width*.38,.67,.10,0)
        wheels([-.33*length,.31*length],.46)
    else:
        articulated=model=="tractor-trailer"
        cab_length=3.40 if articulated else 2.10
        cab_y=length/2-cab_length/2
        block(0,0,.43,width*.73,length-.32,.34,2)
        block(0,cab_y,.60,width*.94,cab_length,.75)
        cab(cab_y-.17,cab_length*.80,1.35,min(height*.85,2.76),.13)
        # Visible air between cab and cargo. The tractor's fifth wheel sits below it.
        gap=.72 if articulated else .22
        cargo=length-cab_length-gap
        block(0,-length/2+cargo/2,.84,width,cargo,height-.84)
        axles=[cab_y+cab_length*.28,cab_y-cab_length*.70,-length*.32]
        if articulated: axles.extend([cab_y-cab_length*.98,-length*.39])
        wheels(axles,.44)
    for side in (-1,1):
        block(side*width*.33,length/2+.014,height*.35,width*.16,.05,.12,3)
    data=bpy.data.meshes.new("Traffic asset | "+model)
    data.from_pydata(verts,[],faces)
    for m in materials:data.materials.append(m)
    for polygon,ink in zip(data.polygons,inks): polygon.material_index=ink
    return data


def register_vehicle_asset(model, mesh):
    """Expose a stationary, unparented vehicle for dragging into another scene."""
    name="Roadway vehicle | "+model
    asset=bpy.data.objects.get(name)
    if asset is None:
        asset=bpy.data.objects.new(name,mesh)
        bevel=asset.modifiers.new("Small edge bevel","BEVEL")
        bevel.width,bevel.segments=.045,1
    asset.data=mesh
    asset.asset_mark()
    asset.use_fake_user=True
    asset.asset_data.description=f"Editable low-poly {model}, facing local +Y, dimensions in metres."
    if not asset.asset_data.tags.get("Roadway traffic"):
        asset.asset_data.tags.new("Roadway traffic")
    return asset


def animate_traffic(scene, group, root, config, slots, mats):
    lanes={e.id:(x+w/2,-1 if e.direction=="reverse" else 1)
           for e,_,x,_,w,_ in slots if e and e.kind=="travel"}
    fps=scene.render.fps/scene.render.fps_base
    hold=config["timing"]["hold_frames"]
    times=np.arange(hold+1)/fps
    meshes={}
    for index,actor in enumerate(config["vehicles"]["traffic_cues"],1):
        model,lane=actor["model"],actor["lane"]
        if model not in meshes:
            meshes[model]=motor_mesh(model,mats)
            register_vehicle_asset(model,meshes[model])
        width=next(e.width for e,*_ in slots if e and e.id==lane)
        if SIZES[model][0]+.15>width:raise ValueError(f"{model} does not fit {lane}")
        xy, headings, fractions, points=sample_movement(
            actor, lanes, config["length_m"], times, config.get("driveway_shifts_m")
        )
        name=f"{index:02d} {model} | {actor.get('movement','through')} | {lane}"
        curve=bpy.data.curves.new(name,"CURVE");curve.dimensions="3D";curve.use_path=True
        spline=curve.splines.new("POLY");spline.points.add(len(points)-1)
        coords=np.column_stack((points,np.full(len(points),.02),np.ones(len(points))))
        spline.points.foreach_set("co",coords.ravel())
        path=bpy.data.objects.new("Path | "+name,curve);group.objects.link(path);path.parent=root
        obj=bpy.data.objects.new(name,meshes[model]);group.objects.link(obj)
        bevel=obj.modifiers.new("Small edge bevel","BEVEL");bevel.width=.045;bevel.segments=1
        obj["traffic model"]=model;obj["traffic cue"]=index
        con=obj.constraints.new("FOLLOW_PATH");con.target=path
        con.use_fixed_location=True;con.use_curve_follow=True;con.forward_axis="FORWARD_Y";con.up_axis="UP_Z"
        # Preserve stops and speed changes while keeping straight sections easy to edit.
        keep={0,hold}
        def simplify(a,b):
            if b-a<2:return
            error=np.abs(fractions[a:b+1]-np.linspace(fractions[a],fractions[b],b-a+1))
            j=int(error.argmax())
            if error[j]>.000075:
                keep.add(a+j);simplify(a,a+j);simplify(a+j,b)
        simplify(0,hold)
        for frame in sorted(keep):
            con.offset_factor=float(fractions[frame]);con.keyframe_insert(data_path="offset_factor",frame=1+frame)
        for fcurve in action_get_channelbag_for_slot(obj.animation_data.action,obj.animation_data.action_slot).fcurves:
            for key in fcurve.keyframe_points:key.interpolation="LINEAR"
        # Vehicle is already fully outside the camera at the final key.
        for prop in ("hide_render","hide_viewport"):
            setattr(obj,prop,False);obj.keyframe_insert(data_path=prop,frame=hold+1)
            setattr(obj,prop,True);obj.keyframe_insert(data_path=prop,frame=hold+2)
    for label,second in (("Traffic reaches capacity",5),("Traffic clears the frame",15)):
        marker=scene.timeline_markers.get(label) or scene.timeline_markers.new(label)
        marker.frame=1+round(second*fps)
