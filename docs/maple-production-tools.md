# Maple production tools

The standard story builder loads Maple when `style_preset` is omitted. Use `editorial_text: true` to add screen titles and editorial notes. Geographic labels, badges, callouts and attribution are part of the scene.

## Build from a clean Blender startup

Run these commands at the repository root with Blender 5.3. Use unused output paths to protect existing projects.

```powershell
blender -b --factory-startup --python-exit-code 1 -P blender/scripts/build_story.py -- --config examples/fresh-maple.json --format landscape --output scratch/dart.blend
blender -b --factory-startup --python-exit-code 1 -P blender/scripts/build_roadway.py -- --config examples/protected-roadway.json --format portrait --output scratch/protected.blend
```

Use `--format landscape` with a separate output path for the other roadway camera. The road example uses synthetic dimensions, traffic and crossing timings.

## Transit and callouts

To show DART rail, add a layer with `"kind": "route", "source": "dart-rail"`, choose an ID, and include that ID in a story step. The package contains Green, Orange, Red, Blue, Silver and TRE. The WGS84 centerlines come from DallasUrbanists/improvement-map. They include the shared downtown and north-of-downtown alignment fixtures and the TRE spine. The story builder offsets shared tracks for legibility.

`blender/presets/maple.json` supplies rail color, casing, weight, opacity and reveal. Override these on the layer or by service ID. Bus groups draw at one speed based on the shortest route taking 60 frames at 30 fps. Use `trace_stagger: 0` for simultaneous starts or `trace_stagger: 15` for Maple Avenue's half-second interval. Badges have bold type and a square minimum backing. The six-frame bus badge fade starts when drawing reaches the label anchor.

Set `"marker": "hospital"` on a point or layer to use the packaged black and white hospital graphic. Callout parents and leader trim keys give separate marker, leader and label controls. The label expands from the leader endpoint. Exits reverse the sequence over the first half of the transition. Entrance timings are independent.

## Roadway geometry and motion

The cross section and its transition can be authored with the **Section controls | dimensions in meters** object's custom properties. The meshes extend past both ends of the camera view and the slab uses the widest sidewalk's width for its thickness. The timeline markers identify arrow fade, old marking wipe, cross-section reallocation, new paint pass and arrow return.

In the starting configuration, set `driveway.width_m`, `driveway.radius_m` and `driveway_shifts_m` with keys such as `left:1` and `right:-1`. Generated curb and bike-marking openings follow those positions. Set `turn_arrows_at_driveways` for driveway-aligned arrows or supply `turn_arrow_pairs` with custom longitudinal centers. Arrow dimensions, pair spacing and opacity are in `blender/presets/dallas-roadway.json`. The center lane has solid yellow outside its broken yellow boundaries. A protected crossing uses `midblock_crossing.center_m` and `refuge_width_m` and separate signed yield windows. After building, the parts and path splines are native editable objects. When moving a crossing by hand, also move its path and paint openings, or set its center in the starting configuration to regenerate aligned geometry.

The roadway builder registers the motor vehicles, bike and scooter models, pedestrian, rollator and wheelchair user as **Current File** assets. Assign a different model by replacing the mesh child on its path-following parent. The config examples demonstrate timing recipes. For a staged protected-crossing user, edit **Speed m/s**, **Arrival seconds**, **Driveway wait seconds**, **Yield at crossing** or **Yield windows seconds** in Custom Properties. Arrival is measured at the path's cue anchor. Yield windows are JSON keyed by travel direction, in seconds from the proposed phase. In Blender's Python Console, with the actor parent selected, apply the timing to its editable Follow Path curve.

```python
import sys
sys.path.insert(0, r"C:/path/to/storytelling-toolkit/blender/scripts")
from protected_simulation import retime_motion
retime_motion(bpy.context.object)
```

Retime after changing a curve. Check new swept footprints with `traffic_checks.footprint_gaps` after editing paths, dimensions or assignments. It returns a signed overlap clearance and a same-lane following gap. The preset does not compute a new multi-actor traffic schedule after a change. The demo stages turn, following stop, independent traffic-direction yielding, and a two-stage wheelchair crossing. Existing-phase vehicles have editable timed path keys and driveway/through trajectory functions in `traffic_paths.py`.

## Reproduce the checks

Use `tests/validate_fresh_maple.py` on the generated DART story, and `tests/validate_roadway_blender.py` followed by `tests/validate_fresh_traffic.py` on each generated roadway orientation. Run these through Blender background mode with `--python-exit-code 1`. No Maple production file is needed by these examples. The production's traffic counts, shot timing, individual cues, camera choices and editorial cuts remain with the production.
