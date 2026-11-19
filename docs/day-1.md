# Day 1 runbook — QGIS-to-Blender foundation

## Audience
Windows operator or coding agent. This is a proof of concept, not a polished video editor.

## Prerequisites
1. Install **QGIS 3.44 LTR** (stable plugin ecosystem) from https://qgis.org/download/.
2. Install Blender from https://www.blender.org/download/.
3. Clone `https://github.com/DallasUrbanists/storytelling-toolkit.git`.
4. Create a working folder for video projects outside the repository (prefer a Google Drive mirrored/offline-available folder). Do not sync transient render caches.

## Manual QGIS exercise
1. Open QGIS and create a new project.
2. Import a **verified** polygon GeoJSON, or create a temporary polygon layer and draw an illustrative boundary.
3. Assign/save the layer in EPSG:4326 (WGS84) and use **Export → Save Features As → GeoJSON**. Reproject during export if necessary. Include source and vintage metadata separately.
4. For Day 1 only, use `tests/fixtures/illustrative-neighborhood.geojson` if authoritative source data are not prepared.
5. Save the QGIS project in the video-project geography folder.

## Blender exercise
Open a terminal in the repository, run (adjust Blender executable path as needed):

```powershell
blender --background --python blender/scripts/import_geography.py -- --geojson tests/fixtures/illustrative-neighborhood.geojson --output illustrative-neighborhood.blend --name "Illustrative Neighborhood"
```

Open the generated `.blend` file and inspect: boundary curve, label, camera, keyed boundary reveal. Manually move the label or adjust keyframes, save, and reopen.

To validate an individual render frame:

```powershell
blender --background illustrative-neighborhood.blend -o //test-frame-##### -f 60
```

Blender treats `-f` and `-a` as terminal render commands. Use a separate command for a full sequence (`-a`).

## Acceptance criteria
- GeoJSON input is parsed; malformed or unsupported geometry raises a clear error.
- At least one polygon is represented as native editable Blender curves.
- Boundary reveal is keyframed; camera is orthographic; text label is a native text object.
- The generated `.blend` is saved at the requested path.
- A frame is genuinely rendered and visually inspected on a Windows machine with Blender installed.
- Documentation records projection assumptions and synthetic fixture limitations.

## Stop/go
If installed Blender cannot load or render the scene, fix that before Day 2. If QGIS isn't available, run the fixture import but mark QGIS integration unvalidated. Do not claim Day 1 is complete on source-only evidence.
