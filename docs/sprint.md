# Four-day implementation sprint

Dates are **milestone labels**, not fixed commitments. The actual calendar should be scheduled at execution time. Goal: a first Maple Avenue explainer, with source-backed geography and editable native scenes.

| Day | Objective | Completion gate |
| --- | --- | --- |
| **1 — Foundation** | Bootstrap this repo; document Windows setup; export QGIS GeoJSON; build an editable Blender geography scene with orthographic camera, boundary draw-on and a label; validate a render | A real imported polygon is editable in Blender and a PNG animation frame can be rendered from a deterministic command |
| **2 — Storytelling** | Generic sequence of geographic focus levels; map raster/imagery background; leader-line callouts; rail/bus paths; persistent layers; portrait/landscape camera presets | Dallas → Oak Lawn → Maple corridor sequence is editable and renders in both formats |
| **3 — Research & 2.5D** | QGIS walkshed workflow, Census estimation with provenance, transit/zoning imports; building footprints to massing; foreground object fading/hiding | Verified study-area assets and an isometric city scene; obstructing buildings can be suppressed |
| **4 — Roadway & finish** | Dimension-aware 4→3 roadway cross-section, buffered/unbuffered treatments, moving low-poly vehicles, scene render handoff to Resolve Free, dual-format final editing | Maple explainer with roadway transformation, editable QGIS/.blend/Resolve files, video exports, source manifest |

## Critical-path priorities
1. Test actual render with correct geometry; don't continue building on a broken pipeline.
2. Use real, verified geographic source files for publication; synthetic inputs are for engineering tests only.
3. Preserve source files and human edits; regenerated geometry must not silently overwrite creative adjustments.
4. Defer generalized plugin UI, automatic citywide ingestion, and fully autonomous editing if the Maple reference production is at risk.

## Proposed per-project files
Google Drive for desktop / Dallas Urbanists / Video Projects / Maple Avenue Safety:
- `01 Geography & Research/`: QGIS .qgz, GeoPackage, approved statistics, source manifest.
- `02 Animation/`: native .blend scenes, linked assets.
- `03 Video Editing/`: Resolve .drp snapshots, narration, audio.
- `04 Rendered Scenes/`: delivery shots (not scratch caches).
- `05 Final Exports/`: portrait and landscape videos.

Use one active editing computer. Wait for Drive sync before switching devices. Keep transient frame sequences outside Drive.
