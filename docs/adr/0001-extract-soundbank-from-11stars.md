# ADR 0001: 從 11STARS 抽離 SoundBank

日期：2026-06-21

## 狀態

Accepted for planning. 尚未切流量。

## 背景

SoundBank 最初放在 `萬語通\11STARS`，用 feature flag 控制曝光，目的是快速驗證 MVP：

- 音樂素材前台
- 授權方案
- ECPay 付款建立與回呼
- 授權憑證與公開驗證
- 私有 master 檔下載
- 退刷與重複付款防護
- 管理員監控與 soft-open 檢查

使用者現在希望 SoundBank 成為獨立專案，避免混在萬語通主系統內。

## 決策

採用旁路抽離，而不是直接移動：

1. 建立獨立專案資料夾與文件。
2. Copy 11STARS 內的 SoundBank 程式碼到獨立 app。
3. 逐步替換 11STARS 依賴，例如 `get_db`、admin token、Render env、ECPay callback base URL、R2/S3 設定。
4. 先部署獨立 staging。
5. 完成 production cutover 後，再決定 11STARS 中的 SoundBank 是否保留 redirect 或移除。

## 理由

- 可避免影響既有萬語通與 LINE Bot。
- 可保留 11STARS 當 rollback 來源。
- 可逐項驗證付款、下載、授權憑證、退刷與監控。
- 可避免一次搬移造成資料庫 schema、callback URL 或 signed URL 失效。

## 不做的事

- 不直接改 11STARS production route。
- 不複製或公開任何密鑰。
- 不搬客戶訂單資料到新專案，除非後續有明確 migration policy。
- 不把 master 音檔放進公開 repo。

## 後果

短期會有兩份邊界：

- 11STARS：正式線上 source of truth。
- 萬語聲庫_SoundBank：獨立化準備區。

這是刻意保守的做法。正式切換前，所有使用者仍走原 SoundBank URL。
