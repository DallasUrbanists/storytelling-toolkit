"""Expand discrete, editable motion segments into ordinary Blender pose keys."""
import math


def motion_poses(motion):
    """Expand timed moves, holds and curves without requiring a physics solver."""
    keys = [list(motion["start"])]
    for segment in motion["segments"]:
        start, x, y, z, bearing, tilt = keys[-1]
        stop = segment["frame"]
        if type(stop) is not int or stop <= start:
            raise ValueError("Motion segment frames must increase")
        kind = segment["kind"]
        if kind == "hold":
            keys.append([stop,x,y,z,bearing,tilt])
            continue
        if kind not in {"move","curve","lane-change"}:
            raise ValueError(f"Unknown motion segment: {kind}")
        end = tuple(segment["to"])
        controls = segment.get("controls")
        if kind == "lane-change":
            span = (end[1]-y)/3
            controls = ((x,y+span),(end[0],end[1]-span))
        if kind == "curve" and (not controls or len(controls)!=2):
            raise ValueError("A curve needs two XY control points")
        curve = controls is not None
        ease = segment.get("ease","linear")
        if ease not in ("linear","in","out","in-out"):
            raise ValueError(f"Unsupported easing: {ease}")
        step = 1 if curve or ease!="linear" else stop-start
        for frame in range(start+step,stop+1,step):
            t = (frame-start)/(stop-start)
            if ease == "out": t=1-(1-t)**2
            if ease == "in": t=t*t
            if ease == "in-out": t=t*t*(3-2*t)
            a = 1-t
            if curve:
                p,q=controls
                u=a**3*x+3*a*a*t*p[0]+3*a*t*t*q[0]+t**3*end[0]
                v=a**3*y+3*a*a*t*p[1]+3*a*t*t*q[1]+t**3*end[1]
                dx=a*a*(p[0]-x)+2*a*t*(q[0]-p[0])+t*t*(end[0]-q[0])
                dy=a*a*(p[1]-y)+2*a*t*(q[1]-p[1])+t*t*(end[1]-q[1])
            else:
                dx,dy=end[0]-x,end[1]-y
                u,v=x+t*dx,y+t*dy
            if "bearing" in segment:
                angle=bearing+t*(segment["bearing"]-bearing)
            elif math.hypot(dx,dy)>1e-9:
                angle=math.degrees(math.atan2(dx,dy))+(180 if segment.get("reverse") else 0)
                previous=keys[-1][4]
                angle=previous+(angle-previous+180)%360-180
            else:
                angle=bearing
            k=z+t*(segment.get("z",z)-z)
            pitch=tilt+t*(segment.get("tilt",tilt)-tilt)
            keys.append([frame,u,v,k,angle,pitch])
    return keys
