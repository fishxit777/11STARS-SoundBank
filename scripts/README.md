# scripts

這個資料夾放 11STARS SoundBank 的本機、驗證與營運輔助腳本。

命名原則：

- `local_*.py`：只跑本機檢查或本機資料整理。
- `staging_*.py`：只跑 staging 驗證。
- `production_*.py`：會碰正式服務的唯讀或受控腳本；必須輸出清楚結果，不能印出密鑰。

安全原則：

- 不要把 API key、DB URL、ECPay HashKey/HashIV、R2/S3 secret 寫進 repo 或文件。
- 需要密鑰時，從本機 private env 檔或系統環境變數載入。

## Standalone Verification

完整本機驗證：

```powershell
.\scripts\verify_standalone.ps1
```

## Legacy Sync Guard

`sync_from_11stars.ps1` 只保留給人工比對後的緊急來源同步。現在
`11STARS-SoundBank` 才是 SoundBank 主線，所以腳本預設會停止，避免把新
repo 的前台、文件與營運修正覆蓋回舊版。

只有在確認舊 `11STARS` 內容真的要重新匯入時，才可使用：

```powershell
.\scripts\sync_from_11stars.ps1 -ConfirmLegacySourceSync
```

## Render Raw Log Watch

監控正式 SoundBank Render 服務最近一小時錯誤、5xx、Traceback、Exception、CheckMac 與 ECPay 相關異常：

```powershell
$env:RENDER_API_KEY = "<load from private local secret store>"
python scripts\production_render_log_watch.py --hours 1
```

腳本預設監控 `11stars-soundbank` 服務，不會列印 API key。若要改監控其他 Render resource，可用 `RENDER_OWNER_ID` 與 `RENDER_SERVICE_ID` 覆蓋。
