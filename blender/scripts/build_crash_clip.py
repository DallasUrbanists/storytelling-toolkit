"""Generate an editable continuous roadway safety illustration and optional preview."""
import argparse
import json
import math
from itertools import combinations
from pathlib import Path
import sys

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_roadway import COLORS, box, build as build_road, collection, empty, material
from traffic_paths import SIZES
from traffic_checks import footprint_gaps
from roadway_traffic import motor_mesh
from urban_camera import key_camera
from active_travel_assets import materials_for, walker_parts

PAINT={"primary":(.78,.018,.025),"secondary":(.88,.58,.025),"context":(.23,.25,.28)}
SURFACES={"front":(1,1),"rear":(1,-1),"left":(0,-1),"right":(0,1)}
PERSON_SIZE=(.62,.55,1.73)


def pose_at(poses, frame):
    values=np.array(poses,dtype=float)
    return [float(np.interp(frame,values[:,0],values[:,i])) for i in range(1,values.shape[1])]


def freeze_road(scene, frame):
    scene.frame_set(frame)
    for obj in scene.objects:
        animation=obj.animation_data
        if animation and animation.action:
            animation.action=None  # keep drivers on the road's section edges
    for ink in bpy.data.materials:
        if ink.node_tree and ink.node_tree.animation_data:
            ink.node_tree.animation_data_clear()


def set_keys(obj, poses):
    for f,x,y,z,bearing,tilt in poses:
        obj.location=(x,y,z)
        obj.rotation_euler=(math.radians(tilt),0,-math.radians(bearing))
        obj.keyframe_insert(data_path="location",frame=f,group="Motion")
        obj.keyframe_insert(data_path="rotation_euler",frame=f,group="Motion")
    action=obj.animation_data.action
    for curve in action.layers[0].strips[0].channelbag(obj.animation_data.action_slot).fcurves:
        for key in curve.keyframe_points:
            key.interpolation="LINEAR"


def make_actor(col, root, cue, mats):
    name=cue["id"]
    model=cue["model"]
    actor=empty(col,name,root)
    actor["Actor ID"]=name
    actor["Model"]=model
    set_keys(actor,cue["poses"])
    if model in ("pedestrian","rollator"):
        palette=materials_for(mats,0)
        for label,at,part,_ in walker_parts(rollator=model=="rollator"):
            obj=bpy.data.objects.new(f"{name} | {label}",part.mesh(label,palette))
            col.objects.link(obj)
            obj.parent=actor
            obj.location=at
        return actor,None
    source="minivan" if model=="ambulance" else model
    ink=material(f"{name} | Body",PAINT[cue["role"]])
    shell=motor_mesh(source,dict(mats,car=ink))
    body=bpy.data.objects.new(f"{name} | Body",shell)
    col.objects.link(body)
    body.parent=actor
    bevel=body.modifiers.new("Soft edges","BEVEL")
    bevel.width=.038
    bevel.segments=1
    if model=="ambulance":
        width,length,height=SIZES[source]
        box(col,f"{name} | Roof light",(0,length*.15,height+.08),(width*.67,.28,.14),
            material("Ambulance light",(.85,.045,.06)),actor)
    return actor,body


def dimensions(model):
    return SIZES["minivan" if model=="ambulance" else model][:2] if model not in ("pedestrian","rollator") else PERSON_SIZE[:2]


def contact_point(event, actor, model):
    axis,sign=SURFACES[event["surface"]]
    result=Vector((0,0,.54))
    result[axis]=sign*dimensions(model)[axis]/2
    return actor.matrix_world@result


def crumple(body, surface, depth, frame):
    if body.data.shape_keys is None:
        body.shape_key_add(name="Undamaged",from_mix=False)
    key=body.shape_key_add(name=f"{surface.title()} crumple | frame {frame}",from_mix=False)
    axis,sign=SURFACES[surface]
    extent=max(sign*v.co[axis] for v in body.data.vertices)
    for v,original in zip(key.data,body.data.vertices):
        blend=max(0.,1-(extent-sign*original.co[axis])/.86)**2
        v.co[axis]-=sign*depth*blend
        v.co.z+=depth*.32*blend
    for f,value in ((frame-1,0),(frame+2,1)):
        key.value=value
        key.keyframe_insert(data_path="value",frame=f,group="Localized impact")


def rigid_pose(actor, frame):
    for child in actor.children:
        if " | arm" not in child.name: continue
        child.rotation_euler.x=0
        child.keyframe_insert(data_path="rotation_euler",index=0,frame=frame-1)
        child.rotation_euler.x=math.pi
        child.keyframe_insert(data_path="rotation_euler",index=0,frame=frame)


def smoke(col, position, frame, amount):
    ink=material("Impact smoke",(.34,.37,.39))
    for i in range(amount):
        angle=i*2.39996
        drift=Vector((math.cos(angle),math.sin(angle),.40+i*.085))
        size=.22+i*.047
        cube=box(col,f"Impact smoke {frame} | {i+1}",position,(size,)*3,ink)
        for f,scale,point in ((frame-1,0,position),(frame+5,.82,position+drift*.5),
                              (frame+18,1.25,position+drift),(frame+36,0,position+drift*2.1)):
            cube.location=point
            cube.scale=(scale,)*3
            cube.keyframe_insert(data_path="location",frame=f,group="Block smoke")
            cube.keyframe_insert(data_path="scale",frame=f,group="Block smoke")


def validate(cues, events, frames):
    identifiers=[c["id"] for c in cues]
    if len(set(identifiers))!=len(identifiers):
        raise ValueError("Actor IDs must be unique")
    by_id={c["id"]:c for c in cues}
    for cue in cues:
        poses=cue["poses"]
        if len(poses)<2 or poses[0][0]!=1 or any(a[0]>=b[0] for a,b in zip(poses,poses[1:])):
            raise ValueError(f"{cue['id']}: use increasing pose frames starting at 1")
        if poses[-1][0]>frames-150:
            raise ValueError(f"{cue['id']}: the scene needs 150 held frames after final movement")
    for event in events:
        f=event["frame"]
        if event["actor"]==event["other"] or {event["actor"],event["other"]}-set(by_id):
            raise ValueError("An impact needs two distinct actor IDs")
        if event["surface"] not in SURFACES or event["other_surface"] not in SURFACES:
            raise ValueError("Specify a named contact surface for both actors")
        if not 2<=f<=frames-150-36:
            raise ValueError("Allow time for the effect to settle and hold")
    t=np.arange(1,frames+1)
    tracks={}
    for cue in cues:
        x,y,_,heading,_=np.array([pose_at(cue["poses"],f) for f in t]).T
        yaw=np.deg2rad(heading)
        tracks[cue["id"]]=(np.column_stack((x,y)),np.column_stack((np.sin(yaw),np.cos(yaw))),
                           *dimensions(cue["model"]))
    for first,second in combinations(identifiers,2):
        gap,_=footprint_gaps(tracks[first],tracks[second])
        allowed=np.zeros(frames,dtype=bool)
        for e in events:
            if {e["actor"],e["other"]}=={first,second}:
                f=e["frame"]
                if abs(gap[f-1])>.12:
                    raise ValueError(f"{first}/{second}: miss the contact at frame {f} ({gap[f-1]:.3f} m)")
                allowed[f-1:f+3]=True
                scene_frame=f-2
                if scene_frame>=0 and gap[scene_frame]<.015:
                    raise ValueError(f"{first}/{second}: premature contact before frame {f}")
        bad=np.flatnonzero((gap<-.025)&~allowed)
        if bad.size:
            raise ValueError(f"{first}/{second}: unexpected overlap at frame {bad[0]+1}")


def build(config, directory, orientation):
    cues=config["actors"]
    events=config.get("impacts",[])
    frames=config["frames"]
    validate(cues,events,frames)
    roadway=json.loads((directory/config["roadway"]).read_text(encoding="utf-8-sig"))
    roadway.update(config.get("roadway_overrides",{}))
    roadway["vehicles"]={}
    scene=build_road(roadway,orientation)
    phase=config.get("layout","existing")
    freeze_road(scene,1 if phase=="existing" else scene.timeline_markers["Proposed street"].frame+1)
    scene.timeline_markers.clear()
    scene.name=config["id"]
    scene.frame_end=frames
    scene["Illustration"]=config["description"]
    root=scene.objects["Roadway origin and bearing"]
    col=collection(scene,"Actors | editable motion")
    mats={k:material(k,v) for k,v in COLORS.items()}
    actors={c["id"]:make_actor(col,root,c,mats) for c in cues}
    by_id={c["id"]:c for c in cues}
    impact_col=collection(scene,"Impact | local deformation and smoke")
    for event in events:
        frame=event["frame"]
        scene.timeline_markers.new(f"Contact | {event['actor']} / {event['other']}",frame=frame)
        scene.frame_set(frame)
        a,body=actors[event["actor"]]
        b,other=actors[event["other"]]
        surface,other_surface=event["surface"],event["other_surface"]
        pa=contact_point(event,a,by_id[event["actor"]]["model"])
        pb=contact_point({"surface":other_surface},b,by_id[event["other"]]["model"])
        if (pa.xy-pb.xy).length>.45:
            raise ValueError(f"Selected impact surfaces do not meet at frame {frame}")
        for actor,mesh,face in ((a,body,surface),(b,other,other_surface)):
            if mesh: crumple(mesh,face,event.get("crumple_m",.22),frame)
            else: rigid_pose(actor,frame)
        smoke(impact_col,(pa+pb)/2,frame,event.get("smoke_blocks",6))
    settled=max(c["poses"][-1][0] for c in cues)
    settled=max([settled,*[e["frame"]+36 for e in events]])
    scene.timeline_markers.new("Settled | final hold",frame=settled)
    cfg=config["camera"][orientation]
    key_camera(scene.camera,1,cfg["target"],cfg["scale"],cfg["bearing"],cfg["tilt"],115)
    bpy.context.view_layer.update()
    for f in [1,*[e["frame"] for e in events],settled]:
        scene.frame_set(f)
        for cue in cues:
            if cue["role"]=="context":continue
            obj,_=actors[cue["id"]]
            point=world_to_camera_view(scene,scene.camera,obj.matrix_world.translation)
            if not (.025<point.x<.975 and .025<point.y<.975):
                raise ValueError(f"{cue['id']} outside {orientation} preview at frame {f}")
    scene.frame_set(1)
    return scene


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--format",choices=("portrait","landscape"),required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--preview",type=Path)
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    for path in (args.output,args.preview):
        if path and path.exists():
            parser.error(f"Choose an unused output: {path}")
        if path:
            path.parent.mkdir(parents=True,exist_ok=True)
    scene=build(json.loads(args.config.read_text(encoding="utf-8-sig")),args.config.parent,args.format)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    if args.preview:
        scene.render.resolution_percentage=25
        scene.eevee.taa_render_samples=8
        scene.frame_step=3
        scene.render.fps=10
        scene.render.image_settings.media_type="VIDEO"
        scene.render.image_settings.file_format="FFMPEG"
        scene.render.ffmpeg.format="MPEG4"
        scene.render.ffmpeg.codec="H264"
        scene.render.use_file_extension=False
        scene.render.filepath=str(args.preview.resolve())
        bpy.ops.render.render(animation=True)


if __name__=="__main__":
    main()
