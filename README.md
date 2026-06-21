# 萬語聲庫 SoundBank

此資料夾是 SoundBank 獨立化專案。現在 SoundBank 的主要開發、GitHub
備份與獨立 Render 部署來源已改到此 repo：

`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS-SoundBank`

GitHub：

`https://github.com/fishxit777/11STARS-SoundBank`

Render：

`https://one1stars-soundbank.onrender.com`

原本 `C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS` 內的
SoundBank 只保留作歷史備援、拆分來源對照與風險回滾參考；不要再把它
當成 SoundBank 的新功能主線。

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

此資料夾是獨立 SoundBank 的主要可執行專案。正式 DNS、ECPay
ReturnURL/NotifyURL、R2 bucket 或資料庫切換仍需逐項驗證後才調整；舊
`11STARS` 內的 SoundBank 只能當歷史備援與拆分對照，不應覆蓋此 repo
的新前台、文件或營運腳本。
