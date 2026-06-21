# SoundBank Payment Transfer SOP

Updated: 2026-06-21

Purpose: make SoundBank payment routing movable without disturbing WanyuTong,
the music radio project, or any existing ECPay orders.

This document is operational guidance only. Do not paste merchant credentials,
HashKey, HashIV, card data, customer data, or raw payment callback bodies into
GitHub, chat, screenshots, or handoff documents.

## Current Decision

SoundBank can reuse the existing ECPay merchant account as long as it keeps its
own order prefix, callback URLs, database records, and refund checks.

If SoundBank is sold or transferred to another operator, the code can stay the
same, but the buyer should use their own ECPay merchant credentials and their
own legal/payment pages.

## What Moves

Move these items together when SoundBank is deployed under a new service,
domain, or owner:

- Source code: `fishxit777/11STARS-SoundBank`
- Render service: `11stars-soundbank`
- Database records for SoundBank orders, licenses, proofs, tracks, and refunds
- Object storage bucket and signed URL settings
- ECPay environment variables, stored only in Render or a local no-upload secret
  folder
- ECPay callback URLs that point to the active SoundBank base URL
- Monitoring scripts and handoff records

Do not move or overwrite WanyuTong / LINE Bot settings unless the change is
explicitly for those projects.

## ECPay Variables

Use SoundBank-specific environment variable names:

- `SOUNDBANK_ECPAY_MERCHANT_ID`
- `SOUNDBANK_ECPAY_HASH_KEY`
- `SOUNDBANK_ECPAY_HASH_IV`
- `SOUNDBANK_ECPAY_PAYMENT_URL`
- `SOUNDBANK_ECPAY_USE_STAGE`
- `SOUNDBANK_ECPAY_CHOOSE_PAYMENT`
- `SOUNDBANK_ECPAY_AUTOSUBMIT`
- `SOUNDBANK_ECPAY_ACCEPT_SIMULATED`
- `SOUNDBANK_PUBLIC_BASE_URL`

Never commit values for these variables.

## Callback Boundary

SoundBank creates ECPay checkout parameters from its own public base URL.

For the current routes:

- ReturnURL / server notification:
  `/soundbank/payment/ecpay/notify`
- OrderResultURL / buyer browser return:
  `/soundbank/payment/ecpay/return?order_id=...`

Operational rule:

- Treat `ReturnURL` as the payment source of truth because it is the server-side
  ECPay notification.
- Treat `OrderResultURL` as user experience only. It may be delayed, skipped,
  refreshed, or blocked by the buyer's browser.
- A paid license, download token, and certificate may be issued only after the
  server-side notification passes `CheckMacValue`, amount, order, and final-state
  guards.

Official references:

- ECPay AIO checkout docs:
  https://developers.ecpay.com.tw/?p=2862
- ECPay payment result notification docs:
  https://developers.ecpay.com.tw/?p=2878

## Shared Merchant Mode

Use this when the owner keeps WanyuTong, music radio, and SoundBank under the
same ECPay merchant.

Rules:

- Keep SoundBank order numbers prefixed with `SB-ORDER-ECPAY-`.
- Keep WanyuTong and music radio order prefixes separate.
- Keep SoundBank callback paths under `/soundbank/payment/ecpay/...`.
- Keep SoundBank order/license/refund tables separate from unrelated products.
- Monitor ECPay logs by SoundBank order prefix before changing any merchant-wide
  setting.
- Do not change ECPay account-level settings that could affect existing
  WanyuTong or music radio payment behavior unless the impact is documented and
  tested.

Minimum verification:

1. Create a SoundBank ECPay checkout.
2. Confirm the generated `MerchantTradeNo` starts with `SB-ORDER-ECPAY-`.
3. Complete payment.
4. Confirm server-side notify returns `1|OK`.
5. Confirm order status becomes `paid`.
6. Confirm download, license certificate, public verification page, and rights
   proof summary open correctly.
7. Confirm WanyuTong and music radio health checks still pass.
8. Check Gmail / ECPay / Render logs for abnormal notices.

## Buyer-Owned Merchant Mode

Use this when SoundBank is transferred or sold to another operator.

Buyer must provide their own:

- ECPay MerchantID
- ECPay HashKey
- ECPay HashIV
- Legal seller name, tax/invoice handling, support email, refund policy, and
  terms
- Domain and public base URL
- Render, database, object storage, and alerting access

Transfer sequence:

1. Freeze production changes.
2. Export a no-secret handoff package: code, docs, schema, seed data, public
   assets, and checklist.
3. Provision the buyer's Render service and database.
4. Set buyer ECPay variables in Render only.
5. Set `SOUNDBANK_PUBLIC_BASE_URL` to the buyer's SoundBank URL.
6. Use ECPay stage mode first if the buyer has stage credentials.
7. Run a stage payment or low-risk production test payment.
8. Verify notify, return, license, download, refund replay guard, and logs.
9. Cut DNS only after payment verification passes.
10. Keep the old owner service online as rollback until the buyer confirms a
    full order cycle.

Do not reuse the old owner's ECPay credentials after ownership transfer unless
there is a written business agreement that explicitly covers settlement,
refunds, customer support, chargebacks, tax/invoice responsibility, and access
termination.

## Refund And Self-Payment Tests

For owner self-tests, the order is still a real card authorization unless it was
created in fake checkout mode or ECPay stage mode.

Refund timing:

- Refund immediately after the test objective is complete if the transaction is
  not meant to remain as an accounting test record.
- Before refunding, record the SoundBank order ID, ECPay authorization number,
  amount, test purpose, and refund date in private accounting notes.
- After refunding, run the refund replay guard check so later ECPay notifications
  cannot reactivate a refunded or voided order.

Never assume money returns automatically just because the owner paid themselves.
It returns only after the card transaction is cancelled, voided, or refunded
through the proper ECPay flow.

## Cutover Checklist

Before switching SoundBank payment traffic:

- [ ] Target Render service health check returns 200.
- [ ] `SOUNDBANK_PUBLIC_BASE_URL` matches the target URL exactly.
- [ ] ECPay variables exist in Render and are not committed.
- [ ] `SOUNDBANK_ECPAY_USE_STAGE` is correct for the target environment.
- [ ] SoundBank order prefix is still `SB-ORDER-ECPAY-`.
- [ ] Bad `CheckMacValue` callback is rejected.
- [ ] Valid callback returns `1|OK`.
- [ ] Amount mismatch does not mark an order as paid.
- [ ] Refunded / cancelled / voided / chargeback orders cannot be reactivated.
- [ ] Download token and license certificate require paid status.
- [ ] Public proof page exposes only safe proof summary data.
- [ ] WanyuTong and music radio checks still pass if sharing the merchant.
- [ ] Gmail and Render logs show no new abnormal payment alerts.

## Rollback

If any payment test fails:

1. Stop public promotion.
2. Disable or hide live checkout while keeping browsing/preview active.
3. Restore the previous Render deploy or previous ECPay variable set.
4. Do not retry payment until the failure reason is recorded.
5. Check whether any pending buyer order requires manual support or refund.

Rollback must not delete order records. Keep failed/pending orders for audit and
support unless legal/accounting policy says otherwise.

## Go / No-Go

Go only when:

- Checkout creates a unique SoundBank order.
- ECPay notify passes signature and amount validation.
- Paid status opens download and license pages.
- Refund/void replay guard passes.
- No 5xx, Traceback, CheckMac, or abnormal email appears after the test.

No-Go when:

- Callback URL points to the wrong project.
- Any SoundBank callback can update WanyuTong or music radio records.
- Order prefix collides with another product.
- Browser return page can mark an order paid without server notify.
- Credentials are present in Git history, screenshots, chat, or documents.

