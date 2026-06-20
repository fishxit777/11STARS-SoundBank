# SoundBank Source Map

更新日期：2026-06-21

## Source Of Truth

目前正式 source of truth：

`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS`

正式線上 URL：

`https://one1stars-line-bot.onrender.com/soundbank`

## 核心程式

| 類型 | 目前位置 | 移轉目標 |
| --- | --- | --- |
| Flask SoundBank module | `萬語通\11STARS\soundbank.py` | `萬語聲庫_SoundBank\src\soundbank.py` |
| Flask app 掛載 | `萬語通\11STARS\app.py` | 新增獨立 `src\app.py` |
| Render staging blueprint | `萬語通\11STARS\render.soundbank.staging.yaml` | 新增獨立 `render.yaml` 或 `render.soundbank.yaml` |
| requirements | `萬語通\11STARS\requirements.txt` | 獨立 requirements，只保留 SoundBank 必要套件 |

`app.py` 目前在檔尾匯入並掛載：

- `init_soundbank_db`
- `register_soundbank_routes`
- `seed_soundbank_beta_originals`
- `soundbank_should_initialize`
- `soundbank_should_seed_beta_originals`

## 資料表

SoundBank 初始化的資料表：

- `soundbank_tracks`
- `soundbank_licenses`
- `soundbank_license_terms_versions`
- `soundbank_orders`
- `soundbank_downloads`
- `soundbank_private_assets`
- `soundbank_license_certificates`
- `soundbank_rights_proofs`
- `soundbank_violation_reports`

移轉注意：

- 訂單、付款狀態、下載紀錄與授權憑證是正式交易資料，不可直接在未定義政策時複製。
- 測試資料與 seed 資料可在 staging 重建。
- 若未來要搬正式交易資料，需先定義資料保留、個資遮罩、稽核紀錄與 rollback 流程。

## 靜態素材

目前位置：

`萬語通\11STARS\static\soundbank_assets`

已盤點：

- 5 個 PNG 視覺/PWA 資產。
- 28 個 preview WAV。
- 28 個 master WAV。
- 28 個 rights TXT。

移轉注意：

- preview 與公開圖檔可納入獨立專案或改由 object storage 發佈。
- master 音檔不應公開放在 repo 或公開靜態目錄。
- rights TXT 可公開或半公開，但正式版仍要保留 proof hash 與不可竄改紀錄。

## 腳本

目前腳本位置：

`萬語通\11STARS\scripts\soundbank_*`

重要類型：

- Object storage：manifest、R2/S3 preflight、upload packet、refs apply、verify。
- ECPay：reuse preflight、production env dry run、notify/return 驗證。
- 監控：soft-open monitor、Render log watch、launch guard。
- 政策：policy copy preflight、refund replay guard、refund cleanup。
- 匯入：staging/prod materials import、private asset import。

移轉注意：

- 腳本應分成 local-only、staging-only、production-safe 三類。
- 任何會連 production DB、ECPay、R2 或 Render 的腳本，都必須要求明確環境變數與 confirm guard。

## 文件

目前文件位置：

`萬語通\11STARS\docs\soundbank_*`

重要類型：

- MVP handoff
- go/no-go
- production env packet
- object storage migration
- ECPay reuse packet
- launch/promotion/checklist
- policy reports
- staging reports

移轉注意：

- 文件可搬，但要標示來源日期與是否仍有效。
- 不應把私密 URL、API key、付款後 private links 或客戶資料貼入新文件。

## 環境變數

SoundBank 相關環境變數前綴：

- `SOUNDBANK_ENABLED`
- `SOUNDBANK_INIT_DB`
- `SOUNDBANK_SEED_BETA_ORIGINALS`
- `SOUNDBANK_SHOW_STARTER_DEMOS`
- `SOUNDBANK_PUBLIC_BASE_URL`
- `SOUNDBANK_SIGNING_SECRET`
- `SOUNDBANK_PAYMENT_WEBHOOK_SECRET`
- `SOUNDBANK_FAKE_CHECKOUT_ENABLED`
- `SOUNDBANK_ECPAY_*`
- `SOUNDBANK_OBJECT_STORAGE_*`
- `SOUNDBANK_ALLOW_PUBLIC_MASTER_URLS`
- `SOUNDBANK_ORDER_TOKEN_TTL_SECONDS`
- `SOUNDBANK_DOWNLOAD_TOKEN_TTL_SECONDS`
- `SOUNDBANK_CERTIFICATE_TOKEN_TTL_SECONDS`

移轉注意：

- 新專案要用自己的 env group 或 Render service env。
- 不在 repo、文件或聊天室公開任何密鑰值。

## 外部服務

| 服務 | 目前用途 | 獨立化處理 |
| --- | --- | --- |
| Render Web Service | 執行 Flask app | 建獨立 SoundBank service |
| Render PostgreSQL | 儲存 tracks/orders/downloads/certs | 建獨立 DB 或明確共用策略 |
| ECPay | 付款與退刷 | 使用同商店可行，但 callback URL 要獨立 |
| Cloudflare R2/S3 | 私有 master 檔與 signed URL | 可沿用 bucket 或建立 SoundBank bucket |
| GitHub | PR、備份、rollback | 建獨立 repo 或保留 monorepo 子資料夾 |
| Gmail/LINE 通知 | 異常郵件與付款通知 | 僅做監控，不存 secrets |

## 目前最安全結論

可以移轉，但不要直接移動正式功能。先 copy-only 建可執行獨立 staging，等前台、後台、付款、下載、授權憑證、退刷與監控全部通過，再切正式 URL。
