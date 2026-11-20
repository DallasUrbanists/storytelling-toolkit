"""Verify motion and authoring controls on the synthetic protected-roadway example."""
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"blender/scripts"))
from protected_simulation import retime_motion
from traffic_paths import SIZES
from traffic_checks import footprint_gaps

scene=bpy.data.scenes["Roadway redesign"]
bpy.context.window.scene=scene
root=scene.objects["Roadway origin and bearing"]
actors=sorted((o for o in scene.objects if "user index" in o),key=lambda a:a["user index"])
opening=sorted((o for o in scene.objects if "traffic cue" in o),key=lambda a:a["traffic cue"])
start=scene.timeline_markers["Proposed street"].frame
assert len(actors)==3 and len(opening)==2
assert all(bpy.data.objects["Roadway vehicle | "+key].asset_data for key in SIZES)
assert all(bpy.data.objects["Roadway vehicle | "+key].asset_data for key in ("road bike","cargo bike","wheelchair user","pedestrian with rollator"))
names=["Arrows fade","Wipe existing paint","Reallocate unmarked lanes","Apply proposed paint","Arrows return"]
marks=[scene.timeline_markers[name].frame for name in names]
assert marks==sorted(set(marks))
component=scene.objects["Crossing placement | move with paths"]
assert component.location.y==2
component.location.y+=.2
assert abs(component.location.y-2.2)<.001
component.location.y-=.2

def poses(objects,frames):
    coordinates=[];headings=[]
    for frame in frames:
        scene.frame_set(frame)
        transforms=[root.matrix_world.inverted()@o.matrix_world for o in objects]
        coordinates.append([m.translation[:2] for m in transforms])
        headings.append([(m.to_3x3()@Vector((0,1,0)))[:2] for m in transforms])
    return np.array(coordinates),np.array(headings)

pre,heading=poses(opening,range(1,marks[0]))
gap,following=footprint_gaps(*[(pre[:,i],heading[:,i],*SIZES[o["traffic model"]][:2]) for i,o in enumerate(opening)])
assert gap.min()>0 and np.nanmin(following)>4.35
assert (np.linalg.norm(np.diff(pre,axis=0),axis=2)<.002).sum(axis=0).min()>8
assert abs(pre[-1,0,0]-pre[0,0,0])>2  # the lead actor actually turns
post,head=poses(actors,range(start,start+540))
sizes=[(.72,1.16),(1.76,4.35),(1.76,4.35)]
for i in range(3):
    for j in range(i):
        gap,_=footprint_gaps((post[:,i],head[:,i],*sizes[i]),(post[:,j],head[:,j],*sizes[j]))
        assert gap.min()>.05,(i,j,gap.min())
speed=np.linalg.norm(np.diff(post,axis=0),axis=2)
wait=(abs(post[:-1,0,0])<.45)&(speed[:,0]<.003)
assert wait.sum()>55
west=(speed[:,1]<.003)&(abs(post[:-1,1,1]-11)<.3)
east=(speed[:,2]<.003)&(abs(post[:-1,2,1]+7)<.3)
assert west.sum()>35 and east.sum()>35 and not np.any(west&east)
assert np.any(west&(speed[:,2]>.06)) and np.any(east&(speed[:,1]>.06))
car=actors[-1]
scene.frame_set(start+6*30)
before=car.matrix_world.translation.copy()
car["Speed m/s"]=6.0
car["Arrival seconds"]-=.25
retime_motion(car,scene)
assert (car.matrix_world.translation-before).length>.1
print("Verified following stop, non-overlapping refuge wait and independent yields, and in-Blender retiming")
