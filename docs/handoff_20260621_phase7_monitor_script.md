# SoundBank Standalone Handoff - Phase 7 Render Log Watch Script

Date: 2026-06-21

## Result

The standalone SoundBank repository now has its own Render raw log watch script.
It no longer needs to borrow the legacy `11STARS` repository script for daily
monitoring.

- Script: `scripts/production_render_log_watch.py`
- Default Render service: `11stars-soundbank`
- Default service ID: `srv-d8rjsk0js32c73c4uhpg`
- Mode: read-only
- Secrets: loaded from local/private environment only, never printed

## How To Run

Use a private local secret store or a system environment variable for
`RENDER_API_KEY`.

```powershell
python scripts\production_render_log_watch.py --hours 1
```

The script checks:

- error-level logs
- HTTP 5xx logs
- Traceback logs
- Exception logs
- CheckMac logs
- ECPay-related HTTP 5xx samples

## Verification

Run on 2026-06-21:

- `python -m py_compile scripts\production_render_log_watch.py`: passed
- `scripts\production_render_log_watch.py --hours 1`: 7 passes, 0 warnings, 0 failures
- `.\scripts\verify_standalone.ps1`: passed

Raw log watch window:

- `2026-06-21T03:47:16Z` to `2026-06-21T04:47:16Z`

Counts:

- error-level logs: 0
- HTTP 5xx logs: 0
- Traceback logs: 0
- Exception logs: 0
- CheckMac logs: 0
- ECPay-related log matches fetched: 0
- ECPay-related HTTP 5xx samples: 0

## Notes

The script can monitor another Render resource by overriding `RENDER_OWNER_ID`
and `RENDER_SERVICE_ID`. Do not commit API keys or private Render data.
