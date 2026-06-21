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

- Deploy ID: `dep-d8rm35naqgkc73bl48jg`
- Status: `live`
- Trigger: `new_commit`
- Commit: `55869f30ee93548242d2373c8f885aa54a44cb99`
- Commit message: `Document standalone SoundBank sync verification`
- Created: `2026-06-21T03:59:18Z`
- Updated: `2026-06-21T04:22:58Z`

## Online Check

Checked after the deploy:

- `https://one1stars-soundbank.onrender.com/healthz` returned 200.
- `https://one1stars-soundbank.onrender.com/soundbank` returned 200.
- `https://one1stars-soundbank.onrender.com/soundbank/tracks` returned 200.

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
