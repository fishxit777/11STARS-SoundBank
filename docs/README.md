# SoundBank Docs Index

更新日期：2026-06-21

這裡是獨立 SoundBank 專案的文件入口。文件只記錄可公開或可交接資訊，不放 `.env`、API key、ECPay HashKey/HashIV、Render token、R2/S3 secret 或客戶個資。

## 先看哪裡

- [handoff.md](handoff.md)：目前狀態、下一步、已知限制。
- [migration/cutover-checklist.md](migration/cutover-checklist.md)：正式切流量前必過清單。
- [migration/payment-transfer-sop.md](migration/payment-transfer-sop.md)：ECPay 共用、移轉、出售交接與退刷邊界。
- [migration/source-map.md](migration/source-map.md)：從舊 `11STARS` 拆出來的來源對照。
- [migration/migration-plan.md](migration/migration-plan.md)：分階段拆分與驗證計畫。

## 架構與決策

- [adr/0001-extract-soundbank-from-11stars.md](adr/0001-extract-soundbank-from-11stars.md)：為什麼從 `11STARS` 拆到獨立 repo。

## 階段交接紀錄

- [handoff_20260621_phase1.md](handoff_20260621_phase1.md)
- [handoff_20260621_phase2.md](handoff_20260621_phase2.md)
- [handoff_20260621_phase4_publication_prep.md](handoff_20260621_phase4_publication_prep.md)
- [handoff_20260621_phase5_sync_verify.md](handoff_20260621_phase5_sync_verify.md)
- [handoff_20260621_phase6_render_binding.md](handoff_20260621_phase6_render_binding.md)
- [handoff_20260621_phase7_monitor_script.md](handoff_20260621_phase7_monitor_script.md)
- [handoff_20260621_phase8_split_audit.md](handoff_20260621_phase8_split_audit.md)

## 目前正式化順序

1. 保持 standalone repo 為主線，不再把 SoundBank 新功能寫回舊 `11STARS`。
2. 每次推送後執行 standalone smoke test、production health check、Render log watch 與 Gmail 異常信檢查。
3. 公開推廣前確認手機版首頁、素材頁、授權頁、下載頁、客服/退費頁與通報頁。
4. 金流正式交接時依 [payment-transfer-sop.md](migration/payment-transfer-sop.md) 更換買方 ECPay 憑證、callback URL 與客服/退費資訊。
5. DNS/TLS、Render paid instance 或替代防冷啟動方案確認後，再把正式入口對外推廣。

## 不應放進 repo 的東西

- Render API key、GitHub token、Cloudflare R2/S3 secret。
- ECPay MerchantID 以外的 HashKey/HashIV 或正式付款後台截圖。
- 客戶 email、付款明細、訂單完整卡號、個資或退款申請原文。
- 正式 master 音檔，除非已確認可公開且走受控下載流程。
