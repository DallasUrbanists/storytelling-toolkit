"""Editable low-poly walkers and micromobility, with jointed limbs and true wheel silhouettes."""
import math
import bpy
import numpy as np
from mathutils import Vector
from roadway_traffic import register_vehicle_asset

class Parts:
    def __init__(self):
        self.vertices=[];self.faces=[];self.inks=[]
    def shape(self,points,faces,color):
        k=len(self.vertices);self.vertices.extend(points)
        self.faces.extend(tuple(k+i for i in face) for face in faces)
        self.inks.extend([color]*len(faces))
    def box(self,p,size,color):
        x,y,z=p;a,b,c=np.array(size)/2
        self.shape([(x+dx*a,y+dy*b,z+dz*c) for dz in (-1,1) for dx,dy in [(-1,-1),(1,-1),(1,1),(-1,1)]],
          [(3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)],color)
    def bar(self,a,b,r,color,top=None):
        a=np.array(a);b=np.array(b);d=b-a
        d=d/np.linalg.norm(d);base=np.cross(d,(1,0,0) if abs(d[0])<.86 else (0,1,0));base/=np.linalg.norm(base)
        other=np.cross(d,base)
        pts=[p+rad*(base*math.cos(t*math.tau/8)+other*math.sin(t*math.tau/8)) for p,rad in ((a,r),(b,r if top is None else top)) for t in range(8)]
        self.shape(pts,[tuple(reversed(range(8))),tuple(range(8,16))]+[(i,(i+1)%8,(i+1)%8+8,i+8) for i in range(8)],color)
    def oval(self,p,size,color):
        x,y,z=p;w,l,h=size;pts=[]
        for zz,rr in ((-.49,.25),(-.31,.82),(.02,1),(.35,.78),(.49,.29)):
            pts.extend((x+w*.5*rr*math.cos(k*math.tau/10),y+l*.5*rr*math.sin(k*math.tau/10),z+zz*h) for k in range(10))
        faces=[tuple(reversed(range(10))),tuple(range(40,50))]
        faces.extend((j+i,j+(i+1)%10,j+(i+1)%10+10,j+i+10) for j in range(0,40,10) for i in range(10))
        self.shape(pts,faces,color)
    def wheel(self,y,r,x=0,width=.084):
        n=20;pts=[]
        inner=r-min(.065,r*.27)
        for dx,rad in ((-width/2,r),(width/2,r),(width/2,inner),(-width/2,inner)):
            pts.extend((x+dx,y+rad*math.cos(k*math.tau/n),r+rad*math.sin(k*math.tau/n)) for k in range(n))
        faces=[(j*n+i,j*n+(i+1)%n,((j+1)%4)*n+(i+1)%n,((j+1)%4)*n+i) for j in range(4) for i in range(n)]
        self.shape(pts,faces,2)
        for k in range(3):
            spoke=(r+inner)/2
            dy=spoke*math.cos(k*math.pi/3);dz=spoke*math.sin(k*math.pi/3)
            self.bar((x,y-dy,r-dz),(x,y+dy,r+dz),min(.014,r*.095),6)
    def mesh(self,name,materials):
        m=bpy.data.meshes.new(name);m.from_pydata(self.vertices,[],self.faces)
        for material in materials:m.materials.append(material)
        for face,index in zip(m.polygons,self.inks):face.material_index=index
        return m

def materials_for(mats,index):
    from build_roadway import material
    def saved(name,color):
        return bpy.data.materials.get("Roadway | "+name) or material(name,color)
    fabric=[(.10,.45,.46),(.72,.42,.15),(.29,.41,.63),(.67,.31,.23),(.43,.56,.31),(.51,.37,.54)]
    skins=[(.70,.40,.25),(.36,.18,.105),(.87,.64,.42),(.52,.30,.19)]
    return [saved("Jacket "+str(index%6),fabric[index%6]),saved("Indigo trousers",(.07,.12,.16)),
            mats["ink"],saved("Skin "+str(index%4),skins[index%4]),mats["white"],
            saved("Bicycle enamel",(.075,.52,.48)),saved("Wheel metal",(.47,.58,.57)),saved("Cargo box",(.69,.43,.19))]

def walker_parts(rollator=False):
    torso=Parts();torso.oval((0,0,1.18),(.45,.30,.57),0)
    head_y=.10 if rollator else .002
    torso.oval((0,head_y,1.56),(.238,.235,.29),3)
    torso.oval((0,head_y-.025,1.677),(.245,.24,.105),6 if rollator else 2)
    parts=[("body",(0,0,0),torso,0)]
    if rollator:
        frame=Parts()
        for side in (-1,1):
            x=side*.295
            frame.wheel(.32,.094,x,.05)
            frame.wheel(.69,.094,x,.05)
            frame.bar((x,.32,.10),(x,.37,1.045),.026,6)
            frame.bar((x,.69,.10),(x,.37,.87),.026,6)
            frame.bar((x,.31,1.045),(x,.47,1.045),.033,2)
        frame.bar((-.295,.58,.46),(.295,.58,.46),.022,6)
        frame.box((0,.525,.565),(.52,.28,.05),5)
        parts.append(("Rollator",(0,0,0),frame,0))
    for side in (-1,1):
        leg=Parts();leg.bar((0,0,0),(0,0,-.38),.095,1,.072);leg.bar((0,0,-.37),(0,-.012,-.75),.066,1,.049)
        leg.oval((0,.055,-.76),(.145,.255,.105),2);parts.append(("leg",(side*.103,0,.831),leg,side))
        arm=Parts()
        elbow=(side*.05,.105,-.265) if rollator else (0,-.025,-.255)
        hand=(side*.087,.355,-.325) if rollator else (0,.045,-.46)
        arm.bar((0,0,0),elbow,.075,0,.058)
        arm.bar(elbow,hand,.051,3,.04)
        parts.append(("arm",(side*.208,0,1.37),arm,0 if rollator else -side*.72))
    return parts


def wheelchair_parts():
    chair=Parts()
    chair.box((0,-.085,.54),(.49,.49,.075),2)
    chair.box((0,-.30,.77),(.5,.055,.46),5)
    chair.oval((0,-.16,.87),(.46,.32,.57),0)
    chair.oval((0,-.139,1.23),(.225,.233,.27),3)
    chair.oval((0,-.166,1.332),(.235,.23,.13),2)
    for side in (-1,1):
        x=side*.27
        chair.bar((x,-.29,.55),(x,.46,.17),.035,6)
        chair.bar((x,-.34,.48),(x,-.37,1.00),.026,6)
        chair.bar((x,-.40,.72),(x,.10,.72),.035,2)
        chair.wheel(.37,.091,x,.055)
        chair.bar((side*.12,-.15,.58),(side*.14,.27,.51),.084,1)
        chair.bar((side*.14,.27,.51),(side*.14,.38,.22),.062,1)
        chair.oval((side*.14,.445,.199),(.13,.224,.077),2)
        chair.bar((side*.192,-.08,1.01),(side*.24,.07,.755),.057,0)
        chair.bar((side*.24,.07,.755),(side*.33,-.08,.65),.042,3)
    chair.box((0,.455,.14),(.44,.23,.04),6)
    parts=[("Wheelchair and rider",(0,0,0),chair,0)]
    for side in (-1,1):
        wheel=Parts()
        radius=.324
        wheel.wheel(0,radius,width=.054)
        wheel.vertices=[(x,y,z-radius) for x,y,z in wheel.vertices]
        parts.append(("Wheelchair wheel",(side*.322,-.16,radius),wheel,0))
    return parts

def ride_parts(model):
    p=Parts();scoot=model=="electric scooter";cargo=model=="cargo bike";electric=model=="e-bike"
    if scoot:
        rear,front,r=-.48,.47,.125
        p.wheel(rear,r);p.wheel(front,r)
        p.box((0,-.03,.165),(.21,.85,.09),5);p.bar((0,front,.13),(0,.31,1.14),.044,5)
        p.bar((-.25,.31,1.14),(.25,.31,1.14),.036,2)
        hip=(0,-.11,.87);shoulder=(0,-.02,1.39);head=(0,.005,1.64);grip=(.23,.31,1.14)
    else:
        rear,front,r=(-.89,1.02,.29) if cargo else (-.59,.58,.319)
        p.wheel(rear,r);p.wheel(front,r)
        seat_y=-.37 if cargo else -.24
        axle=(0,rear,r);crank=(0,seat_y+.18,.32);seat=(0,seat_y,.85);steer=(0,.27,.89);wheel=(0,front,r)
        for a,b in ((axle,crank),(crank,seat),(axle,seat),(seat,steer),(steer,crank),(steer,wheel)):
            p.bar(a,b,.044 if electric else .032,5)
        if electric:p.bar((0,-.04,.41),(0,.16,.67),.077,1)
        if cargo:
            p.box((0,.57,.49),(.57,.72,.085),7)
            for x in (-.27,.27):p.box((x,.57,.63),(.055,.72,.28),7)
            for y in (.235,.905):p.box((0,y,.63),(.55,.055,.28),7)
        p.oval((0,seat_y,.885),(.19,.27,.07),2)
        p.bar((-.265,.30,.94),(.265,.30,.94),.031,2)
        hip=(0,seat_y,.96);shoulder=(0,seat_y+.22,1.35);head=(0,seat_y+.28,1.57);grip=(.23,.30,.94)
    p.bar(hip,shoulder,.132,0,.175);p.oval(head,(.236,.235,.26),3)
    p.oval((0,head[1]-.018,head[2]+.095),(.255,.275,.135),4)
    for side in (-1,1):
        sy=hip[1];g=(side*grip[0],grip[1],grip[2])
        elbow=(side*.18,(shoulder[1]+g[1])/2-.03,(shoulder[2]+g[2])/2-.085)
        p.bar((side*.14,*shoulder[1:]),elbow,.06,0);p.bar(elbow,g,.048,3)
        knee=(side*.115,sy+(.05 if scoot else .24),.56 if scoot else .69)
        foot=(side*.096,sy+side*(.19 if scoot else .14),.24 if scoot else .345+side*.085)
        p.bar((side*.083,sy,hip[2]),knee,.088,1,.066);p.bar(knee,foot,.059,1,.048)
        p.oval(foot,(.128,.24,.079),2)
    return p

def paint_and_link(group,parent,mesh,name,location=(0,0,0)):
    o=bpy.data.objects.new(name,mesh);group.objects.link(o);o.parent=parent;o.location=location
    return o
