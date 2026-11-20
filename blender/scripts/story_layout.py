"""Geometry and screen layout for transit strokes and geographic labels."""
from collections import defaultdict
from itertools import product
from math import ceil, hypot


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def samples(path, spacing):
    result = [path[0]]
    for a, b in zip(path, path[1:]):
        steps = ceil(hypot(b[0] - a[0], b[1] - a[1]) / spacing)
        result.extend(mix(a, b, i / steps) for i in range(1, steps + 1))
    return result


def distance_to_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if not length2:
        return hypot(p[0] - a[0], p[1] - a[1])
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def tangent(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = hypot(dx, dy)
    return (dx / length, dy / length) if length else (0, 0)


def parallel_routes(groups, tolerance):
    """Return each resampled path and a vector per vertex in units of lane spacing."""
    spacing = tolerance * 0.8
    groups = [[samples(path, spacing) for path in paths] for paths in groups]
    cells = defaultdict(list)

    def cell(point):
        return tuple(int(value // tolerance) for value in point)

    for route, paths in enumerate(groups):
        for path in paths:
            if path[0] > path[-1]:
                path = path[::-1]
            for a, b in zip(path, path[1:]):
                cells[cell(mix(a, b, 0.5))].append((route, a, b, tangent(a, b)))

    result = []
    for route, paths in enumerate(groups):
        packed = []
        for path in paths:
            if len(path) < 2:
                continue
            hits, normals = [], []
            for i, point in enumerate(path):
                ux, uy = tangent(path[max(0, i - 1)], path[min(i + 1, len(path) - 1)])
                if path[0] > path[-1]:
                    ux, uy = -ux, -uy
                cx, cy = cell(point)
                nearby = {}
                for x, y in product(range(cx - 2, cx + 3), range(cy - 2, cy + 3)):
                    for other, a, b, (vx, vy) in cells[x, y]:
                        if other == route or abs(ux * vx + uy * vy) <= 0.94:
                            continue
                        distance = distance_to_segment(point, a, b)
                        if distance <= tolerance and (other not in nearby or distance < nearby[other][0]):
                            nearby[other] = distance, vx, vy
                hits.append(set(nearby))
                reference = min(nearby, default=route)
                if reference < route:
                    _, ux, uy = nearby[reference]
                normals.append((-uy, ux))

            # Require sustained shared alignment, then ease lanes in at junctions.
            for other in sorted(set().union(*hits)):
                start = 0
                while start < len(hits):
                    if other not in hits[start]:
                        start += 1
                        continue
                    end = start + 1
                    while end < len(hits) and other in hits[end]:
                        end += 1
                    if end - start < 7:
                        for i in range(start, end):
                            hits[i].discard(other)
                    start = end

            offsets = []
            for (nx, ny), lane in zip(normals, hits):
                side = sum(0.5 if other < route else -0.5 for other in lane)
                offsets.append((nx * side, ny * side))
            smooth = [
                tuple(sum(values) / 13 for values in zip(*offsets[max(0, i - 6):i + 7]))
                for i in range(len(path))
            ]
            packed.append((path, smooth))
        result.append(packed)
    return result


def rect(center, width, height):
    x, y = center
    return x - width / 2, y - height / 2, x + width / 2, y + height / 2


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def contained(r, frame):
    return r[0] >= frame[0] and r[1] >= frame[1] and r[2] <= frame[2] and r[3] <= frame[3]


def hits_rect(a, b, r):
    """Clip a segment against a rectangle using parametric slabs."""
    low, high = 0, 1
    for axis in (0, 1):
        delta = b[axis] - a[axis]
        if not delta:
            if not r[axis] <= a[axis] <= r[axis + 2]:
                return False
            continue
        u, v = sorted(((r[axis] - a[axis]) / delta, (r[axis + 2] - a[axis]) / delta))
        low, high = max(low, u), min(high, v)
        if low > high:
            return False
    return True


def crosses(a, b, c, d):
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def callout_geometry(anchor, offset, width, height):
    x, y = anchor
    dx, dy = offset
    side = 1 if dx >= 0 else -1
    elbow, edge = (x + dx * 0.67, y + dy), (x + dx, y + dy)
    return rect((edge[0] + side * width / 2, edge[1]), width, height), [(anchor, elbow), (elbow, edge)]


def callout_offsets(preferred):
    choices = [tuple(preferred)]
    choices.extend((side * length, rise) for length in (0.028, 0.046, 0.063, 0.080)
                   for side in (-1, 1) for rise in (0.022, -0.022, 0.038, -0.038, 0))
    return dict.fromkeys(choices)


class Placement:
    """Screen space inputs use fractions of the long render edge."""

    def __init__(self, pose, dimensions, visible_frames=None):
        self.center, self.scale = pose
        self.visible_frames = visible_frames
        width, height = (value / max(dimensions) for value in dimensions)
        self.frame = rect((0, 0), width - 0.038, height - 0.038)
        left, top = -width / 2, height / 2
        self.boxes = [(left, -top, left + 0.32, -top + 0.05)]
        self.leaders = []
        self.grid = defaultdict(list)

    def screen(self, point):
        return tuple((v - c) / self.scale for v, c in zip(point, self.center))

    @staticmethod
    def cells(r):
        return product(*(range(int(r[i] // 0.045), int(r[i + 2] // 0.045) + 1) for i in (0, 1)))

    def add_route(self, owner, packed, separation):
        for path, offsets in packed:
            screen = [self.screen(p) if not offsets else
                      (self.screen(p)[0] + offsets[i][0] * separation,
                       self.screen(p)[1] + offsets[i][1] * separation)
                      for i, p in enumerate(path)]
            for a, b in zip(screen, screen[1:]):
                extent = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
                padded = (self.frame[0] - 0.10, self.frame[1] - 0.10,
                          self.frame[2] + 0.10, self.frame[3] + 0.10)
                if overlap((extent[0] - 1e-9, extent[1] - 1e-9, extent[2] + 1e-9, extent[3] + 1e-9), padded):
                    segment = owner, a, b
                    for cell in self.cells(extent):
                        self.grid[cell].append(segment)

    def title_conflicts(self, box):
        """Penalize semantic overlays more than background street texture."""
        routes = {}
        for cell in self.cells(box):
            for name, a, b in self.grid.get(cell, ()):
                if hits_rect(a, b, box):
                    routes.setdefault(name, set()).add((a, b))
        street_weight = sum(min(3, len(parts)) for name, parts in routes.items() if name[0] == "street context")
        overlays = sum(1 for name in routes if name[0] != "street context")
        return (30 * sum(overlap(box, other) for other in self.boxes)
                + 12 * sum(hits_rect(*segment, box) for segment in self.leaders)
                + 8 * overlays + street_weight)

    def score(self, box, leader=(), owner=None):
        penalty = 5000 * (not contained(box, self.frame))
        penalty += 600 * sum(overlap(box, other) for other in self.boxes)
        penalty += 36 * sum(hits_rect(*segment, box) for segment in self.leaders)
        envelope = (min([box[0], *(p[0] for segment in leader for p in segment)]),
                    min([box[1], *(p[1] for segment in leader for p in segment)]),
                    max([box[2], *(p[0] for segment in leader for p in segment)]),
                    max([box[3], *(p[1] for segment in leader for p in segment)]))
        routes, crossing = set(), set()
        for cell in self.cells(envelope):
            for name, a, b in self.grid.get(cell, ()):
                if name == owner:
                    continue
                if hits_rect(a, b, box):
                    routes.add(name)
                if any(crosses(a, b, c, d) for c, d in leader):
                    crossing.add(name)
        penalty += 90 * len(routes) + 45 * len(crossing)
        for segment in leader:
            penalty += 180 * sum(hits_rect(*segment, other) for other in self.boxes)
            penalty += 55 * sum(crosses(*segment, *other) for other in self.leaders)
        return penalty



def title_corner(left_score, right_score, previous="LEFT"):
    """Use the preceding corner for effectively tied scores."""
    if abs(left_score - right_score) <= 1:
        return previous
    return "LEFT" if left_score < right_score else "RIGHT"


def place_callout(layouts, point, preferred, width, height):
    def cost(option):
        dx, dy = option
        conflict = sum(layout.score(*callout_geometry(layout.screen(point), option, width, height))
                       for layout in layouts)
        return conflict + 75 * hypot(dx, dy) + 40 * hypot(dx - preferred[0], dy - preferred[1])

    offset = min(callout_offsets(preferred), key=cost)
    for layout in layouts:
        box, leader = callout_geometry(layout.screen(point), offset, width, height)
        layout.boxes.append(box)
        layout.leaders.extend(leader)
    return offset

def split_trace(paths, coordinate=None):
    """Split the selected centerline at its midpoint or nearest segment point."""
    if coordinate is None:
        lengths = [[hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:])]
                   for path, _ in paths]
        part = max(range(len(paths)), key=lambda i: sum(lengths[i]))
        remaining = sum(lengths[part]) / 2
        for segment, length in enumerate(lengths[part]):
            if length and remaining <= length:
                fraction = remaining / length
                break
            remaining -= length
        else:
            segment, fraction = 0, 0
    else:
        best = None
        for index, (path, _) in enumerate(paths):
            for j, (a, b) in enumerate(zip(path, path[1:])):
                dx, dy = b[0] - a[0], b[1] - a[1]
                length2 = dx * dx + dy * dy
                t = max(0, min(1, ((coordinate[0] - a[0]) * dx + (coordinate[1] - a[1]) * dy) / length2)) if length2 else 0
                x, y = mix(a, b, t)
                candidate = (hypot(coordinate[0] - x, coordinate[1] - y), index, j, t)
                if best is None or candidate < best:
                    best = candidate
        _, part, segment, fraction = best
    path, offsets = paths[part]
    launch = mix(path[segment], path[segment + 1], fraction)
    cut = segment + (fraction == 1)
    if 0 < fraction < 1:
        cut = segment + 1
        path = [*path[:cut], launch, *path[cut:]]
        if offsets:
            offsets = [*offsets[:cut], mix(offsets[segment], offsets[segment + 1], fraction), *offsets[cut:]]
    branches = [(path[a:b][::stride], offsets[a:b][::stride])
                for a, b, stride in ((0, cut + 1, -1), (cut, len(path), 1)) if b - a >= 2]
    remaining_paths = []
    for index, (other, lane) in enumerate(paths):
        if index == part:
            continue
        if hypot(other[-1][0] - launch[0], other[-1][1] - launch[1]) < hypot(
                other[0][0] - launch[0], other[0][1] - launch[1]):
            other, lane = other[::-1], lane[::-1]
        remaining_paths.append((other, lane))
    return branches, remaining_paths
