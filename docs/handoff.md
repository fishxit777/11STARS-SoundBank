# SoundBank Standalone Handoff

Updated: 2026-06-21

## Current State

SoundBank has been extracted into an independent local project and published to
its own GitHub repository.

- Local project: `C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS-SoundBank`
- GitHub repository: `https://github.com/fishxit777/11STARS-SoundBank`
- Render service: `11stars-soundbank`
- Public URL: `https://one1stars-soundbank.onrender.com`
- Current mode: starter-demo catalog mode
- Latest copy source: `C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS`
- Latest verified source commit: `428f554`

The original WanyuTong / 11STARS production service was not overwritten. The
standalone Render service is separate from the existing LINE Bot backend.

## What Is Live

- `/healthz` returns 200.
- `/soundbank` returns 200.
- `/soundbank/tracks` returns 200.
- `/soundbank.webmanifest` returns 200.
- Public demo assets are included.
- Master files are not publicly stored in the repository.

## Safety Defaults

The standalone service currently uses safe launch defaults:

- `SOUNDBANK_ENABLED=true`
- `SOUNDBANK_SHOW_STARTER_DEMOS=true`
- `SOUNDBANK_INIT_DB=false`
- `SOUNDBANK_SEED_BETA_ORIGINALS=false`
- `SOUNDBANK_FAKE_CHECKOUT_ENABLED=false`
- `SOUNDBANK_ALLOW_PUBLIC_MASTER_URLS=false`

These settings allow browsing and preview checks without exposing private master
files or enabling fake checkout.

## Still Needed For Full Production Sales

Before the standalone site accepts real standalone orders, configure these in
Render only, never in GitHub:

- `DATABASE_URL`
- `ADMIN_TOKEN`
- `SOUNDBANK_SIGNING_SECRET`
- `SOUNDBANK_PAYMENT_WEBHOOK_SECRET`
- ECPay merchant credentials
- R2 or S3 object-storage credentials

After secrets are configured, run a paid-order test, download-token test,
refund/void replay test, and email-abnormal check before public promotion.

## Rollback

No DNS has been cut over yet, so rollback is simple:

1. Keep using the existing WanyuTong SoundBank URL.
2. Suspend or delete the standalone Render service if needed.
3. GitHub history can restore the standalone repo to any previous commit.

## Verification

Run locally:

```powershell
cd "C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS-SoundBank"
.\scripts\verify_standalone.ps1
git status -sb
```

Check online:

```text
https://one1stars-soundbank.onrender.com/healthz
https://one1stars-soundbank.onrender.com/soundbank
https://one1stars-soundbank.onrender.com/soundbank/tracks
```
