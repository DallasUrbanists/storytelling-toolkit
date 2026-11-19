# Agent instructions

## Mission and boundaries
Build reusable tools and templates for **QGIS → Blender → DaVinci Resolve Free**. Do not build a separate video editor, CMS, cloud database, or mandatory AI integration. Windows is the first supported platform. Blender owns geographic 2.5D animations; Resolve Free owns final editorial finishing.

## Permissions
The project owner authorizes feature branches, issues, PRs and merges into main after required checks. Do not force-push main. Ask for approval before repository security settings, credentials, paid purchases, or licensing decisions. Do not presume desktop application access from GitHub access.

## Small work packages
Keep issue scope to one independently testable capability (target 15–45 minutes). Reassess at 60 minutes; never enlarge acceptance criteria silently. Favor a working end-to-end example over scaffolding. Maintain docs and tests in each PR.

## Data quality
Never invent verified geography, demographic counts, roadway measurements, or current transit service. Synthetic fixtures must be labeled. Preserve projection, source, vintage and attribution. Building heights may be illustrative only when marked. Derived data must carry methodology and provenance.

## Project ownership
Source code and reusable templates are committed here. Individual productions belong outside this repository in Google Drive's Video Projects folder. Preserve relative media paths, close apps before syncing, and avoid simultaneous editing on two PCs. Caches and large intermediate renders remain local.

## Validation
Run syntax/static tests where possible. Only report a Blender render as completed after a real Blender invocation generates a verified artifact. Do not assume QGIS, Blender, or Resolve are installed on the agent host. Record blockers precisely.
