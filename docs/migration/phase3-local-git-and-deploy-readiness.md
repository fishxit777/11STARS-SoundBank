# Phase 3 - Local Git And Deploy Readiness

Date: 2026-06-21

## Completed

- Initialized `萬語聲庫_SoundBank` as its own local Git repository.
- Created the first local restore point:
  - Commit: `be451af Initialize standalone SoundBank project`
  - Branch: `main`
- Confirmed `萬語通\11STARS` remained clean after the standalone work.
- Updated `render.yaml` to start the app from the `src` folder:
  - `gunicorn --chdir src app:app`
- Added placeholder-only deployment environment variables for:
  - Dedicated database URL.
  - Admin token.
  - SoundBank signing and payment webhook secrets.
  - ECPay merchant credentials.
  - R2/S3-compatible object storage credentials.

## Not Done Yet

- No GitHub remote repository was created.
- No Render standalone service was created.
- No DNS or custom domain was changed.
- No live ECPay callback URL was changed.
- No production database was copied.

## Next Deployment Split

1. Create or select a dedicated GitHub repository for SoundBank.
2. Push this local `main` branch to that repository.
3. Create a new Render web service from the SoundBank repository.
4. Add a dedicated database or explicitly wire an isolated existing database.
5. Add ECPay and object-storage secrets in Render environment variables.
6. Update ECPay callback URLs only after staging checkout is verified.

## User Verification Trigger

User verification is needed only when creating/selecting the public GitHub
repository, creating a Render service through the logged-in dashboard, or
changing ECPay production callback URLs.
