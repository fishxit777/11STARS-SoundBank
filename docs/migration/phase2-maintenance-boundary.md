# Phase 2 - Maintenance Boundary

Date: 2026-06-21

This standalone SoundBank folder now has repeatable local scripts instead of
depending on manual file copying.

## Scripts

- `scripts/sync_from_11stars.ps1`
  - Copies the current `soundbank.py` implementation from `萬語通\11STARS`.
  - Copies public SoundBank assets only: artwork, preview WAV files, and rights
    TXT summaries.
  - Blocks public master WAV files.
  - Runs the standalone verification script after syncing.

- `scripts/verify_standalone.ps1`
  - Runs Python compile checks.
  - Runs Flask test-client checks for the standalone routes.
  - Confirms public assets do not include master WAV files.
  - Scans for common secret-like token patterns without printing secret matches.

- `scripts/run_local.ps1`
  - Starts the standalone Flask app with safe local defaults.
  - Uses `/soundbank` as the primary local entry point.
  - Keeps public master URLs disabled by default.

## Safe Local Flow

```powershell
cd "C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS-SoundBank"
.\scripts\sync_from_11stars.ps1
.\scripts\verify_standalone.ps1
.\scripts\run_local.ps1
```

## Boundary Rule

The standalone project may reuse SoundBank code and public preview assets from
`11STARS`, but it must not publish private master files, dashboard secrets,
payment keys, database URLs, or customer data.

Production cutover is still separate from this phase. Before using a standalone
Render service, create independent environment variables and confirm payment
callback URLs.
