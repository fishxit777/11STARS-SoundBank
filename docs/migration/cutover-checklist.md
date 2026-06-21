# SoundBank Cutover Checklist

更新日期：2026-06-21

此清單用於正式從 11STARS 內嵌 SoundBank 切到獨立 SoundBank service 前。

## 不可跳過

- [ ] 11STARS production 仍可正常服務萬語通與 LINE Bot。
- [ ] 獨立 SoundBank staging 前台通過。
- [ ] 獨立 SoundBank staging 後台通過。
- [ ] 獨立 SoundBank DB schema 通過。
- [ ] ECPay staging 或 production dry-run 通過。
- [ ] R2/S3 signed URL 通過。
- [ ] 退刷 replay guard 通過。
- [ ] 授權憑證與公開驗證頁通過。
- [ ] 手機版首頁、素材、授權、下載、客服/退費、通報通過。
- [ ] DNS/TLS 通過。
- [ ] Render health check 通過。
- [ ] 監控腳本可讀最新 deploy 與異常 log。
- [ ] 獨立 `11stars-soundbank` Render service 已確認連到
      `fishxit777/11STARS-SoundBank` 的 `main` branch。
- [ ] 公開推廣前，將獨立 SoundBank Render service 從 Free 升級，避免冷啟動等待
      並啟用自訂網域。
- [ ] 舊 `11stars-soundbank-staging` 已標記為 legacy staging、停用、或重新接到
      standalone repo。
- [ ] Gmail 異常信件檢查無阻斷項。

## 金流

- [ ] `ReturnURL` 指向獨立 SoundBank。
- [ ] `OrderResultURL` 指向獨立 SoundBank。
- [ ] `CheckMacValue` bad callback 拒絕。
- [ ] `CheckMacValue` valid callback 接受。
- [ ] 重複 notify 不重複開通。
- [ ] 已退刷、取消、chargeback 訂單不能被舊 notify 重開。
- [ ] 自付測試款項已在 ECPay 後台完成退刷或保留為明確測試紀錄。

## 下載與憑證

- [ ] 未付款不能下載 master。
- [ ] 付款成功可以下載正式檔。
- [ ] 下載次數與過期時間符合授權。
- [ ] 授權憑證 hash/verification URL 可查。
- [ ] revoked certificate 顯示正確。

## 內容與法律

- [ ] 每首曲目有秒數、BPM、用途、授權方案。
- [ ] 每首曲目有 rights proof 或不可上架。
- [ ] 禁止 Content ID、轉售、再授權、素材包再販售、音樂平台單獨發行。
- [ ] 退費頁與 checkout 提醒一致。
- [ ] 條款版本可追蹤。
- [ ] SEO/copy preflight 通過。

## 前端與手機

- [ ] 首頁無錯位。
- [ ] 素材卡片無文字溢出。
- [ ] audio player 可操作。
- [ ] 導覽列在手機可讀、可點。
- [ ] 背景圖不遮文字。
- [ ] PWA cache version 已更新。

## Rollback

- [ ] 保留 11STARS `/soundbank` 舊功能或 redirect fallback。
- [ ] 記錄 Render deploy id。
- [ ] 記錄 DB migration id。
- [ ] 記錄 DNS 變更時間。
- [ ] 確認 rollback 後 ECPay callback 不會打到錯誤服務。

## Go / No-Go

Go 條件：

- 上述不可跳過項目全過。
- 金流、下載、憑證、退刷四項全過。
- 手機前台無明顯錯位。
- 沒有新的異常信件或 Render 5xx。

No-Go 條件：

- 任何付款 callback 不穩。
- master 檔可被未付款公開下載。
- 授權憑證無法驗證。
- 手機版主要 CTA 無法使用。
- Render service 仍會顯示 wake page 且未升級或未做替代方案。
