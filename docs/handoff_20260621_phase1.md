# SoundBank Phase 1 Handoff - Standalone Skeleton

Updated: 2026-06-21

## Status

Phase 1 is complete. This folder now has a copy-only standalone SoundBank
skeleton that can load the public SoundBank pages without touching the
WanyuTong production service.

## Created Files

- `src/app.py`: standalone Flask entrypoint.
- `src/soundbank.py`: copied SoundBank feature module from `萬語通\11STARS`.
- `static/soundbank_assets`: public preview assets only.
- `requirements.txt`: minimal runtime dependencies.
- `.env.example`: non-secret environment template.
- `render.yaml`: placeholder Render blueprint for a future standalone service.

## Safety Decisions

- No production database is connected by default.
- `SOUNDBANK_INIT_DB=false` by default.
- `SOUNDBANK_SHOW_STARTER_DEMOS=true` lets public pages render without DB.
- `SOUNDBANK_ALLOW_PUBLIC_MASTER_URLS=false` by default.
- Master WAV files were intentionally not copied.
- Payment remains disabled unless standalone ECPay variables are explicitly set.

## Verification

- `python -m py_compile src\app.py src\soundbank.py`: passed.
- Flask test client returned 200 for:
  - `/healthz`
  - `/`
  - `/soundbank`
  - `/soundbank/tracks`
  - `/soundbank/license`
  - `/soundbank.webmanifest`
  - `/soundbank-sw.js`
- Public asset copy contains:
  - 5 images
  - 28 preview WAV files
  - 28 rights text files
  - 0 master WAV files
- Secret pattern scan found no common API token patterns.

## Known Boundary

`萬語通\11STARS\soundbank.py` currently has a working-tree change outside this
new folder. It appears to be SoundBank public copy/title refinement work. The
standalone skeleton was synced from the current visible file, but the original
repo change was not reverted, committed, or pushed in this phase.

## Next Step

Phase 2 should create a true independent runtime boundary:

1. Decide whether the standalone repo keeps copying `soundbank.py` temporarily
   or starts extracting shared helpers.
2. Add a dedicated SoundBank staging database.
3. Run schema initialization only against that isolated database.
4. Re-test checkout, signed downloads, certificates, verification pages, and
   admin monitor routes with standalone environment variables.
