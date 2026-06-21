# Phase 4 - Publication Prep

Date: 2026-06-21

## Result

The standalone SoundBank project has been published to GitHub and deployed to a
separate Render web service.

- GitHub repository: `https://github.com/fishxit777/11STARS-SoundBank`
- Render service: `11stars-soundbank`
- Public URL: `https://one1stars-soundbank.onrender.com`
- First live deploy commit: `a500cf160e5d00dba57922c7065ce6cc945d7c92`

This deployment did not overwrite the existing WanyuTong / 11STARS production
service.

## Publish Path Used

The user created an empty GitHub repository:

```text
https://github.com/fishxit777/11STARS-SoundBank
```

The local standalone repo was pushed to that remote with:

```powershell
cd "C:\Users\bao58\OneDrive\文件\New project\萬語聲庫_SoundBank"
.\scripts\publish_to_github.ps1 -RemoteUrl "https://github.com/fishxit777/11STARS-SoundBank.git"
```

## Render Path Used

The service was created directly through the Render API because a valid local
Render API key was available. The checked-in `render.yaml` is aligned with the
service name and public URL for future reproducible deployment.

The service currently runs in safe starter-demo mode:

- browsing and preview pages are enabled;
- fake checkout is disabled;
- master files are not public;
- database-backed sales are not enabled yet.

## Secrets Still Needed For Full Production Sales

Add these in Render only, never in GitHub:

- `DATABASE_URL`
- `ADMIN_TOKEN`
- `SOUNDBANK_SIGNING_SECRET`
- `SOUNDBANK_PAYMENT_WEBHOOK_SECRET`
- `SOUNDBANK_ECPAY_MERCHANT_ID`
- `SOUNDBANK_ECPAY_HASH_KEY`
- `SOUNDBANK_ECPAY_HASH_IV`
- `SOUNDBANK_OBJECT_STORAGE_ENDPOINT`
- `SOUNDBANK_OBJECT_STORAGE_BUCKET`
- `SOUNDBANK_OBJECT_STORAGE_ACCESS_KEY`
- `SOUNDBANK_OBJECT_STORAGE_SECRET_KEY`

## Verification Completed

Online checks:

```text
https://one1stars-soundbank.onrender.com/healthz
https://one1stars-soundbank.onrender.com/soundbank
https://one1stars-soundbank.onrender.com/soundbank/tracks
https://one1stars-soundbank.onrender.com/soundbank.webmanifest
```

Expected current health mode:

```json
{"ok":true,"service":"soundbank-standalone","database_configured":false,"mode":"starter-demo"}
```

## Rollback

Until DNS is changed, this standalone deployment has no customer-facing effect
on the existing WanyuTong / 11STARS production service.

If needed, suspend or delete only the standalone Render service. Keep the
existing production service untouched.
