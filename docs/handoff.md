# SoundBank 獨立化交接

更新日期：2026-06-21

## 現況

SoundBank 目前是 `萬語通\11STARS` 裡的 feature-gated 子功能，正式路徑為：

- 前台：`https://one1stars-line-bot.onrender.com/soundbank`
- 核心模組：`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS\soundbank.py`
- 掛載點：`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS\app.py`
- 靜態素材：`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS\static\soundbank_assets`
- 文件與 runbook：`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS\docs\soundbank_*`
- 腳本：`C:\Users\bao58\OneDrive\文件\New project\萬語通\11STARS\scripts\soundbank_*`

## 本次完成

- 建立獨立專案外殼：`C:\Users\bao58\OneDrive\文件\New project\萬語聲庫_SoundBank`
- 建立移轉 source map、架構決策、分階段計畫與 cutover 清單。
- 未更動 11STARS 線上程式碼。
- 未搬移正式流量、金流、DNS、客戶資料、密鑰或 master 音檔。

## 為什麼不能直接拖過來

SoundBank 不是只有頁面。它包含付款、授權、憑證、下載簽章、退刷保護、資料表初始化、管理員頁、監控、R2/S3 私有檔與 Render 環境變數。直接移動資料夾會造成付款回呼、下載連結、憑證驗證或後台查詢中斷。

## 下一步

Phase 1：抽離可執行 app 骨架。

目標是把 11STARS 內的 SoundBank 程式碼 copy 到此專案的 `src`，包成獨立 Flask app，但仍只在本機或 staging 跑，不切正式流量。

驗收條件：

- 本機可啟動 `/soundbank`。
- `python -m py_compile` 通過。
- 前台主要頁面與手機版 layout 可檢查。
- 付款與下載仍預設 disabled 或 mock，不碰正式 ECPay。
- 文件列出剩餘耦合點。

預估時間：30-45 分鐘。

是否需要使用者驗證：目前不需要。
