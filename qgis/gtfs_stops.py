"""Export service-dated fixed-route stops and a separately verified GoLink interchange layer."""
import argparse
import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile


def records(feed, name):
    with feed.open(name + ".txt") as stream:
        yield from csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig"))


def make_stop(row, **fields):
    return {"type": "Feature", "geometry": {"type": "Point",
                "coordinates": [float(row["stop_lon"]), float(row["stop_lat"])]},
            "properties": {"stop_id": row["stop_id"], "name": row["stop_name"], **fields}}


def export(feed_path, output, bounds, connections=None):
    with ZipFile(feed_path) as feed:
        info = next(records(feed, "feed_info"))
        edition = {"feed_version": info["feed_version"], "feed_start_date": info["feed_start_date"],
                   "feed_end_date": info["feed_end_date"], "publisher": info["feed_publisher_name"]}
        routes = {row["route_id"]: row for row in records(feed, "routes")}
        trips = {row["trip_id"]: routes[row["route_id"]] for row in records(feed, "trips")}
        stops = {row["stop_id"]: row for row in records(feed, "stops")}
        west, south, east, north = bounds
        local = {key for key, row in stops.items() if west <= float(row["stop_lon"]) <= east
                 and south <= float(row["stop_lat"]) <= north}
        services = {}
        for visit in records(feed, "stop_times"):
            stop_id = visit["stop_id"]
            if stop_id not in local:
                continue
            route = trips[visit["trip_id"]]
            if route["route_type"] != "3":
                continue
            services.setdefault(stop_id, set()).add(route["route_short_name"])
        features = [make_stop(stops[key], routes=", ".join(sorted(value)), **edition)
                    for key, value in sorted(services.items())]
        if not features:
            raise ValueError("No active bus stops found within the given extent")
        output.mkdir(parents=True, exist_ok=True)
        def save(name, features):
            (output / name).write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2),
                                       encoding="utf-8")
        save("stops.geojson", features)
        if connections:
            links = json.loads(connections.read_text(encoding="utf-8"))
            save("connections.geojson", [make_stop(stops[record["stop_id"]], **{
                k:v for k,v in record.items() if k != "stop_id"}, **edition) for record in links])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("feed", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--bounds", type=float, nargs=4, required=True)
    p.add_argument("--connections", type=Path)
    args = p.parse_args()
    export(args.feed, args.output, args.bounds, args.connections)


if __name__ == "__main__":
    main()
