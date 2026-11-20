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
- **Timing.** The sample settles by frame 191 and plays to frame 350 at 30 fps. Timeline markers flag contact and the start of the hold. After shifting a contact, move the corresponding motion, deformation and smoke keys together. The marker is a reference for the edit.
