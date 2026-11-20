# Day 3 geographic research and 2.5D shots

This workflow keeps GIS measurements in QGIS and creates editable, local-meter scene geometry in Blender. Production files stay outside this repository. Use QGIS 3.44 LTR and Blender 5.3.

## Walking catchment

1. Supply a WGS 84 study-line GeoJSON at `data/corridor.geojson` inside the input directory. Use the actual study endpoints. The Maple example starts at Mockingbird Lane and ends at Oak Lawn Avenue.
2. Prepare the walking graph from an OSM snapshot (`osm.json`). The snapshot contains Overpass-style `elements`, a `query`, `source_url`, and an `osm3s.timestamp_osm_base`. Ways carry IDs, node IDs, tags, and ordered `geometry` entries with `lat` and `lon`. Retain barrier nodes and original timestamps. A live OSM map API extraction can use its retrieval time when labeled as such. Save the source snapshot and its bounding box alongside the existing production inputs.
3. Run the native QGIS Python launcher. Select a local projected CRS in meters. The equal-area stage uses EPSG:5070 for the U.S. population interpolation.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QGIS_CUSTOM_CONFIG_PATH = Join-Path $PWD 'scratch/day3-qgis-profile'
$qgisPython = 'C:/Program Files/QGIS 3.44.15/bin/python-qgis-ltr.bat'
& $qgisPython qgis/day3_research.py --input C:/Production/Maple/inputs --work scratch/maple --output C:/Production/Maple/day3 --crs EPSG:26914 --building-extent -96.837 32.806 -96.814 32.822
```

Open `Maple_Research.qgz` in QGIS. The GeoPackage holds the source graph, corridor, origins, reachable lines, catchment, building footprints, and available research overlays. Right-click **Reachable pedestrian network** and choose **Zoom to Layer** to inspect the resulting street connections. Turn off the catchment fill to inspect the native route fanout. Use Identify Features to inspect source attributes. Toggle the full pedestrian graph to compare where network reachability stops.

**Routing.** Native **Service area (from layer)** uses shortest-path distance. For a constant speed the distance budget is equivalent to time. The default 4.8 km/h and ten minutes yield 800 meters. Start points lie at both corridor endpoints and about every 100 m, and snap within 45 m. All three settings are configurable. Mapped pedestrian access, barriers, and foot-specific one-way tags affect the graph. Lines connect at shared mapped vertices. A grade-separated crossing with no shared vertex remains disconnected. Restricted or unmapped sidewalk links, origin snapping to nearby parallel geometry, crossing delay, stairs and slope can affect the result. Check outliers before publication. Use the dissolved 65 m frontage around the reachable lines as an estimated areal footprint. Exact path reachability lives in the line layer. See [QGIS network analysis](https://docs.qgis.org/3.44/en/docs/user_manual/processing_algs/qgis/networkanalysis.html) and [OpenStreetMap attribution](https://www.openstreetmap.org/copyright).

## Population

Save the matching [2024 Census TIGERweb block groups](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS2024/MapServer/10) as `block-groups.geojson`, with whole polygons and `GEOID`. Use [ACS table B01003](https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b01003.dat) for the 2020–2024 estimates and margins of error. Save `acs-2024.json` as a Census API-style table with a header row containing `B01003_001E`, `B01003_001M`, `state`, `county`, `tract` and `block group`. The table-based file columns `B01003_E001` and `B01003_M001` correspond to the API estimate and margin. Record the retrieval endpoints in `acquisition.json` as `{"acs":["<table URL>"], "tiger":["<boundary URL>"]}`.

The baseline sums each block group's population multiplied by the share of its area within the catchment. The report includes unrounded values and individual weights, rounds to the nearest 100, and recalculates at 40 m and 90 m frontage widths. The approximate 90% sampling margin treats contributions as independent and excludes uncertainty from uneven household distribution, the routing network, and the polygon. An allocation based on a locally verified housing-unit or residential-floor-area layer could improve the model. Footprints alone include nonresidential buildings and give no occupancy counts. A comparison using 2010 and 2020 decennial block counts could apply the same present-day catchment to each vintage's blocks and compare weights and sensitivity. That would describe change on a fixed geography. Overlapping ACS estimates cannot establish annual changes.

An editor may generate an approved caption after reviewing the value and methodology:

```powershell
python qgis/approve_population.py C:/Production/Maple/day3/population_review.json C:/Production/Maple/day3/approved_caption.json --value <rounded-value> --approved-by '<editor>'
```

Add the relative file as `approved_caption` in the shot JSON. The builder leaves the statistic out unless that option is supplied.

## Buildings and overlays

- Put municipal or other authoritative footprint polygons in `building-source.geojson` when available. Specify `--building-id`, `--building-source` and, if supported by verified metadata, `--verified-height-field` (meters) and `--level-field`. Otherwise, use OSM footprints within a representative `--building-extent` in longitude/latitude order. QGIS repairs polygon topology and exports `buildings.geojson` in WGS 84. IDs and source attribution travel with the mesh.
- Use an independently verified physical height first, then mapped levels × 3.2 m per floor, then an illustrative height (default 7 m). Both assumptions are editable in the shot JSON. An unverified OSM height is retained as metadata and excluded from the verified height tier.
- Reuse Day 2 DART rail and bus layers and supplement with `python qgis/gtfs_stops.py <feed.zip> <input-folder> --bounds <west> <south> <east> <north>`. Feed edition and effective coverage appear in the point attributes. The optional `--connections` file lists agency-verified interchanges by fixed-route `stop_id`, with the description, effective reference, source URL, and any location limits. A GTFS station point does not specify an on-demand curb pickup position.
- The city publishes [base zoning](https://gis.dallascityhall.com/arcgis/rest/services/sdc_public/Zoning/MapServer/15) and [PD 193](https://gis.dallascityhall.com/arcgis/rest/services/sdc_public/Zoning/MapServer/10) separately. Preserve the distinction in layer names. Overlays and ordinance interpretation require separate review.

## Blender

Append to a saved independent copy of the Day 2 project. The builder adds a camera-bound marker after the last frame and places the new geographic geometry in a separate collection with the same horizontal coordinate origin. It writes a new .blend path. Save creative edits in the individual production file. To build a standalone shot, use `--factory-startup` with no source project.

```powershell
blender -b C:/Production/Maple/Maple_day2_landscape.blend --python-exit-code 1 --python blender/scripts/add_urban_shot.py -- --config C:/Production/Maple/day3/maple_urban_shot.json --format landscape --output C:/Production/Maple/day3/Maple_day3_landscape.blend
```

The JSON takes the Day 2 `origin`, `detail_center`, WGS 84 files for `corridor`, `buildings`, optionally `walkshed`, `zoning`, `context_lines`, and optional `transit` entries with `name`, `file`, `color` and `kind: "points"` for stops. Set `subject_name`, `overview_title`, and `credit` for the edit. `bearing` is clockwise from north looking at the subject. Use `tilt` to override the default isometric angle of about 54.74° from overhead, or `end_tilt` for a later oblique angle. The `framing` options override `center`, `bearing`, `scale`, `overview_scale`, `tilt`, or `end_tilt` by format.

In Blender, use **Numpad 0** for the camera, then scrub from **Day 3 | 10-minute walkshed** to the 2.5D marker. Select the Day 3 camera to edit its transform keys in the Dope Sheet, or its Orthographic Scale keys under Camera Data. In the Outliner, toggle the optional overlay collections for viewport and render independently. Select a generated building and use Tab to edit its mesh. Its Custom Properties include the source ID and height method.

Use `--visibility normal|fade|hide|manual`. Fade uses 15% opacity by default, with a seven-frame ramp. The bake checks orthographic rays to sampled points in the visible roadway each frame and records every blocking building on those rays. Building geometry is sampled once at the start of the bake. Edit the poses or building meshes first, then rebake through `urban_camera.bake_visibility` if geometry or framing changes. To override an individual building, set `visibility_overrides` in JSON by stable ID or change the object's `visibility_override` (auto, show, fade, hide) before rebaking. The Object Color alpha keys remain editable. Eevee uses a dithered material, which avoids object-level transparency sorting but introduces stipple at low sample counts. Use more samples for the final render or choose `hide` for clean cuts. The animated line width is graphic and does not supply engineering dimensions for Day 4.

## Verification

```powershell
python -m unittest discover -s tests -p 'test_*.py'
& $qgisPython tests/validate_day3_qgis.py
blender -b --factory-startup --python-exit-code 1 --python tests/validate_day3_blender.py
```

Validate both orientations using frames from the original geographic story, the new overhead shot, the tilt, and the final close view. Review the alpha keys and inspect the roadway against a normal-visibility control render.


### Street context for the walkshed shot

Supply `context_lines` as a WGS 84 street network that extends beyond the entire overhead camera footprint in both formats. Add any wider source networks in `context_supplemental_lines` as a list of GeoJSON paths. The builder uses the walkshed camera center, authored scale and output aspect ratio to select street geometry with a small margin. Supply wider source data for larger overview scales. The camera target and walkshed scale are independent of the street network, and the normal map attribution should name every source used.

### Match the preceding map

The map builder carries the ground color and optional "map_style" settings
into a geographic extension. Supply "street_color", "street_width_m", and
"corridor_color" there when matching an established palette. The urban shot
can override those values through its own "map_style". Set "subject_width_px"
to match the corridor's overhead screen width at a 1920-pixel long edge. Its
closer 2.5D view retains the physical width as a minimum. Set
"walkshed_show_holes" to false to fill interior holes in the display geometry.
That switch has no effect on the source walking catchment or its analysis.
