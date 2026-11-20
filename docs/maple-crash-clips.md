# Maple crash clip technical sample

The sample uses synthetic coordinates in metres and an editable Maple road cross-section. Shot-specific art direction and final media live in the production workspace.

Run from the toolkit root with Blender 5.3. Use fresh output names.

```powershell
blender -b --factory-startup --python-exit-code 1 -P blender/scripts/build_crash_clip.py -- --config examples/m03-rear-end.json --format portrait --output scratch/m03-portrait.blend --preview scratch/m03-portrait.mp4
```

Repeat with `--format landscape` and distinct output names. The preview is 25% render size at 10 fps, with the same running time as the 30 fps scene.

- **Approach and hold.** Edit the Motion keys on each actor parent in the Dope Sheet. In the config, a pose is `[frame, x, y, z, bearing_degrees, tilt_degrees]`. Forward along the street is local +Y, and positive bearing turns toward +X.
- **Impact.** The sample's front-to-rear contact is at frame 150. The selected bumper surfaces get local shape keys. The smoke blocks have separate position and scale keys.
- **Camera.** Change the active camera's transform or orthographic scale. The config has separate portrait and landscape framing sections.
- **Timing.** The sample settles by frame 191 and plays to frame 350 at 30 fps. Timeline markers flag contact and the start of the hold. Use the native timing workflow below when revising contact timing.

## Native verification and clean export

In a generated scene, **Actors | editable motion** contains the actor parents. Edit their Motion keys directly. Alternatively use an actor's `motion` object with a six-value `start` pose and timed `segments`. Segment kinds are `move`, `hold`, `curve` (two XY control points), and `lane-change`. A move can use `ease: out` to brake or `reverse: true` to face along the opposite direction of travel. Combine curves and holds to approach a driveway, wait, cross in two stages, or pass and rejoin a lane. The segments set the performance, including the lengths of stops.

Each contact names both actors and their local `front`, `rear`, `left` or `right` surface. Multiple contacts can name the same pedestrian. Once impacted, the figure switches to straight overhead arms and follows the whole-body translation and tilt keys. A rollator remains at the first impact location. Edit the localized vehicle shape keys and individual smoke blocks in Blender.

When changing contact timing, edit both actors' motion and move the numbered **Contact** marker to the revised frame. Select Python Console and run:

```python
import sys
sys.path.insert(0, r"C:/path/to/storytelling-toolkit/blender/scripts")
from crash_review import sync_impacts
sync_impacts()
```

The command verifies the surfaces meet, then moves the crumple, rigid-pose and smoke keys. Move **Settled | final hold** to the last movement or smoke disappearance and leave at least 150 subsequent frames with a stationary camera. The validation checks the native scene after such edits.

```powershell
blender -b scratch/m03-portrait.blend --python-exit-code 1 -P blender/scripts/crash_review.py -- --stills scratch/m03-stills --frames 145 150 160 191 350
blender -b scratch/m03-portrait.blend --python-exit-code 1 -P blender/scripts/crash_review.py -- --clean scratch/M03-before-portrait.mp4
python tools/verify_crash_export.py scratch/M03-before-portrait.mp4 --orientation portrait --frames 350
```

Use `--preview` instead of `--clean` for a low-resolution preview of an edited scene. Scrub in Camera View to see ordinary Blender motion keys; the MP4 preview uses 10 fps for faster iteration. Compare corresponding frames from two still folders side by side, such as `ffmpeg -i before/frame-0150.png -i after/frame-0150.png -filter_complex hstack review.png`. Clean exports are 30 fps and keep the native dimensions of the selected camera.

The test fixtures `tests/fixtures/crash-double-contact.json`, `crash-driver-view.json`, `crash-refuge-clearance.json`, and `crash-reversing.json` use synthetic positions. In the driver test, the configured inside-lane screen must block five target samples from the driver eye, while the audience camera must retain sight of the oncoming car. The refuge check tests actor footprints against both island noses. Before approving a production clip, still review the framing, actor entrances and sightlines in both orientations.

The 15-clip plan in `examples/maple-crash-manifest.json` specifies 30 output variants. Use the selected shot ID and orientation in clean output names. Pair approval and delivery records with the corresponding variant. The production's shot-specific motions and final outputs follow creative approval.

The city diagrams supply editorial references for sight obstruction, midblock conflicts and emergency clearance. [City of Dallas Maple Avenue FAQ, Figures 5, 6 and 9](https://dallascityhall.com/departments/transportation/Documents/Vision%20Zero/Maple%20Avenue/FAQ_Maple-Ave_11192024.pdf)
