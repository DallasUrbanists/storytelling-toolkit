"""Check the native scene after creative edits and render review stills or a clean clip."""
import argparse
import json
import math
from itertools import combinations
from pathlib import Path
import sys

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from bpy_extras.anim_utils import action_get_channelbag_for_slot
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_crash_clip import dimensions, contact_point
from traffic_checks import footprint_gaps


def ray_blocked(origin, target, meshes, graph):
    """Check only the named occluder, excluding the viewer's own vehicle shell."""
    for obj in meshes:
        m=obj.matrix_world.inverted()
        a,b=m@origin,m@target
        delta=b-a
        if delta.length<1e-6:continue
        tree=BVHTree.FromObject(obj,graph)
        hit,*_=tree.ray_cast(a,delta.normalized(),delta.length)
        if hit is not None:return True
    return False


def check_visibility(scene, actors, checks):
    for check in checks:
        scene.frame_set(check["frame"])
        viewer,screen,target=(actors[check[k]] for k in ("viewer","screen","target"))
        eye=viewer.matrix_world@Vector(check.get("eye_local",[.30,.30,1.22]))
        graph=bpy.context.evaluated_depsgraph_get()
        blocker=[o for o in screen.children if o.type=="MESH"]
        w,l=dimensions(target["Model"])
        locations=[target.matrix_world@Vector((w*x,l*y,z)) for x,y,z in
                   ((0,0,.85),(-.38,-.38,.75),(.38,.38,.75),(-.38,.38,.85),(.38,-.38,.85))]
        hidden=sum(ray_blocked(eye,p,blocker,graph) for p in locations)
        camera=scene.camera
        normal=camera.matrix_world.to_3x3()@Vector((0,0,1))
        origins=[p+normal*(camera.matrix_world.translation-p).dot(normal)
                 if camera.data.type=="ORTHO" else camera.matrix_world.translation for p in locations]
        camera_blocked=all(ray_blocked(a,p,blocker,graph) for a,p in zip(origins,locations))
        if check.get("driver_hidden",True) and hidden!=len(locations):
            raise ValueError(f"Driver can still see {len(locations)-hidden} target samples at {check['frame']}")
        if not check.get("driver_hidden",True) and hidden==len(locations):
            raise ValueError(f"Driver cannot see the target at {check['frame']}")
        if check.get("audience_visible",True):
            screen_point=world_to_camera_view(scene,scene.camera,locations[0])
            if camera_blocked or not (0<screen_point.x<1 and 0<screen_point.y<1):
                raise ValueError(f"Audience cannot see the target at {check['frame']}")


def island_gaps(points, headings, width, length, polygon):
    """Vectorized separating-axis test against an authored convex refuge nose."""
    edges=np.roll(polygon,-1,axis=0)-polygon
    laterals=np.stack((-headings[:,1], headings[:,0]),axis=1)
    axes=[headings,laterals]
    axes.extend(np.broadcast_to(n/np.linalg.norm(n),headings.shape) for e in edges
                if np.linalg.norm(e)>1e-8 for n in [np.array([-e[1],e[0]])])
    clearances=[]
    for axis in axes:
        road_projection=polygon@axis.T
        centre=np.einsum("ij,ij->i",points,axis)
        radius=(abs(np.einsum("ij,ij->i",headings,axis))*length
                +abs(np.einsum("ij,ij->i",laterals,axis))*width)/2
        clearances.append(np.maximum(centre-radius-road_projection.max(axis=0),
                                     road_projection.min(axis=0)-centre-radius))
    return np.maximum.reduce(clearances)


def animation_curves(item):
    animation=item.animation_data
    if not animation or not animation.action:return ()
    return action_get_channelbag_for_slot(animation.action,animation.action_slot).fcurves


def move_keys(curve, frames, displacement=0):
    for key in curve.keyframe_points:
        for coord in (key.co,key.handle_left,key.handle_right):
            coord.x+=frames
            coord.y+=displacement
    curve.update()


def sync_impacts(scene=None):
    """Follow edited Contact markers after the poses have been revised in Blender."""
    scene=scene or bpy.context.scene
    source=scene.frame_current
    spec=json.loads(scene["Review metadata"])
    settled=scene.timeline_markers["Settled | final hold"].frame
    actors={o["Actor ID"]:o for o in scene.objects if "Actor ID" in o}
    updates=[]
    try:
        for event in spec["impacts"]:
            label=event["label"]
            frame=scene.timeline_markers[event["marker"]].frame
            if not 2<=frame<=settled-36:
                raise ValueError(f"{label}: leave room for the effect before the final hold")
            scene.frame_set(frame)
            a,b=actors[event["actor"]],actors[event["other"]]
            p=contact_point(event,a,a["Model"])
            q=contact_point({"surface":event["other_surface"]},b,b["Model"])
            if (p.xy-q.xy).length>.45:
                raise ValueError(f"{label}: surfaces miss at frame {frame}")
            point=(p+q)/2
            updates.append((event,label,frame,point,{name:o.matrix_world.copy() for name,o in actors.items()}))
        for event,label,frame,point,matrices in updates:
            frames=frame-event["frame"]
            displacement=point-Vector(event["point"])
            for obj in scene.objects:
                if obj.get("Impact smoke")==label or obj.get("Impact pose")==label:
                    if obj.get("Released aid for"):
                        obj.matrix_basis=matrices[obj["Released aid for"]]
                    for curve in animation_curves(obj):
                        shift=displacement[curve.array_index] if curve.data_path=="location" else 0
                        move_keys(curve,frames,shift)
                shape_keys=getattr(obj.data,"shape_keys",None)
                if shape_keys:
                    for block in shape_keys.key_blocks:
                        if block.name.endswith(" | "+label):
                            for curve in animation_curves(shape_keys):
                                if curve.data_path==block.path_from_id("value"):
                                    move_keys(curve,frames)
            event["frame"]=frame
            event["point"]=list(point)
        scene["Review metadata"]=json.dumps(spec)
    finally:
        scene.frame_set(source)


def verify_scene(scene):
    spec=json.loads(scene["Review metadata"])
    actors={obj["Actor ID"]:obj for obj in scene.objects if "Actor ID" in obj}
    if set(actors)!={a["id"] for a in spec["actors"]}:
        raise ValueError("The actor collection and review metadata disagree")
    source=scene.frame_current
    settled=scene.timeline_markers["Settled | final hold"].frame
    if scene.frame_end-settled<150:
        raise ValueError("The settled hold needs at least 150 frames")
    if scene.render.fps!=30 or scene.render.fps_base!=1:
        raise ValueError("Clean sources run at 30 fps")
    if any(obj.type=="FONT" for obj in scene.objects):
        raise ValueError("Editorial text is present in the clean scene")
    keys={name:[] for name in actors}
    poses={name:[] for name in actors}
    try:
        camera_hold=None
        for f in range(1,scene.frame_end+1):
            scene.frame_set(f)
            if f>=settled:
                camera=np.r_[np.array(scene.camera.matrix_world).ravel(),scene.camera.data.ortho_scale]
                if camera_hold is None:camera_hold=camera
                elif not np.allclose(camera,camera_hold,atol=1e-6):
                    raise ValueError("The camera moves during the settled hold")
            for name,obj in actors.items():
                mx=obj.matrix_world
                lateral=(mx.to_3x3()@Vector((1,0,0))).xy.normalized()
                direction=(-lateral.y,lateral.x)
                keys[name].append([mx.translation.x,mx.translation.y,*direction])
                poses[name].append(np.array(mx))
        tracks={name:(np.array(k)[:,:2],np.array(k)[:,2:],*dimensions(actors[name]["Model"]))
                for name,k in keys.items()}
        for spec_actor in spec["actors"]:
            name=spec_actor["id"]
            tail=poses[name][settled-1:]
            if not np.allclose(tail,tail[0],atol=1e-5):
                raise ValueError(f"{name} moves during the settled hold")
        events=[]
        for event in spec["impacts"]:
            a,b=event["actor"],event["other"]
            marker=event.get("marker",f"Contact | {a} / {b}")
            current=scene.timeline_markers.get(marker)
            f=event["frame"]
            if current and current.frame!=f:
                raise ValueError(f"{marker}: run sync_impacts after changing the marker")
            events.append((a,b,f))
            if not 2<=f<settled:
                raise ValueError(f"Contact frame {f} falls outside the moving action")
            scene.frame_set(f)
            pa=contact_point(event,actors[a],actors[a]["Model"])
            pb=contact_point({"surface":event["other_surface"]},actors[b],actors[b]["Model"])
            if (pa.xy-pb.xy).length>.45:
                raise ValueError(f"Contact surfaces no longer meet at frame {f}")
            for name in (a,b):
                p=world_to_camera_view(scene,scene.camera,actors[name].matrix_world.translation)
                if not (.025<p.x<.975 and .025<p.y<.975):
                    raise ValueError(f"{name} contact goes off camera at frame {f}")
        for a,b in combinations(actors,2):
            gaps,_=footprint_gaps(tracks[a],tracks[b])
            allowed=np.zeros(len(gaps),dtype=bool)
            for x,y,f in events:
                if {x,y}!={a,b}:continue
                if abs(gaps[f-1])>.12 or gaps[f-2]<.015:
                    raise ValueError(f"{a}/{b}: late or premature contact at frame {f}")
                allowed[f-1:f+3]=True
            bad=np.flatnonzero((gaps<-.025)&~allowed)
            if bad.size:raise ValueError(f"{a}/{b}: unplanned overlap at frame {bad[0]+1}")
        for island in [o for o in scene.objects if o.name.startswith("Raised refuge nose") and not o.hide_render]:
            n=len(island.data.vertices)//2
            poly=np.array([(island.matrix_world@v.co).xy for v in island.data.vertices[:n]])
            for name,track in tracks.items():
                gap=island_gaps(*track,poly)
                bad=np.flatnonzero(gap<-.02)
                if bad.size:raise ValueError(f"{name}: refuge collision at frame {bad[0]+1}")
        check_visibility(scene,actors,spec["visibility_checks"])
        print(f"Verified {len(actors)} actors, {len(events)} contacts, {scene.frame_end-settled} hold frames",flush=True)
        return settled
    finally:
        scene.frame_set(source)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stills",type=Path)
    parser.add_argument("--frames",nargs="+",type=int,default=[])
    parser.add_argument("--preview",type=Path)
    parser.add_argument("--clean",type=Path)
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    scene=bpy.context.scene
    settled=verify_scene(scene)
    if args.stills:
        args.stills.mkdir(parents=True,exist_ok=True)
        scene.render.resolution_percentage=50
        scene.render.image_settings.file_format="PNG"
        frames=args.frames or [1,*[m.frame for m in scene.timeline_markers if m.name.startswith("Contact")],settled]
        for frame in sorted(set(frames)):
            scene.frame_set(frame)
            scene.render.filepath=str((args.stills/f"frame-{frame:04}.png").resolve())
            bpy.ops.render.render(write_still=True)
    if args.preview or args.clean:
        path=args.clean or args.preview
        if path.exists():parser.error(f"Choose an unused output: {path}")
        path.parent.mkdir(parents=True,exist_ok=True)
        scene.render.resolution_percentage=100 if args.clean else 25
        if not args.clean:
            scene.frame_step=3
            scene.render.fps=10
            scene.eevee.taa_render_samples=8
        scene.render.image_settings.media_type="VIDEO"
        scene.render.image_settings.file_format="FFMPEG"
        scene.render.ffmpeg.format="MPEG4"
        scene.render.ffmpeg.codec="H264"
        scene.render.ffmpeg.constant_rate_factor="HIGH"
        scene.render.use_file_extension=False
        scene.render.filepath=str(path.resolve())
        bpy.ops.render.render(animation=True)


if __name__=="__main__":
    main()
