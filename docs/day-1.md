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
3. Assign/save the layer in EPSG:4326 (WGS84) and use **Layer → Save As…** or right-click the layer and choose **Export → Save Features As…**. Set format to **GeoJSON** and CRS to **EPSG:4326 – WGS 84**. Reproject during export if necessary. Include source and vintage metadata separately.
4. For Day 1 only, use `tests/fixtures/illustrative-neighborhood.geojson` if authoritative source data are not prepared.
5. Save the QGIS project in the video-project geography folder.

## Blender exercise
Open a terminal in the repository, run (adjust Blender executable path as needed):

```powershell
blender --background --factory-startup --python-exit-code 1 --python blender/scripts/import_geography.py -- --geojson tests/fixtures/illustrative-neighborhood.geojson --output illustrative-neighborhood.blend --name "Illustrative Neighborhood (Synthetic)"
```

Open the generated `.blend` file and inspect: boundary curve, label, camera, keyed boundary reveal. Scrub the Timeline to frame 25 for a partial outline with no label and to frame 60 for the full outline and label. In the Outliner, select the boundary and move the pointer over the 3D Viewport before pressing **Tab** to inspect its editable control points. The importer uses a local equirectangular approximation in meters for compact study areas and draws exterior rings only.

To validate an individual render frame:

```powershell
blender --background illustrative-neighborhood.blend -o //test-frame-#### -f 25,60
blender --background illustrative-neighborhood.blend --python-exit-code 1 --python tests/validate_blender_scene.py -- test-frame-0025.png test-frame-0060.png
```

Run the same import, render, and validation for the QGIS-exported file. Open both frame-60 PNGs to check framing and legibility. The PNGs have a transparent background for compositing. Blender treats `-f` and `-a` as terminal render commands. Use a separate command for a full sequence (`-a`).

## Acceptance criteria
- GeoJSON input is parsed; malformed or unsupported geometry raises a clear error.
- At least one polygon is represented as native editable Blender curves.
- Boundary reveal is keyframed; camera is orthographic; text label is a native text object.
- The generated `.blend` is saved at the requested path.
- A frame is genuinely rendered and visually inspected on a Windows machine with Blender installed.
- Documentation records projection assumptions and synthetic fixture limitations.

## Stop/go
If installed Blender cannot load or render the scene, fix that before Day 2. If QGIS isn't available, run the fixture import but mark QGIS integration unvalidated. Do not claim Day 1 is complete on source-only evidence.
