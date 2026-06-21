# 萬語聲庫 SoundBank

此資料夾是 SoundBank 獨立化的專案外殼。現在正式線上來源仍在：

`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS`

此獨立專案位置：

`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS-SoundBank`

目前狀態：獨立 GitHub repo 已建立，獨立 Render starter-demo 服務可驗證；尚未切正式流量，尚未從 11STARS 移除任何線上功能。

## 為什麼之前在萬語通 11STARS 裡

SoundBank 一開始採用低風險寄生模式，原因是可以共用既有：

- Render Web Service 與 PostgreSQL
- ECPay 金流設定與付款回呼
- Flask 後端、管理員驗證、監控腳本
- 既有備份、GitHub PR、Render 部署流程

這讓 MVP 能先上線驗證金流、授權憑證、下載與退刷流程，但也造成專案邊界不夠清楚。

## 現在的獨立化策略

採用 copy-first、verify、cutover：

1. 先在此資料夾建立獨立專案骨架與移轉文件。
2. 只複製可公開程式碼與文件，不複製密鑰、客戶資料或未確認可公開的正式 master 檔。
3. 建立獨立 staging，確認前台、後台、付款、下載、授權憑證、退刷保護與監控。
4. 通過 go/no-go 後再切正式 URL。
5. 切換穩定後，才規劃從 11STARS 移除 SoundBank 模組。

## 目前文件

- `docs/handoff.md`：目前狀態與下一步。
- `docs/adr/0001-extract-soundbank-from-11stars.md`：架構決策紀錄。
- `docs/migration/source-map.md`：來源檔案、腳本、資料表、環境變數與外部服務盤點。
- `docs/migration/migration-plan.md`：分階段拆分計畫。
- `docs/migration/cutover-checklist.md`：正式切流量前檢查清單。

## 重要界線

此資料夾是獨立 SoundBank 的可執行準備區。線上正式客戶流量仍以 11STARS 內的 SoundBank 為 rollback 來源。任何正式 DNS、ECPay ReturnURL/NotifyURL、R2 bucket 或資料庫切換，都必須等獨立 staging 與付款/下載/授權憑證驗證後再做。
