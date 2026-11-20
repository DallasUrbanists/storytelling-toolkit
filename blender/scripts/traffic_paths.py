"""Deterministic roadway movements in local metres, for editable Blender paths."""
import numpy as np

# Width, length and height of each stylized model in metres.
SIZES = {
    "sedan": (1.76, 4.35, 1.45), "pickup": (1.97, 5.25, 1.80),
    "SUV": (1.94, 4.72, 1.76), "minivan": (1.94, 5.02, 1.78),
    "box truck": (2.26, 6.45, 2.95), "transit bus": (2.46, 9.35, 3.02),
    "school bus": (2.43, 9.05, 2.95), "tractor-trailer": (2.48, 15.4, 3.62),
}

def driveway_layout(length):
    throat = 6.2
    flare = 1.35
    offset = length/2 - min(8.1, length*.28)
    return offset, throat, flare

def driveway_center(length, side, end, shifts=None):
    offset, _, _ = driveway_layout(length)
    return end * offset + (shifts or {}).get(f"{side}:{end}", 0)


def path_profile(actor, lanes, design_length, driveway_shifts=None):
    """Sample a straight route or a tangent-continuous quarter turn at constant spacing."""
    lane = actor["lane"]
    x, direction = lanes[lane]
    maneuver = actor.get("movement", "through")
    speed = actor["speed"]
    stop_distance = actor.get("stop_at")
    if maneuver == "through":
        vertices = np.array([[x, -direction*140.], [x, direction*140.]])
        anchor = 140.
    else:
        side, index = actor["driveway"]
        outward = -1 if side=="left" else 1
        inbound = maneuver=="into"
        horizontal = outward if inbound else -outward
        driveway_y = driveway_center(design_length, side, index, driveway_shifts) - horizontal*1.50
        corner = np.array([x, driveway_y])
        v, h = np.array([0., direction]), np.array([horizontal, 0.])
        entry, leave = (v,h) if inbound else (h,v)
        curb = max(abs(p[0]) for p in lanes.values())*4/3
        # Tangency on the driveway leg is at or beyond the curb.
        radius = max(4.4, abs(outward*curb-x)+1.1)
        a, b = corner-entry*radius, corner+leave*radius
        center = a + leave*radius
        theta = np.linspace(0, np.pi/2, 65)[:,None]
        arc = center - np.cos(theta)*radius*leave + np.sin(theta)*radius*entry
        vertices = np.vstack((a-entry*140, arc, b+leave*140))
        anchor = 140.
        # Waiting point sits just before the turn on the approach leg.
        if stop_distance is None:
            stop_distance = -2.2 if inbound else -2.9

    cumulative = np.r_[0., np.cumsum(np.linalg.norm(np.diff(vertices,axis=0),axis=1))]
    d = np.linspace(0., cumulative[-1], round(cumulative[-1]/.22)+1)
    points = np.column_stack([np.interp(d,cumulative,component) for component in vertices.T])
    if maneuver == "through":
        velocities = np.full_like(d,speed)
    else:
        arc_end = anchor + radius*np.pi/2
        away = np.maximum(np.maximum(anchor-d, d-arc_end),0.)
        velocities = np.minimum(speed, np.sqrt(3.6**2+2*1.6*away))
    wait = actor.get("wait",0.)
    if wait:
        stop = anchor + stop_distance
        velocities = np.minimum(velocities, np.sqrt(2*2.6*np.abs(d-stop)))
    times = np.r_[0., np.cumsum(2*np.diff(d)/(velocities[:-1]+velocities[1:]))]
    event_time = np.interp(anchor,d,times)
    if wait:
        stop_idx = np.argmin(abs(d-stop))
        times[stop_idx+1:] += wait
        if d[stop_idx]<anchor:
            event_time += wait
    return points, times - event_time, d

def sample_movement(actor, lanes, length, seconds, driveway_shifts=None):
    points, times, distances = path_profile(actor, lanes, length, driveway_shifts)
    if actor.get("opening_pause"):
        seconds=np.interp(seconds,*np.asarray(actor["opening_pause"]).T)
    clock=seconds-actor["at"]
    wait=actor.get("wait",0.)
    if wait:
        # Insert a duplicate distance key so a yielding vehicle comes completely to rest.
        index=int(np.argmax(np.diff(times)))
        timing=np.insert(times,index+1,times[index]+wait)
        station=np.insert(distances,index+1,distances[index])
        distance=np.interp(clock,timing,station)
    else:
        distance=np.interp(clock,times,distances)
    xy = np.column_stack([np.interp(distance,distances,component) for component in points.T])
    tangent = np.gradient(points,axis=0)
    direction = np.column_stack([np.interp(distance,distances,component) for component in tangent.T])
    direction /= np.linalg.norm(direction,axis=1)[:,None]
    return xy, direction, distance / distances[-1], points
