"""Dallas pavement-marking geometry and the illustrative two-stage crossing."""
import json,math
from pathlib import Path
import numpy as np

def style_config():
    return json.loads((Path(__file__).resolve().parents[1]/"presets/dallas-roadway.json").read_text(encoding="utf-8-sig"))

def turn_outline(style):
    """Sheet 5008 silhouette. Coordinates run from the tail to the outside corner of the head."""
    def bezier(a,b,c,d):
        t=np.linspace(0,1,14)[:,None]
        return (1-t)**3*a+3*(1-t)**2*t*b+3*(1-t)*t**2*c+t**3*d
    outer=bezier(*map(np.array,[(1,.14),(1,.58),(.79,.76),(.41,.84)]))
    inner=bezier(*map(np.array,[(.40,.64),(.70,.58),(.80,.40),(.80,.14)]))
    outline=[(.80,0),(1,0),*outer,(.55,.96),(0,1),(.13,.56),(.28,.69),*inner]
    return [((x-.50)*style["turn_arrow_width_ft"]*.3048,y*style["turn_arrow_length_ft"]*.3048) for x,y in outline]

def without(spans,lo,hi):
    result=[]
    for a,b in spans:
        if a<lo:result.append((a,min(lo,b)))
        if b>hi:result.append((max(hi,a),b))
    return result

def install_crossing(col,root,slots,mats,phases,refuge_width=None):
    from build_roadway import box,mesh,material,visible
    incoming=phases[3];end=phases[-1]
    curb=max(abs(x+w/2)+w/2 for _,e,_,x,_,w in slots if e and e.kind=="bike")
    turn=next((w for _,e,_,_,_,w in slots if e and e.kind=="turn"),0)
    if turn<1.85:raise ValueError("The proposed center lane needs space for the configured refuge")
    half=min(1.40,turn/2-.09) if refuge_width is None else refuge_width/2
    if not .5 <= half <= turn/2-.09:
        raise ValueError("Refuge width must be at least one metre and fit inside the turn lane")
    cream=material("Refuge concrete",(.64,.66,.61))
    tactile=material("Detectable warning",(.79,.57,.22))
    green=material("Bicycle crossing",(.065,.34,.25))
    pole=material("Reflector post",(.72,.75,.67)); char=mats["ink"]
    pieces=[]
    def rect(name,x,y,z,w,l,h,m):
        obj=box(col,name,(x,y,z),(w,l,h),m,root);pieces.append(obj);return obj
    def island(name,sign):
        # The flat ends face the shared cut-through. Both outside noses are rounded.
        y0=3.12;cap=5.50
        poly=[(-half,y0),(half,y0),(half,cap)]
        poly +=[(half*math.cos(i*math.pi/18),cap+1.06*math.sin(i*math.pi/18)) for i in range(1,19)]
        if sign<0:poly=[(x,-y) for x,y in reversed(poly)]
        n=len(poly);verts=[(x,y,z) for z in (.025,.185) for x,y in poly]
        faces=[tuple(range(n-1,-1,-1)),tuple(range(n,2*n))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
        obj=mesh(col,name,verts,faces,cream,root);pieces.append(obj)
        y=sign*5.04
        # Low bollards outline the waiting area without intruding on either crossing.
        for x in (-half*.54,half*.54):
            rect("Refuge bollard",x,y,.50,.105,.105,.66,pole)
            rect("Bollard reflective band",x,y,.68,.109,.109,.09,tactile)
    for sign in (-1,1):island("Raised refuge nose",sign)
    # Two parallel channels leave an entirely flush waiting space between the noses.
    rect("Refuge | flush passage",0,0,.014,half*2,6.23,.024,cream)
    for side in (-1,1):
        start,end_x=sorted((side*half,side*curb))
        d=end_x-start
        for i in range(7):
            x=start+(i+.5)*d/7
            rect("Pedestrian crossing | ladder stripe",x,-1.40,.037,d/7*.52,2.66,.009,mats["white"])
        rect("Mounted bicycle crossing",.5*(start+end_x),1.56,.031,d,2.16,.009,green)
        for y in (.41,2.71):
            for i in range(6):
                rect("Bicycle crossing | white block",start+(i+.5)*d/6,y,.042,d/6*.47,.22,.009,mats["white"])
        for x in (side*(half-.21),side*(curb+.20)):
            rect("Flush detectable warning",x,-1.4,.047,.38,2.6,.017,tactile)
        # Stagger the yield markings by approach direction.
        e=next((entry for entry in slots if entry[1] and entry[1].kind=="travel" and np.sign(entry[3]+entry[5]/2)==side),None)
        if e:
            x=e[3]+e[5]/2; w=e[5]
            for j in (-1,0,1):
                xx=x+j*w*.26;yy=-side*6.4
                v=[(xx-.26,yy+side*.22,.033),(xx+.26,yy+side*.22,.033),(xx,yy-side*.34,.033)]
                pieces.append(mesh(col,"Yield triangle",v,[(0,1,2)],mats["white"],root))
    # Crosswalk paint and island appear during the proposed-paint pass.
    fade_materials={}
    for obj in pieces:
        source=obj.data.materials[0]
        if source not in fade_materials:
            fade=source.copy()
            fade.name="Crossing reveal | "+source.name
            fade.surface_render_method="DITHERED"
            nodes,links=fade.node_tree.nodes,fade.node_tree.links
            out=next(n for n in nodes if n.type=="OUTPUT_MATERIAL")
            original=out.inputs[0].links[0].from_socket
            mix=nodes.new("ShaderNodeMixShader")
            links.new(nodes.new("ShaderNodeBsdfTransparent").outputs[0],mix.inputs[1]);links.new(original,mix.inputs[2]);links.new(mix.outputs[0],out.inputs[0])
            for frame,amount in ((incoming,0.),(phases[-2],1.)):
                mix.inputs[0].default_value=amount;mix.inputs[0].keyframe_insert(data_path="default_value",frame=frame)
            fade_materials[source]=fade
        obj.data.materials[0]=fade_materials[source]
        visible(obj,incoming,100000,100000)
        obj["illustrative crossing"]=True
