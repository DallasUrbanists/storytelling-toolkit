"""Bake the checked Maple crossing choreography into editable Blender paths and poses."""
from itertools import permutations
import math
import json
import bpy
import numpy as np
from bpy_extras.anim_utils import action_get_channelbag_for_slot
from active_travel_assets import materials_for,walker_parts,wheelchair_parts,ride_parts,paint_and_link
from crossing_paths import Layout,Route,ENDPOINTS,RIDER_SIZES,speed_clock,profile,road_user_path
from roadway_traffic import motor_mesh,register_vehicle_asset

def editable_path(group,root,name,route):
    curve=bpy.data.curves.new(name,"CURVE");curve.dimensions="3D";curve.use_path=True
    spline=curve.splines.new("POLY");spline.points.add(len(route.xy)-1)
    vertices=np.column_stack((route.xy,np.full(len(route.xy),.019),np.ones(len(route.xy))))
    spline.points.foreach_set("co",vertices.ravel())
    obj=bpy.data.objects.new(name,curve);group.objects.link(obj);obj.parent=root
    return obj

def simplified(values,tolerance):
    keep={0,len(values)-1};stack=[(0,len(values)-1)]
    while stack:
        a,b=stack.pop()
        if b-a<2:continue
        errors=abs(values[a:b+1]-np.linspace(values[a],values[b],b-a+1))
        j=int(errors.argmax())+a
        if errors[j-a]>tolerance:
            keep.add(j);stack.extend(((a,j),(j,b)))
    return sorted(keep)

def linear_keys(obj):
    a=obj.animation_data
    if a and a.action:
        for fc in action_get_channelbag_for_slot(a.action,a.action_slot).fcurves:
            for k in fc.keyframe_points:k.interpolation="LINEAR"


def key_motion(carrier, constraint, scene_frames, distance, length):
    for index in simplified(distance,.009):
        constraint.offset_factor=float(distance[index]/length)
        constraint.keyframe_insert(data_path="offset_factor",frame=int(scene_frames[index]))
    linear_keys(carrier)


def retime_motion(carrier, scene=None):
    """Apply the selected actor's editable speed, arrival and yielding controls."""
    scene = scene or bpy.context.scene
    data = json.loads(carrier["Timing recipe"])
    cue = data["cue"]
    for field, label in (("speed","Speed m/s"),("at","Arrival seconds"),("drive_wait","Driveway wait seconds")):
        cue[field] = float(carrier[label])
    if cue["speed"]<=0 or cue["drive_wait"]<0:
        raise ValueError("Speed must be positive and wait nonnegative")
    follow = next(c for c in carrier.constraints if c.type=="FOLLOW_PATH")
    path = Route([p.co[:2] for p in follow.target.data.splines[0].points],radius=0)
    for key, value in data["stations"].items():
        setattr(path,key,value*path.d[-1])
    path.slow=[(a*path.d[-1],b*path.d[-1]) for a,b in data["slow"]]
    path.cross=data["cross"]
    path.crossing_center=data["center"]
    if cue["drive_wait"] and not hasattr(path,"access_stop"):
        raise ValueError("A driveway wait needs a driveway path")
    frames=np.arange(data["first"],data["last"]+1)
    fps=scene.render.fps/scene.render.fps_base
    windows=json.loads(carrier["Yield windows seconds"])
    closures={int(k):v for k,v in windows.items()} if carrier["Yield at crossing"] else None
    distance=profile(path,cue,(frames-data["zero"])/fps,cue["kind"],closures)
    if carrier.animation_data:
        carrier.animation_data_clear()
    key_motion(carrier,follow,frames,distance,path.d[-1])
    scene.frame_set(scene.frame_current)

def bake_route_archive(scene,root,layout,fps):
    from build_roadway import collection
    group=collection(scene,"Bicycle itinerary library | 56 directed trips")
    group.hide_render=True
    for i,(origin,dest) in enumerate(permutations(ENDPOINTS,2)):
        path=layout.active(origin,dest)
        obj=editable_path(group,root,f"Ride | {origin} to {dest}",path)
        model=list(RIDER_SIZES)[i%4]
        speed={"road bike":5.8,"cargo bike":4.6,"electric scooter":4.4,"e-bike":6.0}[model]
        stops=[(path.gates[1],1.2)] if path.cross else []
        t,d=speed_clock(path,speed,stops,2.0)
        # Native evaluation time is a distance fraction on the equally spaced polyline.
        obj.data.path_duration=100
        last=math.ceil(t[-1]*fps);frames=np.arange(last+1)
        dist=np.interp(frames/fps,t,d)
        for k in simplified(dist,.018):
            obj.data.eval_time=100*dist[k]/path.d[-1]
            obj.data.keyframe_insert(data_path="eval_time",frame=int(frames[k])+1)
        linear_keys(obj.data)
        obj["origin"]=origin;obj["destination"]=dest;obj["model"]=model
        obj["traversal seconds"]=float(t[-1]);obj["length m"]=float(path.d[-1])
        obj["walk bicycle intervals m"]=str([(round(a,2),round(b,2)) for a,b in path.slow])
        obj["crosses at refuge"]=bool(path.cross)
        assert np.all(np.diff(dist)>=0) and abs(dist[-1]-path.d[-1])<.001
        if path.cross:
            x,y=path.xy[np.abs(path.xy[:,0]).argmin()]
            assert .40<y-layout.crossing_center<2.74
    group.hide_viewport=True
    scene["Validated directed rider itineraries"]=len(group.objects)

def install_users(scene,root,cfg,slots,mats):
    from build_roadway import collection,empty,visible
    spec=cfg["midblock_crossing"]
    layout=Layout(slots, cfg["length_m"], cfg.get("driveway_shifts_m"), spec.get("center_m",0))
    old={e.id:(x+w/2,1 if e.direction=="forward" else -1) for e,_,x,_,w,_ in slots if e and e.kind=="travel"}
    fps=scene.render.fps/scene.render.fps_base
    after=scene.timeline_markers["Proposed street"].frame
    existing_end=scene.timeline_markers["Arrows fade"].frame
    closures={int(k):v for k,v in spec.get("yield_windows_seconds",{}).items()}
    paths=collection(scene,"Crossing traffic | editable paths")
    actors=collection(scene,"Crossing traffic | vehicles and people")
    new_assets={}
    for index,cue in enumerate(spec.get("users",[]),1):
        kind,model=cue["kind"],cue["model"]
        pre=kind in ("pedestrian","opening rider")
        first=1 if pre else (existing_end if cue.get("role")=="two-stage mounted rider" else after)
        last=existing_end if kind=="opening rider" else scene.frame_end
        frames=np.arange(first,last+1)
        seconds=(frames-(1 if pre else after))/fps
        route=road_user_path(layout,old,cue)
        gates=closures if kind=="motor" or cue.get("yield_side") else None
        dist=profile(route,cue,seconds,kind,gates)
        name=f"{index:02d} | {model} | "+(cue.get("role") or (cue.get("origin","")+" to "+cue.get("dest","") if "origin" in cue else cue.get("movement","through")))
        path=editable_path(paths,root,"Travel path | "+name,route)
        carrier=empty(actors,name);carrier.empty_display_size=.22
        carrier["user index"]=index;carrier["user type"]=kind;carrier["model"]=model
        con=carrier.constraints.new("FOLLOW_PATH");con.target=path;con.use_fixed_location=True
        con.use_curve_follow=True;con.forward_axis="FORWARD_Y";con.up_axis="UP_Z"
        key_motion(carrier,con,frames,dist,route.d[-1])
        carrier["Speed m/s"]=cue["speed"]
        carrier["Arrival seconds"]=cue["at"]
        carrier["Driveway wait seconds"]=cue.get("drive_wait",0.)
        carrier["Yield at crossing"]=gates is not None
        carrier["Yield windows seconds"]=json.dumps(gates or {})
        carrier["Timing recipe"]=json.dumps({
            "cue":cue,"first":first,"last":last,"zero":1 if pre else after,
            "stations":{key:getattr(route,key)/route.d[-1] for key in ("entry","access_stop") if hasattr(route,key)},
            "slow":[(a/route.d[-1],b/route.d[-1]) for a,b in route.slow],
            "cross":int(route.cross),"center":getattr(route,"crossing_center",0)})
        pieces=[]
        if kind=="motor":
            canonical=bpy.data.objects.get("Roadway vehicle | "+model)
            mesh=canonical.data if canonical else motor_mesh(model,mats)
            obj=paint_and_link(actors,carrier,mesh,"Motor | "+name)
            bevel=obj.modifiers.new("Small edge bevel","BEVEL");bevel.width=.045;bevel.segments=1
            pieces=[obj]
        elif kind=="pedestrian":
            palette=materials_for(mats,index)
            speed=np.abs(np.gradient(dist))*fps
            stride=np.sin(dist*math.tau/1.48+index)*np.clip(speed/1.45,0,1)
            if model == "wheelchair user":
                body_parts = wheelchair_parts()
            else:
                body_parts = walker_parts(rollator=model == "pedestrian with rollator")
            for label,xyz,part,mult in body_parts:
                obj=paint_and_link(actors,carrier,part.mesh(label+" | "+name,palette),label+" | "+name,xyz)
                pieces.append(obj)
                if label == "Wheelchair wheel":
                    for k in simplified(dist,.009):
                        obj.rotation_euler.x = -float(dist[k]/.324)
                        obj.keyframe_insert(data_path="rotation_euler",index=0,frame=int(frames[k]))
                    linear_keys(obj)
                elif mult:
                    # The amplitude falls to zero when the person waits at the refuge or driveway.
                    sample=sorted(set([*range(0,len(frames),3),len(frames)-1]))
                    for k in sample:
                        obj.rotation_euler.x=float(stride[k]*mult*(.29 if model=="pedestrian with rollator" else .47))
                        obj.keyframe_insert(data_path="rotation_euler",index=0,frame=int(frames[k]))
                    linear_keys(obj)
        else:
            if model not in new_assets:
                new_assets[model]=ride_parts(model).mesh("Micromobility | "+model,materials_for(mats,index))
                register_vehicle_asset(model,new_assets[model])
            obj=paint_and_link(actors,carrier,new_assets[model],"Rider | "+name)
            pieces=[obj]
        for obj in pieces:visible(obj,first,last,scene.frame_end)
    bake_route_archive(scene,root,layout,fps)
    for label,frame in (("After | traffic at capacity",after+round(5*fps)),("After | traffic clears",after+round(15*fps))):
        mark=scene.timeline_markers.get(label) or scene.timeline_markers.new(label);mark.frame=frame
