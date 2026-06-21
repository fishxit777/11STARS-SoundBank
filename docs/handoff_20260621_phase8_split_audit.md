# SoundBank Split Audit

Updated: 2026-06-21 Asia/Taipei

## Purpose

Confirm the boundary between the original `11STARS` repository and the new
standalone `11STARS-SoundBank` repository after the standalone GitHub repo and
Render service were created.

No files were deleted from the original `11STARS` repository during this audit.

## Current Source Of Truth

- Active SoundBank repo:
  `C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS-SoundBank`
- GitHub:
  `https://github.com/fishxit777/11STARS-SoundBank`
- Render service:
  `11stars-soundbank`
- Public URL:
  `https://one1stars-soundbank.onrender.com`
- Current standalone commit before this audit:
  `0401efc Add standalone Render log watch`
- Original `11STARS` commit used as comparison baseline:
  `428f554 Document 2026-06-21 SoundBank monitor sweep (#169)`

The original `C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS`
repository remains active for WanyuTong / LINE bot work. Its SoundBank files
should now be treated as legacy rollback/reference material, not as the main
SoundBank development line.

## File And Asset Findings

### Backend module

- Original module:
  `C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS\soundbank.py`
- Standalone module:
  `C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS-SoundBank\src\soundbank.py`
- SHA-256 differs, which is expected because newer SoundBank UI/copy/layout
  work continued in the standalone repo after extraction.

### Public assets

Asset counts from the audit:

- Original `11STARS/static/soundbank_assets`: 89 files
- Standalone `11STARS-SoundBank/static/soundbank_assets`: 61 files
- Files present in both: 61
- Files missing from standalone: 28
- Missing files that are master WAVs: 28
- Missing non-master files: 0
- Extra files in standalone: 0

Conclusion: the standalone public repo intentionally excludes all master WAV
files. Preview WAVs, rights TXT files, and SoundBank images are present in the
standalone repo. This is the desired public-repo boundary.

### Scripts and documents

- Original `11STARS` still contains 29 SoundBank-specific scripts and 45
  SoundBank-related docs.
- Standalone `11STARS-SoundBank` contains 7 focused scripts and 14 focused docs.
- The standalone repo keeps only the scripts/docs needed for standalone
  verification, publishing, Render log watch, and migration handoff.

## Risks Found

1. The standalone `README.md` still said formal traffic was in `11STARS`.
   This was stale after the standalone Render service and GitHub repo became
   the working SoundBank source.
2. `scripts/sync_from_11stars.ps1` could overwrite the newer standalone
   `src/soundbank.py` from the older `11STARS/soundbank.py` if run casually.
3. The original `11STARS` repo still tracks SoundBank master WAV files. They
   were intentionally not copied to the standalone repo. Do not promote the old
   repo as the customer-facing SoundBank source.
4. Some old `11STARS` docs still point to legacy SoundBank URLs and launch
   notes. They are useful as history only.

## Actions Taken

- Updated standalone `README.md` to state that `11STARS-SoundBank` is now the
  SoundBank source of truth.
- Guarded `scripts/sync_from_11stars.ps1` so it stops by default and requires
  `-ConfirmLegacySourceSync` before it can copy old files into the new repo.
- Documented the legacy sync guard in `scripts/README.md`.
- Added this split-audit handoff.

## Do Not Do Automatically

- Do not delete SoundBank files from the original `11STARS` repo yet.
- Do not move or expose master WAVs through GitHub.
- Do not change ECPay callbacks, DNS, R2 bucket policy, or database routing
  without a separate cutover checklist and rollback plan.

## Recommended Next Step

Run standalone verification, commit this audit, push to GitHub, then let Render
auto-deploy the documentation/script guard update. After that, run the production
health check and Render raw-log watch once more.
