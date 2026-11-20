# Configure Maple Avenue transit and callouts

Use a copy of the revised Day 2 project. Keep the story JSON alongside its `data` folder. Edit the JSON for repeatable styling, use QGIS to inspect coordinates and source geometry, render in Blender, and assemble the renders in Resolve.

## 1. Restyle the callouts

Add these fields to the `DART station markers` layer in `maple-story.json`. Apply the same fields to `Regional landmarks` if desired.

```json
"label_backing": true,
"backing_corner": 0,
"backing_x_padding": 0.002,
"backing_color": "c2efdf",
"leader_color": "7fd7bd",
"dot_color": "ffe49a"
```

Zero makes the corners square. The padding is measured on each side as a fraction of the long render edge. At 1920 pixels, `0.002` gives about 3.8 pixels per side, down from 9.6. The hex values are example colors. The text contrast follows the backing color, and the pale casing still surrounds the leader.

## 2. Set speed, color, and opacity

In `Selected DART rail` change `"trace": 57` to `"trace": 40` for a faster rail reveal. In `Selected DART buses` change `"trace": 47` to `"trace": 67` for a slower bus reveal. These examples take about 1.33 and 2.23 seconds at 30 fps. Zero turns tracing off. Increase the shot's `hold` if the reveal needs more time. `delay` sets when a layer starts, and `fade` controls its opacity transition.

For one color across a layer, remove `color_property` and set `color`. For individual colors, keep `color_property` and edit the feature colors or set a route override. A route's `opacity` is multiplied by the shot's visibility for that layer.

```json
"route_overrides": {
  "ORANGE": {"color": "ffa54d", "opacity": 0.9, "trace": 35}
}
```

## 3. Set the bus animation origin

Add `"trace_origin": [-96.833204, 32.813602]` to `Selected DART buses`. This is the WGS 84 longitude and latitude of the SWMD/Parkland station feature, GTFS stop `29826`. Each bus trace starts at the closest point on its selected path. Some routes serve Inwood, so their snapped points can be elsewhere. Use `trace_origin` inside an individual `route_overrides` entry to replace the layer setting for that route. Without a coordinate, transit starts halfway along its longest path by length. In QGIS, use EPSG:4326 when copying a replacement coordinate.

## 4. Rename the station callouts

In `data/stations.geojson`, find each feature by `stop_id` and edit its `name`. You can also edit the attribute in QGIS and export a replacement WGS 84 GeoJSON. Keep the coordinates and other properties.

| Stop ID | New name |
| --- | --- |
| `29824` | Inwood/Love Field Station |
| `29826` | SWMD/Parkland Station |
| `29825` | Market Center Station |

Rebuild so the backing and collision placement fit the longer names. To edit the text directly in Blender, select the object ending in **Label**, press Tab, and edit the text. The backing is a separate curve that you can resize independently.

## 5. Choose bus directions leaving the stations

Copy `bus-departure-directions.geojson` into the project's `data` folder and change the bus layer's `file` to `data/bus-departure-directions.geojson`. To generate this file from a GTFS ZIP, run from the toolkit root.

```powershell
python tools/gtfs_directions.py --routes C:/Maple/data/bus.geojson --gtfs C:/Downloads/google_transit.zip --stop 33285 --stop 33286 --departures-only --output C:/Maple/data/bus-departure-directions.geojson
```

The IDs are the bus stops at Inwood/Love Field and SWMD/Parkland. The helper keeps representative published shapes for directions with boardable trips that have another stop after the station. It uses the stop-specific headsign when available, then the trip headsign. A selected shape includes the full trip alignment. Omit `--departures-only` to include arrival-only directions in the available choices. [GTFS Schedule reference](https://gtfs.org/documentation/schedule/reference/#tripstxt)

Add `route_overrides` to the bus layer. Use the exact route ID from the feature, including leading zeros, and a quoted direction ID or a full headsign. Omit `direction` or use `"all"` for the original combined geometry.

```json
"route_overrides": {
  "001": {"direction": "0"},
  "005": {"direction": "0"},
  "023": {"direction": "0"},
  "057": {"direction": "1"},
  "101": {"direction": "1"},
  "103": {"direction": "0"},
  "122": {"direction": "0"},
  "207": {"direction": "0"},
  "213": {"direction": "0"},
  "219": {"direction": "0"},
  "230": {"direction": "1"},
  "306": {"direction": "1"},
  "422": {"direction": "0"}
}
```

| Route | Departure headsigns, shortened for readability |
| --- | --- |
| 1 | 0 · Bexar |
| 5 | 0 · Love Field Airport |
| 23 | 0 · JB Jackson TC / MLK Jr Station |
| 57 | 1 · Wheatland |
| 101 | 1 · Wheatland |
| 103 | 0 · Downtown Dallas |
| 122 | 0 · SWMD/Parkland via Brookriver and Record Crossing (loop) |
| 207 | 0 · CBD West Transfer Center or 1 · Regal Row at Diplomacy |
| 213 | 0 · Bachman Station |
| 219 | 0 · Tyler/Vernon Station |
| 230 | 0 · Downtown Dallas or 1 · DFW South Remote Parking |
| 306 | 1 · Glenn Heights Park & Ride |
| 422 | 0 · UTSW/Parkland Shuttle |

Both directions of 207 and 230 serve onward stops. The example chooses 207 toward Downtown and 230 toward DFW. The IDs above are from DART feed `V761-218-220-20261115`.

## 6. Rebuild and review

From the toolkit root, run Blender 5.3 with the path to your edited JSON and a fresh output path.

```powershell
blender -b --factory-startup --python-exit-code 1 --python blender/scripts/build_story.py -- --config C:/Maple/maple-story.json --format landscape --output C:/Maple/Maple_controls_landscape.blend
blender -b --factory-startup --python-exit-code 1 --python blender/scripts/build_story.py -- --config C:/Maple/maple-story.json --format portrait --output C:/Maple/Maple_controls_portrait.blend
```

If PowerShell cannot find Blender, substitute `& 'C:/Program Files/Blender Foundation/Blender 5.3/blender.exe'` for `blender`. Open each scene, use Numpad 0 for camera view, and scrub from frames 29 and 177. Check the start points, callout fit, and route choices. Render test frames in both orientations before replacing the shots in Resolve.
