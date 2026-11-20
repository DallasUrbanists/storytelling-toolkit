# Day 4 roadway redesign

Build a dimensioned animated cross-section in Blender 5.3. The example geometry and all of its widths are illustrative. For Maple Avenue, the City's 2024 planning materials describe the four-to-three-lane proposal, one-way bike lanes on either side, and a center two-way left-turn lane. They do not establish surveyed dimensions for the cross-section depicted here. See the [City project page](https://dallascityhall.com/departments/transportation/Pages/Maple-Avenue-Safety-Project.aspx) and its linked, preliminary roll plot.

## Author a cross-section

1. Copy `examples/illustrative-roadway.json` into your production folder. Each section has a curb-to-curb total, left and right outside allocations, and a total right-of-way. They must add up. Write the elements in left-to-right order and give each an ID, zone, type, direction where applicable, and source.
2. Use `unit: "ft"` or `unit: "m"`. Leave a width null to share the unallocated width in its zone. Retain documented widths with `locked: true` and cite the relevant sheet and location. Known widths reserve their space first. The builder identifies derived widths on the object. All scene geometry is in meters.
3. Pair the two layouts in `mapping`. Each endpoint must use every element once in order. Null means an element collapses at that endpoint. The interpolated edges are shared by neighboring strips, so each frame preserves the allocated total and never opens gaps. Use physically meaningful mappings. Put a different material treatment in a separate slot if it should visibly appear or disappear.
4. Set hold, morph, reveal and closing durations in frames, and pick smooth or linear easing. Each orientation has a separate orthographic bearing, tilt, scale and optional target in local meters. Set `vehicles.existing` and `vehicles.proposed` to mappings from element IDs to `car`, `bus` or `bike`.

```powershell
blender -b --factory-startup --python-exit-code 1 --python blender/scripts/build_roadway.py -- --config examples/illustrative-roadway.json --format landscape --output scratch/roadway-landscape.blend
blender -b C:/Production/Maple_Day_3_portrait.blend --python-exit-code 1 --python blender/scripts/build_roadway.py -- --config C:/Production/maple-roadway.json --format portrait --output C:/Production/Maple_Day_4_portrait.blend
```

In the second command the tool retains the original scene and creates a separate **Roadway redesign** scene. To line it up with a real site, give `geography.origin` the same WGS 84 origin as Day 3, and provide two ordered `geography.centerline` coordinates on the local study centerline. The pair establishes the shot midpoint and orientation. `length_m` is the scene length. Keep the original project and use a new output file each time.

## Edit directly in Blender

1. Switch to **Roadway redesign** in the Scene selector, enter camera view, and scrub to the timeline markers. The Outliner groups the roadway, markings, camera, title objects, building massing, and vehicle curves.
2. Select **Section controls | dimensions in meters**. Each `existing edge NN` and `proposed edge NN` property is a shared edge. For a direct change to two adjacent lanes, move their common boundary without crossing another edge. Preserve locked segment widths and curb/ROW boundaries. Direct Blender edits bypass validation. Change the JSON and generate a new take for changes that need validation.
3. The controller's progress curve sets timing. Editable vehicle path curves set direction, and their Follow Path offset keys set speed. Edit camera transform and Orthographic Scale keys separately. Change title text in Edit Mode and materials in Material Properties.
4. The roadway scene starts with copies of nearby buildings evaluated at the final Day 3 pose. The Day 3 occlusion bake tests the actual road edges throughout the camera animation. Use the object's `visibility_override` for manual control and rebake after changing camera or geometry. For a clean edit, use hide mode. Fade mode retains translucent context.

## Render and edit

In Blender render the original geographic scene and the Roadway redesign scene separately. Use 1080 × 1920 for portrait or 1920 × 1080 for landscape at 30 fps. For long final renders, use PNG sequences in local scratch and turn them into editorial intermediates. Use matching full-frame title-safe layouts and inspect the start, midpoint and final roadway layouts in each composition before final editing.

Import both sets of shots into Resolve Free. Use two timelines at 30 fps, each with its own resolution. Motion in the geography shot can be segmented at the Dallas, Oak Lawn, Maple, and walking-catchment beats. Follow with the roadway motion and closing. Keep narration and captions editable. The media pool may need relinking to `04 Rendered Scenes` when a project transfers. Export the .drp alongside a text narration sheet and subtitle file. Preserve the QGIS project with its sibling GeoPackage. Keep render caches outside Drive and Git.

## Corridor variations

Use a segment register with WGS 84 start and end positions, configuration IDs, facility, buffer width when documented, turn treatments, bus stops, source, sheet reference and confidence. Use `roadway_model.validate_segments` to catch invalid or unreferenced records. Keep standard bike lanes, buffered examples and intersection transitions separate. For an illustrative treatment with no defensible project limits, keep the endpoints null. Keep citywide dated documents distinct from final engineering plans.

## Verification

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

The roadway-model tests cover lock and derivation metadata, width edits, invalid width and mapping rejection, and contiguous allocation at 101 progress samples. Use rendered visual QA for painted lines, titles, building occlusion and vehicle clearances.
