# scripts

此資料夾預留給獨立 SoundBank 腳本。

腳本分類建議：

- `local_*.py`：只跑本機，不連正式服務。
- `staging_*.py`：只允許 staging。
- `production_*.py`：必須有 confirm guard、乾跑模式與明確輸出。

任何需要 API key、DB URL、ECPay HashKey/HashIV、R2/S3 secret 的腳本，不可把值寫入 repo 或文件。
