# SoundBank Standalone Handoff - Phase 2

Date: 2026-06-21

## Completed

- Added repeatable maintenance scripts for the standalone SoundBank folder.
- Added a sync script that locates `11STARS\soundbank.py` without hard-coded
  Chinese path literals, avoiding PowerShell encoding issues.
- Added standalone verification that checks:
  - Python compilation.
  - Main SoundBank routes.
  - Public asset counts.
  - No public master WAV files.
  - No common secret-like token patterns.
- Added local run helper with safe SoundBank defaults.
- Added maintenance-boundary documentation.

## Verified

Command:

```powershell
cd "C:\Users\bao58\OneDrive\文件\New project\萬語聲庫_SoundBank"
.\scripts\sync_from_11stars.ps1
```

Result:

- Source root: `C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS`
- Images: 5
- Preview WAV: 28
- Rights TXT: 28
- Master WAV: 0
- `/healthz`: 200
- `/soundbank`: 200
- `/soundbank/tracks`: 200
- `/soundbank/license`: 200
- `/soundbank.webmanifest`: 200
- `/soundbank-sw.js`: 200
- Common token pattern scan: pass

## Boundary

No source repo files were changed by this phase. The standalone folder now has
its own repeatable local maintenance flow, but it is not yet an independent
GitHub repository or Render service.

## Next Recommended Step

Phase 3: initialize the standalone project as its own Git repository, then
prepare a dedicated deployment plan for a separate Render service and callback
URLs.
