"""Validate ordered, dimensioned sections and pair their editable boundaries."""
from dataclasses import dataclass
from math import isclose, isfinite

FEET_TO_METERS = 0.3048
TYPES = {"travel", "turn", "bike", "buffer", "parking", "sidewalk",
         "median", "refuge", "curb", "furnishing"}
OUTSIDE = {"sidewalk", "curb", "furnishing"}
DIRECTIONS = {"forward", "reverse", "both"}
CONFIDENCE = {"verified", "planning", "illustrative"}


def positive(value, label):
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be a positive number")
    return value


@dataclass(frozen=True)
class Element:
    id: str
    kind: str
    direction: str | None
    width: float
    zone: str
    source: str
    locked: bool
    derived: bool


def read_section(data, factor):
    curb = positive(data["curb_to_curb"], "Curb-to-curb width")
    right = positive(data["right_of_way"], "Right-of-way width")
    if right < curb:
        raise ValueError("Right-of-way cannot be narrower than curb-to-curb")
    totals = {"left": data["left_outside"], "road": curb, "right": data["right_outside"]}
    if any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in totals.values()):
        raise ValueError("Outside widths must be finite and nonnegative")
    if not isclose(sum(totals.values()), right, abs_tol=1e-6):
        raise ValueError("Outside widths plus the road must equal the right-of-way")
    rows = data["elements"]
    if len({row["id"] for row in rows}) != len(rows) or any(not row["id"] for row in rows):
        raise ValueError("Element IDs must be nonempty and unique")
    if any(row["zone"] not in totals for row in rows):
        raise ValueError("Use left, road, or right zones")
    if [row["zone"] for row in rows] != sorted(
        (row["zone"] for row in rows), key=list(totals).index
    ):
        raise ValueError("Write elements left to right, in order by zone")
    elements = []
    for zone, total in totals.items():
        selected = [row for row in rows if row["zone"] == zone]
        known = [positive(row["width"], row["id"]) for row in selected if row.get("width") is not None]
        unknown_count = len(selected) - len(known)
        remaining = total - sum(known)
        if unknown_count and remaining <= 0 or not unknown_count and not isclose(remaining, 0, abs_tol=1e-6):
            raise ValueError(f"{zone} allocation does not match its width of {total}")
        for row in selected:
            kind, direction = row["type"], row.get("direction")
            if kind not in TYPES or (kind in OUTSIDE and zone == "road"):
                raise ValueError(f"Invalid element type in {zone}: {kind}")
            if zone != "road" and kind not in OUTSIDE:
                raise ValueError(f"{kind} belongs inside the curb lines")
            if direction not in DIRECTIONS | {None} or (kind in {"travel", "bike", "turn"} and direction is None):
                raise ValueError(f"Invalid direction for {row['id']}")
            source = row["source"]
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f"Missing source for {row['id']}")
            derived = row.get("width") is None
            locked = row.get("locked", False)
            if type(locked) is not bool or locked and derived:
                raise ValueError(f"Only a known width can be locked: {row['id']}")
            width = remaining / unknown_count if derived else row["width"]
            elements.append(Element(row["id"], kind, direction, width * factor, zone, source, locked, derived))
    return {item.id: item for item in elements}, totals["left"] * factor, curb * factor, right * factor


def load_model(data):
    """Use an explicit ordered slot map to preserve a contiguous section at every progress value."""
    factor = {"ft": FEET_TO_METERS, "m": 1}[data.get("unit", "ft")]
    old, old_left, old_road, old_row = read_section(data["existing"], factor)
    new, new_left, new_road, new_row = read_section(data["proposed"], factor)
    order = data["mapping"]
    for column, section in (("existing", old), ("proposed", new)):
        if [slot[column] for slot in order if slot.get(column)] != list(section):
            raise ValueError(f"Mapping must include each {column} element once in cross-section order")
    slots = []
    x_old, x_new = -old_road / 2 - old_left, -new_road / 2 - new_left
    for slot in order:
        a, b = old.get(slot.get("existing")), new.get(slot.get("proposed"))
        if a is None and b is None:
            raise ValueError("An animation slot must reference at least one endpoint")
        if a and b and a.zone != b.zone:
            raise ValueError(f"A mapped element cannot change zones: {a.id}")
        old_width, new_width = a.width if a else 0, b.width if b else 0
        slots.append((a, b, x_old, x_new, old_width, new_width))
        x_old += old_width
        x_new += new_width
    return slots, (old_road, new_road), (old_row, new_row)


def validate_segments(segments, configurations):
    ids = set()
    for segment in segments:
        label = segment["id"]
        if not label or label in ids:
            raise ValueError("Corridor segment IDs must be nonempty and unique")
        ids.add(label)
        if segment["confidence"] not in CONFIDENCE or not segment["source"] or not segment["reference"]:
            raise ValueError(f"Missing confidence or provenance for {label}")
        if any(segment[key] not in configurations for key in ("existing", "proposed")):
            raise ValueError(f"Unknown cross-section in {label}")
        for endpoint in ("start", "end"):
            point = segment[endpoint]
            if point is None and segment["confidence"] == "illustrative":
                continue
            if len(point) != 2 or any(type(v) not in (int, float) for v in point):
                raise ValueError(f"Use [longitude, latitude] for {label} {endpoint}")
            if not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                raise ValueError(f"Invalid coordinate for {label} {endpoint}")
        if segment["start"] is not None and segment["start"] == segment["end"]:
            raise ValueError(f"Segment endpoints must differ: {label}")
        if segment.get("buffer_width_ft") is not None:
            positive(segment["buffer_width_ft"], "Buffer width")
