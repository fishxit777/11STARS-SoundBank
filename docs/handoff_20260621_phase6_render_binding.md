# SoundBank Standalone Handoff - Phase 6 Render Binding

Date: 2026-06-21

## Result

The standalone production/demo Render service is now confirmed to be connected
to the new standalone GitHub repository.

- Render service: `11stars-soundbank`
- Service ID: `srv-d8rjsk0js32c73c4uhpg`
- Repository: `https://github.com/fishxit777/11STARS-SoundBank`
- Branch: `main`
- Auto-deploy: `yes`
- Region: Oregon
- Plan: Free
- Public URL: `https://one1stars-soundbank.onrender.com`

This means the live standalone SoundBank service is no longer deploying from
the old `fishxit777/11STARS` repository.

## Latest Deploy

- Deploy ID: `dep-d8rmibgjs32c73fvdl00`
- Status: `live`
- Trigger: `new_commit`
- Commit: `b6195ce88073cbeb6f6c4367e53c4b86b2dae9ac`
- Commit message: `Document Render binding for standalone SoundBank`
- Updated: `2026-06-21T04:32:35Z`

## Online Check

Checked after the deploy:

- `https://one1stars-soundbank.onrender.com/healthz` returned 200.
- `https://one1stars-soundbank.onrender.com/soundbank` returned 200.
- `https://one1stars-soundbank.onrender.com/soundbank/tracks` returned 200.
- `https://one1stars-soundbank.onrender.com/soundbank/license` returned 200.
- `https://one1stars-soundbank.onrender.com/soundbank.webmanifest` returned 200.
- `https://one1stars-soundbank.onrender.com/soundbank-sw.js` returned 200.

## Render Raw Log Watch

Using the owner-private Render API key from the local no-upload secret store,
the one-hour raw log watch passed:

- Error-level logs: 0
- HTTP 5xx logs: 0
- Traceback logs: 0
- Exception logs: 0
- CheckMac logs: 0
- ECPay-related HTTP 5xx samples: 0
- Summary: 7 passes, 0 warnings, 0 failures

## Legacy Staging Note

The old `11stars-soundbank-staging` Render service still points to:

- Repository: `https://github.com/fishxit777/11STARS`
- Branch: `feature/soundbank-mvp`
- Auto-deploy: `no`
- Plan: Free

Do not treat that staging service as the current production source of truth. It
can be kept as a temporary rollback/reference service, or retired after the
standalone service is fully promoted.

## Public Promotion Limitation

The standalone service is still on Render Free. This causes two public launch
limitations:

- It can show a cold-start/loading screen after inactivity.
- It cannot use a custom domain while it remains on the Free plan.

Before serious public promotion, upgrade the standalone service plan and then
configure the official SoundBank subdomain.
