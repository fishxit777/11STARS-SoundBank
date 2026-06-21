# Phase 4 - Publication Prep

Date: 2026-06-21

## Result

The standalone SoundBank project is locally ready for GitHub and Render
publication, but the external GitHub repository does not exist yet.

The GitHub connector currently exposed file and pull-request tools for existing
repositories, but not a create-repository tool. The local machine also does not
have `gh` or `render` CLI installed, so repository creation and Render Blueprint
creation cannot be completed fully from the terminal yet.

## Safe Publish Path

Recommended repository name:

```text
11STARS-SoundBank
```

Reason:

- It keeps SoundBank separate from `11STARS`.
- It avoids overwriting the current WanyuTong/LINE Bot repository.
- It is still recognizable as part of the 11STARS product family.

Manual one-time action:

1. Open GitHub new repository page:

```text
https://github.com/new
```

2. Create an empty repository named:

```text
11STARS-SoundBank
```

3. Do not add README, .gitignore, or license in GitHub. This local project
   already has those files.

4. After the repo exists, run:

```powershell
cd "C:\Users\bao58\OneDrive\文件\New project\萬語聲庫_SoundBank"
.\scripts\publish_to_github.ps1 -RemoteUrl "https://github.com/fishxit777/11STARS-SoundBank.git"
```

## Render Path After GitHub Exists

Use Render Blueprint after the GitHub repo is pushed:

```text
https://dashboard.render.com/blueprint/new
```

Select the new `fishxit777/11STARS-SoundBank` repository and use the checked-in
`render.yaml`.

Required Render secrets must be added in the dashboard. Do not commit them:

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

## Rollback

Until DNS is changed, this phase has no customer-facing effect.

If GitHub publishing fails, remove the wrong remote and retry:

```powershell
git remote remove origin
```

If Render deployment fails, keep the existing production service untouched and
fix the standalone service separately.

## Verification Commands

```powershell
cd "C:\Users\bao58\OneDrive\文件\New project\萬語聲庫_SoundBank"
.\scripts\verify_standalone.ps1
git status -sb
```
