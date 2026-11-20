"""Paths and deterministic distance profiles for a two-stage midblock crossing, in metres."""
import numpy as np
from traffic_paths import driveway_center, driveway_layout

ENDPOINTS=("W-","W+","E-","E+","WD-","WD+","ED-","ED+")
RIDER_SIZES={"road bike":(.64,1.79,1.65),"e-bike":(.68,1.87,1.70),
             "electric scooter":(.60,1.22,1.77),"cargo bike":(.77,2.48,1.65)}
PEDESTRIAN=(.44,.46,1.72)
WALK_Y=-1.55
BIKE_Y=1.55
POST_FRAME=696

def unit(a):
    return a/np.maximum(np.linalg.norm(a,axis=-1,keepdims=True),1.e-12)

class Route:
    def __init__(self, waypoints, radius=1.0):
        raw=np.array(waypoints,dtype=float)
        raw=raw[np.r_[True,np.linalg.norm(np.diff(raw,axis=0),axis=1)>.015]]
        pts=[raw[0]]
        for a,b,c in zip(raw,raw[1:],raw[2:]):
            v,u=b-a,c-b
            cut=min(radius,np.linalg.norm(v)*.47,np.linalg.norm(u)*.47)
            p,q=b-unit(v)*cut,b+unit(u)*cut
            t=np.linspace(0,1,18)[:,None]
            pts.extend((1-t)**2*p+2*t*(1-t)*b+t**2*q)
        pts=np.array([*pts, raw[-1]])
        d=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(pts,axis=0),axis=1))]
        self.d=np.linspace(0.,d[-1],int(d[-1]/.13)+2)
        self.xy=np.array([np.interp(self.d,d,p) for p in pts.T]).T
        self.h=unit(np.gradient(self.xy,axis=0))
        self.curvature=np.linalg.norm(np.gradient(self.h,self.d,axis=0),axis=1)
        self.slow=[]
        self.cross=0
        self.gates=[]
    def station(self,x,y):
        return float(self.d[np.argmin(np.linalg.norm(self.xy-[x,y],axis=1))])
    def pose(self,d):
        loc=np.stack([np.interp(d,self.d,c) for c in self.xy.T],axis=-1)
        h=unit(np.stack([np.interp(d,self.d,c) for c in self.h.T],axis=-1))
        return loc,h

class Layout:
    def __init__(self, slots, length, driveway_shifts=None, crossing_center=0):
        self.length=length
        self.drive=driveway_layout(length)[0]
        self.driveway_shifts = driveway_shifts
        self.crossing_center = crossing_center
        self.lanes={}
        self.walk={};self.bike={};self.car={}
        for _,e,_,x,_,w in slots:
            if e is None:continue
            mid=x+w/2;side=1 if mid>0 else -1
            if e.kind in ("sidewalk","bike","travel"):
                {"sidewalk":self.walk,"bike":self.bike,"travel":self.car}[e.kind][side]=mid
            if e.kind in ("bike","travel"):self.lanes[e.id]=mid
            if e.kind=="turn":self.island_width=w
        self.curb=max(abs(x) for x in self.bike.values())+.76
    @staticmethod
    def end_info(name):
        return (-1 if name[0]=="W" else 1,1 if name[-1]=="+" else -1,"D" in name)
    def end_y(self,name):
        side,sign,drive=self.end_info(name)
        return self.driveway_y(side, sign) if drive else sign * 72.

    def driveway_y(self, side, end):
        return driveway_center(self.length, "left" if side < 0 else "right", end, self.driveway_shifts)
    def _side_leg(self,name,start,end,ped=False,corner_track=0):
        side,_,drive=self.end_info(name)
        use_walk=ped or side*(end-start)<0
        x=self.walk[side]+corner_track if use_walk else self.bike[side]
        return x,use_walk
    def active(self,origin,dest,ped=False,track=0):
        if origin==dest:raise ValueError("Distinct endpoints required")
        a,_,ad=self.end_info(origin);b,_,bd=self.end_info(dest)
        ay,by=self.end_y(origin),self.end_y(dest)
        cross= a!=b
        cy=self.crossing_center+(WALK_Y+track if ped else BIKE_Y+.34*a)
        # Driveway access stays on the right-hand side of its low-speed access leg.
        if ad:ay+=a*2.10
        if bd:by-=b*2.10
        ax,walk1=self._side_leg(origin,ay,cy if cross else by,ped,track)
        bx,walk2=self._side_leg(dest,cy if cross else ay,by,ped,track)
        pts=[(a*53,ay),(ax,ay)] if ad else [(ax,ay)]
        if cross:pts.extend([(ax,cy),(bx,cy)])
        pts.extend([(bx,by),(b*53,by)] if bd else [(bx,by)])
        path=Route(pts,.78 if not ped else .35)
        path.crossing_center=self.crossing_center
        if cross:
            path.cross=a
            path.gates=[path.station(self.bike[a],cy),path.station(0,cy),path.station(self.bike[b],cy)]
        if not ped:
            end=path.d[-1]
            if cross:
                if walk1:path.slow.append((0.,max(0.,path.gates[0]-.5)))
                if walk2:path.slow.append((min(end,path.gates[-1]+.5),end))
            elif walk1:path.slow.append((0.,end))
        path.entry=path.station(a*21,ay) if ad else path.station(ax,np.sign(ay)*48)
        return path
    def motor(self,cue):
        lane=cue["lane"];x=self.lanes[lane];sign=int(np.sign(x))
        move=cue.get("movement","through")
        if move=="through":
            path=Route([(x,-sign*88),(x,sign*88)])
            path.entry=path.station(x,-sign*48)
        else:
            side,index=cue["driveway"];side=-1 if side=="left" else 1
            into=move=="into";sideways=side if into else -side
            center = self.driveway_y(side, index)
            y=center-sideways*1.50
            left=side!=sign
            if into:
                pts=[(x,-sign*88)]
                if left:
                    # Enter the shared turn lane after clearing the island nose.
                    first=y-sign*16
                    relative=(first-self.crossing_center)*sign
                    if relative>0:first=self.crossing_center+max(6.8,relative)*sign
                    pts += [(x,first),(0,y-sign*5.4),(0,y)]
                else:pts.append((x,y))
                pts.append((side*65,y))
            else:
                pts=[(side*65,y),(x,y),(x,sign*88)]
            path=Route(pts,4.2 if not left else 3.9)
            path.entry=path.station(x,-sign*48) if into else path.station(side*21,y)
            # Stop upstream of sidewalk when leaving, before the bike lane when turning in.
            path.access_stop=path.station(side*(abs(self.walk[side])+1.35),y) if not into else path.station(0 if left else x,y-sign*4.9)
            path.side=side;path.drive_y=center
        path.crossing_center=self.crossing_center
        crosses=np.min(path.xy[:,1])<self.crossing_center-8 and np.max(path.xy[:,1])>self.crossing_center+8
        if crosses:path.cross=sign
        return path

def speed_clock(path,speed,stops,accel=3.8,corner_accel=3.3):
    """Integrate a distance-based speed envelope, with exact stationary dwells."""
    d=path.d
    local=np.minimum(speed,np.sqrt(corner_accel/np.maximum(.0001,path.curvature)))
    for a,b in path.slow:local[(d>=a)&(d<=b)]=np.minimum(local[(d>=a)&(d<=b)],1.65)
    indices=[]
    for place,wait in sorted(stops):
        k=int(np.abs(d-place).argmin())
        if not 0<k<len(d)-1:continue
        local[k]=0.
        indices.append((k,wait))
    # Squared speed envelope has slope +/-2a in distance space.
    sq=local**2
    sq=np.minimum.accumulate(sq-2*accel*d)+2*accel*d
    sq=np.minimum.accumulate((sq+2*accel*d)[::-1])[::-1]-2*accel*d
    v=np.sqrt(np.maximum(0,sq))
    clock=np.r_[0.,np.cumsum(2*np.diff(d)/np.maximum(.01,v[1:]+v[:-1]))]
    station=d.copy()
    for k,wait in reversed(indices):
        before=clock[k];clock[k+1:]+=wait
        clock=np.insert(clock,k+1,before+wait);station=np.insert(station,k+1,d[k])
    return clock,station

def profile(path,cue,seconds,kind,closures=None):
    motor=kind=="motor"
    a=3.8 if motor else 2.0
    stops=list(cue.get("stops",[]))
    if cue.get("drive_wait",0)>0:
        w,l,_=cue["size"];stops.append((path.access_stop-l/2,cue["drive_wait"]))
    def times():
        clock,station=speed_clock(path,cue["speed"],stops,a)
        event=cue.get("event",path.entry)
        return clock-np.interp(event,station,clock)+cue["at"],station
    clock,s=times()
    if closures and (cue.get("yield_side") or path.cross):
        sign=cue.get("yield_side",path.cross);x=cue["lane_x"];hl=cue["size"][1]/2
        y=getattr(path,"crossing_center",0)
        start=path.station(x,y-sign*(3.25+hl))
        end=path.station(x,y+sign*(3.25+hl))
        stopping=path.station(x,y-sign*(6.85+hl))
        for ready,clear in closures.get(sign,[]):
            entry=np.interp(start,s,clock);exit=np.interp(end,s,clock)
            if exit<=ready or entry>=clear:continue
            stops.append((stopping,0.))
            clock,s=times();k=np.flatnonzero(np.diff(s)==0)
            k=min(k,key=lambda j:abs(s[j]-stopping))
            hold=max(.25,clear-clock[k])
            stops[-1]=(stopping,hold);clock,s=times()
    if "departure_acceleration" in cue:
        start,factor=cue["departure_acceleration"]
        elapsed=np.maximum(seconds-start,0.)
        seconds=seconds+(factor-1)*np.where(elapsed<1.2,elapsed**2/2.4,elapsed-.6)
    return np.interp(seconds,clock,s)

def road_user_path(layout, old_lanes, cue):
    kind=cue["kind"]
    if kind=="motor":
        return layout.motor(cue)
    if kind=="opening rider":
        x,direction=old_lanes[cue["lane"]]
        x+=cue.get("lateral",0.)
        path=Route([(x,-direction*80),(x,direction*80)])
        path.entry=path.station(x,-direction*47)
        return path
    return layout.active(cue["origin"],cue["dest"],kind=="pedestrian",cue.get("track",0.))
