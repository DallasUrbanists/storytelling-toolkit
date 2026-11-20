"""Attach representative GTFS directions to an existing route GeoJSON."""
import argparse
from collections import Counter, defaultdict
from csv import DictReader
from io import TextIOWrapper
import json
from pathlib import Path
from zipfile import ZipFile


def attach_directions(routes, gtfs, selected_stops=(), departures_only=False):
    features = routes["features"]
    wanted = {str(feature["properties"]["id"]) for feature in features}
    with ZipFile(gtfs) as archive:
        def rows(table):
            with TextIOWrapper(archive.open(f"{table}.txt"), encoding="utf-8-sig", newline="") as stream:
                yield from DictReader(stream)

        short_names = {row["route_id"]: row["route_short_name"] for row in rows("routes")
                       if row["route_short_name"] in wanted}
        trips = {row["trip_id"]: row for row in rows("trips")
                 if row["route_id"] in short_names and row.get("shape_id") and row.get("direction_id")}
        visits, final_stop = defaultdict(list), {}
        if selected_stops:
            stop_ids = set(selected_stops)
            unknown = stop_ids - {row["stop_id"] for row in rows("stops")}
            if unknown:
                raise ValueError(f"GTFS stop IDs not found: {', '.join(sorted(unknown))}")
            for row in rows("stop_times"):
                tid = row["trip_id"]
                if tid not in trips:
                    continue
                seq = int(row["stop_sequence"])
                final_stop[tid] = max(seq, final_stop.get(tid, -1))
                if row["stop_id"] in stop_ids:
                    visits[tid].append((seq, row))
        candidates = defaultdict(Counter)
        for tid, trip in trips.items():
            eligible = [row for seq, row in sorted(visits[tid], key=lambda item: item[0])
                        if not departures_only or (seq < final_stop[tid] and row.get("pickup_type") != "1")]
            if selected_stops and not eligible:
                continue
            headsign = next((row["stop_headsign"] for row in eligible if row.get("stop_headsign")), "")
            headsign = headsign or trip.get("trip_headsign", "")
            key = short_names[trip["route_id"]], trip["direction_id"]
            candidates[key][(trip["shape_id"], headsign)] += 1
        selected = {key: min(counts, key=lambda pattern: (-counts[pattern], pattern))
                    for key, counts in candidates.items()}
        shape_ids = {shape_id for shape_id, _ in selected.values()}
        coordinates = defaultdict(list)
        for row in rows("shapes"):
            if row["shape_id"] in shape_ids:
                coordinates[row["shape_id"]].append((int(row["shape_pt_sequence"]),
                    [float(row["shape_pt_lon"]), float(row["shape_pt_lat"])]))
        version = next(rows("feed_info"), {}).get("feed_version") if "feed_info.txt" in archive.namelist() else None

    by_route = defaultdict(list)
    for (route, direction_id), (shape_id, headsign) in sorted(selected.items()):
        points = [point for _, point in sorted(coordinates[shape_id])]
        if len(points) < 2:
            raise ValueError(f"GTFS shape {shape_id} is missing or too short")
        by_route[route].append({"direction_id": direction_id, "headsign": headsign or f"Direction {direction_id}",
                                "shape_id": shape_id, "feed_version": version,
                                "geometry": {"type": "LineString", "coordinates": points}})
    missing = wanted - by_route.keys()
    if missing:
        raise ValueError(f"No eligible GTFS directions for: {', '.join(sorted(missing))}")

    return {**routes, "features": [
        {**feature, "properties": {**feature["properties"],
                                  "directions": by_route[str(feature["properties"]["id"])]}}
        for feature in features
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", required=True, type=Path, help="GeoJSON with GTFS route_short_name as properties.id")
    parser.add_argument("--gtfs", required=True, type=Path, help="GTFS Schedule ZIP")
    parser.add_argument("--output", required=True, type=Path, help="New direction-ready GeoJSON")
    parser.add_argument("--stop", action="append", default=[], help="GTFS stop ID, repeat to include several stops")
    parser.add_argument("--departures-only", action="store_true", help="Keep directions with boardable onward trips")
    args = parser.parse_args()
    if args.departures_only and not args.stop:
        parser.error("--departures-only requires at least one --stop")
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    routes = json.loads(args.routes.read_text(encoding="utf-8-sig"))
    result = attach_directions(routes, args.gtfs, args.stop, args.departures_only)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")
    for feature in result["features"]:
        props = feature["properties"]
        directions = " / ".join(f"{d['direction_id']} {d['headsign']}" for d in props["directions"])
        print(f"{props['id']}: {directions}")


if __name__ == "__main__":
    main()
