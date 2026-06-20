# SoundBank Migration Plan

更新日期：2026-06-21

## 原則

- 不影響萬語通、LINE Bot、音樂電台與既有 Render production。
- 不公開密鑰、正式 master 音檔或客戶資料。
- 每一階段都要能 rollback。
- 先 staging，後 production。

## Phase 0 - 盤點與專案外殼

狀態：完成。

輸出：

- `README.md`
- `docs/handoff.md`
- `docs/adr/0001-extract-soundbank-from-11stars.md`
- `docs/migration/source-map.md`
- `docs/migration/migration-plan.md`
- `docs/migration/cutover-checklist.md`

## Phase 1 - 抽離可執行 App 骨架

目標：

- Copy `soundbank.py` 到 `src`。
- 建立獨立 `src\app.py`。
- 建立獨立 config/env loader。
- 建立獨立 requirements。
- 保留 feature flag 與 fake checkout guard。

驗收：

- 本機 `/soundbank` 可開。
- `python -m py_compile` 通過。
- 不連正式 ECPay。
- 不連正式 R2。
- 不修改 11STARS。

## Phase 2 - 獨立資料庫與 schema

目標：

- 建立 SoundBank 專用 DB schema 初始化。
- 將 seed/import 腳本改指向獨立 DB。
- 正式交易資料暫不搬移。

驗收：

- staging DB 可以建立 9 張資料表。
- beta tracks、licenses、rights proofs 可匯入。
- admin health 可讀出資料量。

## Phase 3 - 素材與 Object Storage

目標：

- preview 檔可公開安全播放。
- master 檔只透過 signed URL 下載。
- R2/S3 manifest 可驗證。

驗收：

- preview 200。
- master public route 404 或 forbidden。
- paid order 才能拿 signed URL。
- signed URL 過期時間符合設定。

## Phase 4 - 金流與授權憑證

目標：

- ECPay ReturnURL/NotifyURL 指向獨立 SoundBank staging。
- CheckMacValue 驗證正常。
- 付款成功後建立 downloads 與 license certificate。
- 退刷、取消、重複付款 replay guard 正常。

驗收：

- bad CheckMacValue 拒絕。
- valid notify 回 `1|OK`。
- 已退刷訂單不得被舊 notify 重開。
- 授權憑證公開驗證頁可查。

## Phase 5 - 前台、後台、Web App

目標：

- 前台首頁、素材、授權、下載、客服/退費、通報完整。
- 手機版排版穩定。
- 後台 health/orders/soft-open monitor 可用。
- PWA manifest/service worker 符合新網域。

驗收：

- Desktop 與 mobile smoke test 通過。
- 無 Render wake page。
- 無水平捲動與錯位。
- cache version 更新。

## Phase 6 - Cutover

目標：

- 正式 SoundBank 自訂網域或正式路徑切到獨立 service。
- 11STARS 保留 redirect 或 feature-gated fallback。

驗收：

- DNS/TLS 正常。
- ECPay production callback 到新 URL。
- R2 signed URL 正常。
- 監控 24-72 小時無重大異常。

## Phase 7 - 清理 11STARS

前提：

- 新 SoundBank production 穩定。
- 已有 rollback 文件。
- 確認舊 URL 的使用者與搜尋流量處理方式。

可選處理：

- 保留 `/soundbank` redirect 到新網域。
- 或保留只讀 fallback。
- 或完全移除 SoundBank 模組。
