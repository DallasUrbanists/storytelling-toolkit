# Day 2 geographic storytelling

The builder turns local WGS 84 map layers and a JSON sequence into an editable Blender scene. Keep the Day 1 import command for a standalone boundary. Use this builder when the map needs several shots, transit, or both output orientations.

## Build and review

Run from the repository root in PowerShell. Use Blender 5.3 on Windows for the workflow verified here. The example geometry is synthetic.

```powershell
blender --background --factory-startup --python-exit-code 1 --python blender/scripts/build_story.py -- --config examples/illustrative-story.json --format landscape --output scratch/illustrative-landscape.blend
blender --background --factory-startup --python-exit-code 1 --python blender/scripts/build_story.py -- --config examples/illustrative-story.json --format portrait --output scratch/illustrative-portrait.blend
blender --background scratch/illustrative-portrait.blend -o //portrait-#### -f 30,105,180
```

The output file path must be new. Save creative edits in the generated project and regenerate to a new file when geographic inputs change. The portrait project uses 1080 × 1920 and the landscape project uses 1920 × 1080. Both run at 30 fps.

In Blender, **Numpad 0** switches to the camera view. Scrub the Timeline and look for named focus markers. Use Rendered viewport shading to see material fades. Select a boundary curve in the Outliner and enter Edit Mode to adjust control points. The corresponding fill and outside mask are separate meshes and need to be rebuilt if the polygon changes. For callouts, select **Label placement** in the Outliner and edit its local X and Y to move the text and the leader elbow together. Select the **Label** text object and enter Edit Mode to change the wording. The **Geographic anchor** moves all parts of a callout. The camera object holds location keys, and the camera data holds **Orthographic Scale** keys. Select the appropriate data block when editing their keyframes.

## Prepare a new story

1. Prepare layers in QGIS. Validate polygon topology, dissolve boundaries as needed, and simplify excessively detailed layers at the intended map scale. Export each layer as GeoJSON in EPSG:4326. Keep the source and date with the production files.
2. Copy `examples/illustrative-story.json` into a new production folder. Point layer files to the exported geography using paths relative to that configuration. Set `origin` to a representative longitude and latitude near the project. The Blender conversion uses a local equirectangular approximation in meters, suitable for a compact metro area. Use QGIS for measurement and CRS transformations.
3. Add as many ordered `steps` as needed. Each step has a `title`, an optional `subtitle` or colored `note`, a `hold` duration in frames, and an incoming `transition` duration. The first step starts at frame 1. A transition of zero makes a cut. Specify one or more `focus` layers for automatic framing or provide `bounds` as west, south, east, north. Set an optional `center`, or override `bounds`, `center`, `padding` or `min_scale` for each orientation under `framing`.
4. Give each step a `layers` map from layer ID to opacity. The same nonzero value keeps the overlay visible across steps, lower values fade it into the background, and omitted IDs fade out. Each layer can set its `delay`, `fade`, and `trace` in frames. A traced layer draws on when it first becomes visible and again after a full disappearance.

| Layer kind | Input and controls |
| --- | --- |
| `boundary` | Polygon or MultiPolygon. Set `color`, `width` in pixels along the long image edge, `fill` opacity and optional `outside_dim` opacity. Import topology-valid rings. Set `show_holes: false` for a solid outer silhouette in the outline, fill and outside mask. The default preserves interior cutouts. |
| `route` | LineString or MultiLineString. Set `color`, `width`, and optionally `color_property` for per-feature hex colors. Use one ordered LineString for a connected study corridor and MultiLineString for genuinely discontinuous lines. Each part of a multipart line draws on concurrently. Set `interline` to offset sustained shared segments. |
| `callout`, `station` | Point features with a `name`. Set `radius`, `text_size` and `offsets` by orientation. Offsets are fractions of the image’s long edge, measured east and north from the anchor. Feature offsets override layer defaults. Set `label_backing: true` for a padded box in the leader color and `auto_place: true` to use the offsets as starting preferences for collision scoring. |
| `street_labels` | Road centerlines with a `name` and optional longitude/latitude `near` to indicate the preferred section. The builder sets upright text along a nearby segment. Set `color` and `text_size`. |
| `raster` | Optional flat backdrop. Export a north-up QGIS image in WGS 84, set matching `bounds` and put the raster first in the layer list. The image is packed into the .blend. |

For a shared GeoJSON, put an `id` in each feature's properties and pass those IDs through the layer's optional `select` array. Layers later in the JSON draw over layers earlier in the file. Put a wide study corridor before the transit layers if the lines should remain visible above it.

### Shared transit paths and route badges

- Set `interline: {"tolerance": 24, "spacing": 8}` on a transit layer. Put the routes to interline together in one GeoJSON layer with one feature per route. `tolerance` is the maximum matching distance in local projected meters. The builder looks for sustained, parallel alignment and eases the offset at joins and splits. `spacing` is center-to-center distance in pixels along the long render edge. Curve shape keys retain the source alignment and scale the separation with the camera.
- Set `route_labels: {"duration": 60}` to show badges for 60 frames from each route reveal. Traced transit routes start halfway along their longest path by length unless you supply a geographic origin. Set `route_labels: {"windows": [[30, 90], [180, 220]]}` to control inclusive frame intervals directly, or use an empty windows array to hide badges. Set a per-feature `route_label_timing` object to override layer timing. Supply a short name or number in the GeoJSON `route_label` property, or `false` to hide that badge. In Blender, the backing, text, position and visibility keys are editable.
- Automatic placement scores the box and leader against nearby labels, the frame, and visible routes marked `interline`, `route_labels` or `avoid_labels: true`. It checks camera poses for the scenes where a callout is visible and uses the same offset through the moves. Review both orientations after rendering. Set `auto_place: false` on a callout feature to use its configured offset exactly.

## Configure transit and callout styling

Use `route_overrides` by GeoJSON feature ID to set `trace`, `trace_origin`, `direction`, `color` or `opacity` for one route. A route layer's `trace_origin` is a WGS 84 longitude/latitude pair that snaps to the closest point on each path. Additional disconnected parts draw later in the reveal. Direction selection accepts a stored GTFS headsign or direction ID, and the original geometry is used by default. Run `python tools/gtfs_directions.py --help` to attach directional geometry from GTFS.

Set `backing_corner` to zero for square callout corners. Set `backing_x_padding` for horizontal padding. Both are fractions of the long render edge. Set `backing_color`, `leader_color` and `dot_color` independently.

Follow the [Maple Avenue walkthrough](maple-transit-controls.md) to apply the controls to the reference project.

## Validate

```powershell
python -m unittest discover -s tests -p "test_*.py"
blender --background scratch/illustrative-portrait.blend --python-exit-code 1 --python tests/validate_story_scene.py -- --config examples/illustrative-story.json --format portrait
```

Render representative frames before, during, and after reveals. Inspect the two formats independently for label edges, overlap and route-legibility problems. Render to a PNG sequence before the final edit in Resolve Free. Put individually edited project files and map sources in the production folder, outside the toolkit repository.
