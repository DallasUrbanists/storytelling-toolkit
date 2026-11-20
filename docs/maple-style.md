# Maple style and editing workflow

Add `"style_preset": "maple"` at the top level of a story JSON to carry the final Maple Avenue design into a new build. Authored layer settings and per-feature overrides take precedence.

| Element | Preset |
| --- | --- |
| Landmark and station callouts | White backing, leader, casing and anchor dot, square corners, automatic placement, and one average glyph width of horizontal padding per side |
| Rail and bus badges | Uppercase text with square backings and rims. Rail badges use one average glyph width per side. Layers marked `"route_mode": "bus"` use lavender `#A695E9` for lines, tethers and badges. Rail colors follow the layer or route data. |
| Transit tracing | For route layers with `route_labels`, 30 frames (one second at 30 fps) unless a layer or route specifies a duration |
| Blender preview | Camera view at frame 1 with Rendered shading. The opening heading is visible on frame 1. Fully inactive map objects also stay hidden in Solid shading. |

Tag route layers with `"route_mode": "bus"` or `"route_mode": "rail"`. An explicit layer `uniform_color` replaces the preset's lavender and takes precedence over individual route colors. The default bus badge has a numeric padding of 0.0015 per side. Use `"character"` for measured, symmetric horizontal padding or a number as a fraction of the image's long edge. Badge placement scores visible routes, labels, leaders and screen edges in each pose where the badge is shown. Bus badges render above the routes even when a crossing cannot be avoided. A callout is fully white at full opacity. In the shot's `layers` map, use `1` for active station callouts that should stay white. Use `delay` and `fade` on the callout layer for timed entrances. Static basemap layers that are active in the opening shot are fully visible on frame 1. Set `opening_visible` to `false` to use a layer's opening fade.

## Prepare the production

- Use [the geographic story guide](day-2.md) for shared transit alignment, badge reveal timing, street names along road centerlines, and collision-aware label placement. Set `show_holes: false` on a layer when a solid boundary silhouette is desired. Put a wide corridor layer beneath transit in the JSON layer order.
- Keep geographic origins and transit directions in the project configuration. Verify them against that project's GeoJSON and GTFS. In the Maple example, the bus origin was `[-96.833204, 32.813602]` at SWMD/Parkland. Each route snaps to its own path. Select departures by route ID and GTFS direction or headsign. A route layer can set a default `direction`, and `route_overrides` can select an exception or use `"all"` for the combined alignment. Use station-specific headsigns to decide which direction to draw. Route 207 toward Downtown and 230 toward DFW were editorial choices for that example. [Maple transit controls](maple-transit-controls.md)

## Edit and preview in Blender

1. Keep one working `.blend` per production during review. Resize a label backing in Blender without scaling the separate text. For a leader-attached label, keep the tied edge fixed and recenter the text after moving the opposite edge. For route recoloring, edit the path's Emission color and update its badge material if they should match.
2. Use camera view and Rendered shading to check material fades. Scrub to the opening, a mid-fade frame, and a later shot. Frame Dropping can help judge playback timing on a slower viewport. Use Render Image to inspect a single frame at export quality.
3. Save visual edits in the working `.blend`. The builder regenerates the scene from JSON and cannot carry forward manual object edits. If a later rebuild is planned, record the finalized settings in the story config where supported.

## Render straight to MP4

In Blender 5.3, open Output Properties. Choose a filename and folder under Output, set Media Type to Video, and choose MPEG-4 and H.264 under Encoding. Leave File Extensions enabled. Check the frame range and frame rate, save the working project, then choose Render > Render Animation. Check the resulting MP4 in the selected folder. For an editable Resolve assembly, use the same render as an input clip.

## Place geographic titles

Map scenes and the walkshed share heading typography. Each stable shot compares
top-left and top-right title boxes against visible routes, labels, and other
map features available to that shot. A near tie keeps the preceding shot's
corner. A tie on the opening shot picks the top left. Long headings wrap to the
frame width. Subtitles are optional and move together with their headings.
