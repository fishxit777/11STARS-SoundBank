import base64
import csv
import hashlib
import hmac
import html
import json
import mimetypes
import os
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras
from flask import abort, jsonify, make_response, redirect, request


TRUE_VALUES = {'1', 'true', 'yes', 'on', 'enabled'}
TOKEN_VERSION = 'v1'
SOUNDBANK_FINAL_PAYMENT_STATUSES = {'refunded', 'cancelled', 'canceled', 'voided', 'chargeback'}
SOUNDBANK_PWA_CACHE_VERSION = '20260620-2'
SOUNDBANK_PWA_PUBLIC_ASSETS = [
    '/soundbank',
    '/soundbank/tracks',
    '/soundbank/license',
    '/soundbank/support',
    '/static/soundbank_assets/soundbank-fullpage-wallpaper.png',
    '/static/soundbank_assets/soundbank-hero-visual.png',
    '/static/soundbank_assets/soundbank-page-backdrop.png',
    '/static/soundbank_assets/soundbank-app-icon-192.png',
    '/static/soundbank_assets/soundbank-app-icon-512.png',
]
SOUNDBANK_PWA_PRIVATE_PREFIXES = [
    '/soundbank/checkout',
    '/soundbank/success',
    '/soundbank/download',
    '/soundbank/downloads',
    '/soundbank/license-certificate',
    '/soundbank/verify',
    '/soundbank/payment',
    '/soundbank/api',
    '/soundbank/admin',
]

SOUNDBANK_LICENSE_RESTRICTIONS = [
    '不得註冊 Content ID、YouTube CID、Facebook Rights Manager 或任何第三方權利管理系統。',
    '不得轉售、再授權、重新包裝成素材庫、模板、beat pack、SaaS 內容庫或 marketplace 商品。',
    '不得把音樂單獨上架 Spotify、Apple Music、YouTube Music、KKBOX、SoundCloud 等串流平台或變成可被他人下載的音樂商品。',
    '不得作為 AI 訓練資料、模型微調資料、資料集或聲音克隆來源。',
]

SOUNDBANK_REFUND_SUPPORT_RULES = [
    '未付款或付款失敗不成立訂單，也不會開通下載。',
    '付款成功但尚未下載正式音檔前，可於 7 日內申請人工退費審核；若核准退費，已產生的授權憑證會撤銷或作廢。',
    '已下載正式音檔、已使用於公開/商業內容或已進入權利爭議申訴流程後，原則上不退費。',
    '重複扣款、檔案毀損、授權憑證錯誤或平台無法交付時，優先補發或修正；無法修正時可退費。',
    '客服回覆目標為 2 個工作日內，Content ID 或權利爭議會優先處理。',
]


def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


def _soundbank_secret():
    secret = (
        os.environ.get('SOUNDBANK_SIGNING_SECRET', '').strip()
        or os.environ.get('ADMIN_TOKEN', '').strip()
    )
    if secret:
        return secret
    if os.environ.get('SOUNDBANK_FAKE_CHECKOUT_ENABLED', 'false').strip().lower() in TRUE_VALUES:
        return 'staging-only-soundbank-secret'
    return ''


def _has_configured_soundbank_secret():
    return bool(os.environ.get('SOUNDBANK_SIGNING_SECRET', '').strip())


def _bool_env(name, default=False):
    value = os.environ.get(name, '').strip().lower()
    if not value:
        return bool(default)
    return value in TRUE_VALUES


def _soundbank_payment_status(order):
    return str((order or {}).get('payment_status') or '').strip().lower()


def _soundbank_order_blocks_paid_callback(order):
    return _soundbank_payment_status(order) in SOUNDBANK_FINAL_PAYMENT_STATUSES


def _b64url(data):
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def _unb64url(value):
    padded = str(value or '') + ('=' * (-len(str(value or '')) % 4))
    return base64.urlsafe_b64decode(padded.encode('ascii'))


def _make_token(payload, ttl_seconds):
    secret = _soundbank_secret()
    if not secret:
        return ''
    data = dict(payload or {})
    data['v'] = TOKEN_VERSION
    data['exp'] = int(time.time()) + int(ttl_seconds)
    raw = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    encoded = _b64url(raw)
    sig = hmac.new(secret.encode('utf-8'), encoded.encode('ascii'), hashlib.sha256).hexdigest()
    return encoded + '.' + sig


def _verify_token(token, expected_purpose):
    secret = _soundbank_secret()
    if not secret or '.' not in str(token or ''):
        return None
    encoded, sig = str(token).split('.', 1)
    expected = hmac.new(secret.encode('utf-8'), encoded.encode('ascii'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64url(encoded).decode('utf-8'))
    except Exception:
        return None
    if payload.get('v') != TOKEN_VERSION:
        return None
    if payload.get('purpose') != expected_purpose:
        return None
    if int(payload.get('exp') or 0) < int(time.time()):
        return None
    return payload


def soundbank_enabled():
    return os.environ.get('SOUNDBANK_ENABLED', 'false').strip().lower() in TRUE_VALUES


def soundbank_should_initialize():
    return (
        soundbank_enabled()
        or os.environ.get('SOUNDBANK_INIT_DB', 'false').strip().lower() in TRUE_VALUES
    )


def soundbank_should_seed_beta_originals():
    explicit = os.environ.get('SOUNDBANK_SEED_BETA_ORIGINALS', '').strip().lower()
    if explicit:
        return explicit in TRUE_VALUES
    return _bool_env('SOUNDBANK_FAKE_CHECKOUT_ENABLED', False) and soundbank_should_initialize()


def _tw_now():
    return (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')


def _esc(value):
    return html.escape(str(value or ''), quote=True)


def _money(amount):
    try:
        return 'NT$' + format(int(amount or 0), ',')
    except Exception:
        return 'NT$0'


def _slug(value, fallback='soundbank'):
    raw = str(value or '').strip().lower()
    out = []
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
        elif ch in [' ', '-', '_']:
            out.append('-')
    result = ''.join(out).strip('-')
    return result[:80] or fallback


def _allow_public_master_urls():
    explicit = os.environ.get('SOUNDBANK_ALLOW_PUBLIC_MASTER_URLS', '').strip()
    if explicit:
        return explicit.lower() in TRUE_VALUES
    return _bool_env('SOUNDBANK_FAKE_CHECKOUT_ENABLED', False)


def _is_public_static_master_request(path):
    raw = urllib.parse.unquote(str(path or '')).replace('\\', '/')
    parts = []
    for part in raw.split('/'):
        if not part or part == '.':
            continue
        if part == '..':
            if parts:
                parts.pop()
            continue
        parts.append(part.lower())
    if len(parts) < 3 or parts[0] != 'static' or parts[1] != 'soundbank_assets':
        return False
    filename = parts[-1]
    return '-master.' in filename


def _storage_env(name, default=''):
    return os.environ.get('SOUNDBANK_' + name, os.environ.get(name, default)).strip()


def _aws_quote(value, safe=''):
    return urllib.parse.quote(str(value or ''), safe=safe)


def _aws_signing_key(secret_key, date_stamp, region, service='s3'):
    key = ('AWS4' + secret_key).encode('utf-8')
    for item in (date_stamp, region, service, 'aws4_request'):
        key = hmac.new(key, item.encode('utf-8'), hashlib.sha256).digest()
    return key


def _presign_object_storage_url(storage_url):
    parsed = urllib.parse.urlparse(storage_url)
    if parsed.scheme not in {'s3', 'r2'}:
        return ''
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    if not bucket or not key:
        return ''
    access_key = _storage_env('OBJECT_STORAGE_ACCESS_KEY_ID', '')
    secret_key = _storage_env('OBJECT_STORAGE_SECRET_ACCESS_KEY', '')
    if not access_key or not secret_key:
        return ''
    region = _storage_env('OBJECT_STORAGE_REGION', 'auto' if parsed.scheme == 'r2' else 'us-east-1')
    endpoint = _storage_env('OBJECT_STORAGE_ENDPOINT', '')
    if not endpoint:
        endpoint = 'https://s3.' + region + '.amazonaws.com'
    endpoint = endpoint.rstrip('/')
    expires = max(60, min(_int_env('SOUNDBANK_OBJECT_STORAGE_SIGNED_URL_TTL_SECONDS', 300), 604800))
    now = datetime.utcnow()
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')
    credential_scope = date_stamp + '/' + region + '/s3/aws4_request'
    credential = access_key + '/' + credential_scope
    path = '/' + bucket + '/' + key
    host = urllib.parse.urlparse(endpoint).netloc
    query = {
        'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
        'X-Amz-Credential': credential,
        'X-Amz-Date': amz_date,
        'X-Amz-Expires': str(expires),
        'X-Amz-SignedHeaders': 'host',
    }
    canonical_query = '&'.join(
        _aws_quote(k, safe='') + '=' + _aws_quote(query[k], safe='-_.~/')
        for k in sorted(query)
    )
    canonical_request = '\n'.join([
        'GET',
        _aws_quote(path, safe='/-_.~'),
        canonical_query,
        'host:' + host,
        '',
        'host',
        'UNSIGNED-PAYLOAD',
    ])
    string_to_sign = '\n'.join([
        'AWS4-HMAC-SHA256',
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode('utf-8')).hexdigest(),
    ])
    signature = hmac.new(
        _aws_signing_key(secret_key, date_stamp, region),
        string_to_sign.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return endpoint + _aws_quote(path, safe='/-_.~') + '?' + canonical_query + '&X-Amz-Signature=' + signature


def _ecpay_credentials():
    return {
        'merchant_id': os.environ.get('SOUNDBANK_ECPAY_MERCHANT_ID', '').strip(),
        'hash_key': os.environ.get('SOUNDBANK_ECPAY_HASH_KEY', '').strip(),
        'hash_iv': os.environ.get('SOUNDBANK_ECPAY_HASH_IV', '').strip(),
    }


def _ecpay_configured():
    creds = _ecpay_credentials()
    return bool(creds.get('merchant_id') and creds.get('hash_key') and creds.get('hash_iv'))


def _ecpay_payment_url():
    explicit = os.environ.get('SOUNDBANK_ECPAY_PAYMENT_URL', '').strip()
    if explicit:
        return explicit
    use_stage = _bool_env(
        'SOUNDBANK_ECPAY_USE_STAGE',
        _bool_env('SOUNDBANK_FAKE_CHECKOUT_ENABLED', False),
    )
    if use_stage:
        return 'https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5'
    return 'https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5'


def _ecpay_check_mac(params, hash_key, hash_iv):
    pairs = []
    for key, value in (params or {}).items():
        if str(key).lower() == 'checkmacvalue':
            continue
        pairs.append((str(key), '' if value is None else str(value)))
    pairs.sort(key=lambda item: item[0].lower())
    raw = 'HashKey=' + hash_key + '&' + '&'.join(k + '=' + v for k, v in pairs) + '&HashIV=' + hash_iv
    encoded = urllib.parse.quote_plus(raw).lower()
    replacements = {
        '%2d': '-',
        '%5f': '_',
        '%2e': '.',
        '%21': '!',
        '%2a': '*',
        '%28': '(',
        '%29': ')',
    }
    for old, new in replacements.items():
        encoded = encoded.replace(old, new)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest().upper()


def _ecpay_safe_text(value, fallback='SoundBank'):
    text = str(value or '').strip()
    if not text:
        text = fallback
    out = []
    for ch in text:
        if ch.isalnum() or ch in [' ', '-', '_', '.', ',']:
            out.append(ch)
    cleaned = ''.join(out).strip()
    return (cleaned or fallback)[:180]


def _ecpay_trade_no():
    return 'SB' + datetime.utcnow().strftime('%y%m%d%H%M%S') + uuid.uuid4().hex[:6].upper()


def _ecpay_order_params(order, track, selected_license, bot_base_url=''):
    creds = _ecpay_credentials()
    trade_date = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y/%m/%d %H:%M:%S')
    item_name = _ecpay_safe_text(
        'SoundBank ' + str(track.get('id') or '') + ' ' + str(selected_license.get('license_type') or ''),
        'SoundBank license',
    )
    params = {
        'MerchantID': creds.get('merchant_id'),
        'MerchantTradeNo': order.get('merchant_order_no'),
        'MerchantTradeDate': trade_date,
        'PaymentType': 'aio',
        'TotalAmount': int(order.get('amount') or 0),
        'TradeDesc': 'SoundBank license',
        'ItemName': item_name,
        'ReturnURL': _external_url('/soundbank/payment/ecpay/notify', bot_base_url),
        'OrderResultURL': _external_url('/soundbank/payment/ecpay/return?order_id=' + order.get('order_id'), bot_base_url),
        'CustomField1': order.get('order_id'),
        'CustomField2': order.get('track_id'),
        'CustomField3': order.get('license_type'),
        'CustomField4': 'soundbank',
        'ChoosePayment': os.environ.get('SOUNDBANK_ECPAY_CHOOSE_PAYMENT', 'ALL').strip() or 'ALL',
        'EncryptType': 1,
    }
    params['CheckMacValue'] = _ecpay_check_mac(params, creds.get('hash_key'), creds.get('hash_iv'))
    return params


def _ecpay_payment_form(params):
    action = _ecpay_payment_url()
    fields = ''.join(
        '<input type="hidden" name="' + _esc(k) + '" value="' + _esc(v) + '">'
        for k, v in params.items()
    )
    autosubmit = _bool_env('SOUNDBANK_ECPAY_AUTOSUBMIT', False)
    script = ''
    if autosubmit:
        script = '<script>document.getElementById("soundbank-ecpay-form").submit();</script>'
    return '''
    <h1>前往 ECPay 付款</h1>
    <div class="notice">付款成功後，系統會自動確認訂單並開通下載與授權憑證。</div>
    <form id="soundbank-ecpay-form" method="POST" action="''' + _esc(action) + '''">
      ''' + fields + '''
      <button class="button" type="submit">前往 ECPay 付款頁</button>
    </form>
    <div class="notice warn">請勿重複送出同一張付款單；若付款頁已開啟，請在原頁面完成付款。</div>
    ''' + script


def _admin_guard(is_admin_token_valid, check_admin_ip):
    if not check_admin_ip():
        return jsonify({'error': '存取被拒絕'}), 403
    if not is_admin_token_valid():
        return jsonify({'error': '後台未登入或 token 無效'}), 403
    return None


def _require_public_enabled():
    if not soundbank_enabled():
        abort(404)


def _fetch_all(get_db, sql, params=()):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _fetch_one(get_db, sql, params=()):
    rows = _fetch_all(get_db, sql, params)
    return rows[0] if rows else None


def _execute(get_db, sql, params=(), fetch_one=False):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        fetched = cur.fetchone() if fetch_one and cur.description else None
        row = dict(fetched) if fetched else None
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _external_url(path, bot_base_url=''):
    path = '/' + str(path or '').lstrip('/')
    base = str(bot_base_url or '').strip().rstrip('/')
    return (base + path) if base else path


def _parse_time(value):
    text = str(value or '').strip()
    if not text:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(text[:19], fmt)
        except Exception:
            pass
    return None


def _active_terms_version(get_db):
    terms = _fetch_one(
        get_db,
        '''
        SELECT version
        FROM soundbank_license_terms_versions
        WHERE status='active'
        ORDER BY effective_date DESC, created_at DESC
        LIMIT 1
        '''
    )
    return terms.get('version', '') if terms else ''


def _order_bundle(get_db, order_id):
    return _fetch_one(
        get_db,
        '''
        SELECT o.order_id, o.track_id, o.license_id, o.license_type, o.amount,
               o.currency, o.buyer_legal_name, o.buyer_email, o.payment_provider,
               o.payment_status, o.merchant_order_no, o.provider_trade_no,
               o.terms_version, o.paid_at,
               o.created_at, t.title AS track_title, t.download_audio_url,
               l.usage_scope, l.download_limit
        FROM soundbank_orders o
        LEFT JOIN soundbank_tracks t ON t.id=o.track_id
        LEFT JOIN soundbank_licenses l
               ON l.track_id=o.track_id AND l.license_type=o.license_type
        WHERE o.order_id=%s
        LIMIT 1
        ''',
        (order_id,)
    )


def _order_bundle_by_payment_ref(get_db, payment_ref):
    return _fetch_one(
        get_db,
        '''
        SELECT o.order_id, o.track_id, o.license_id, o.license_type, o.amount,
               o.currency, o.buyer_legal_name, o.buyer_email, o.payment_provider,
               o.payment_status, o.merchant_order_no, o.provider_trade_no,
               o.terms_version, o.paid_at,
               o.created_at, t.title AS track_title, t.download_audio_url,
               l.usage_scope, l.download_limit
        FROM soundbank_orders o
        LEFT JOIN soundbank_tracks t ON t.id=o.track_id
        LEFT JOIN soundbank_licenses l
               ON l.track_id=o.track_id AND l.license_type=o.license_type
        WHERE o.order_id=%s OR o.merchant_order_no=%s
        ORDER BY o.created_at DESC
        LIMIT 1
        ''',
        (payment_ref, payment_ref)
    )


def _private_asset_response(get_db, asset_id):
    row = _fetch_one(
        get_db,
        '''
        SELECT asset_id, filename, content_type, byte_size, sha256, data
        FROM soundbank_private_assets
        WHERE asset_id=%s
        LIMIT 1
        ''',
        (asset_id,)
    )
    if not row:
        return None
    data = row.get('data') or b''
    if isinstance(data, memoryview):
        data = data.tobytes()
    response = make_response(bytes(data))
    response.headers['Content-Type'] = row.get('content_type') or 'application/octet-stream'
    response.headers['Content-Length'] = str(row.get('byte_size') or len(data))
    response.headers['Content-Disposition'] = 'attachment; filename="' + _slug(row.get('filename'), asset_id) + '"'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if row.get('sha256'):
        response.headers['X-SoundBank-Asset-SHA256'] = row.get('sha256')
    return response


def _master_download_response(get_db, order):
    target_ref = str(order.get('download_audio_url') or '').strip()
    if not target_ref:
        return None, 'missing'
    if target_ref.startswith('db://'):
        asset_id = target_ref[len('db://'):].strip('/')
        if not asset_id:
            return None, 'missing'
        response = _private_asset_response(get_db, asset_id)
        return (response, '') if response else (None, 'private asset not found')
    if target_ref.startswith('s3://') or target_ref.startswith('r2://'):
        signed_url = _presign_object_storage_url(target_ref)
        if not signed_url:
            return None, 'object storage signing is not configured'
        return redirect(signed_url), ''
    if target_ref.startswith('http://') or target_ref.startswith('https://'):
        if not _allow_public_master_urls():
            return None, 'public master URL is disabled'
        return redirect(target_ref), ''
    return None, 'unsupported master storage reference'


def _ensure_download_row(get_db, order_id, track_id, expires_at=None):
    existing = _fetch_one(
        get_db,
        '''
        SELECT d.id, d.order_id, d.track_id, d.download_count, d.expires_at
        FROM soundbank_downloads d
        JOIN soundbank_orders o ON o.order_id=d.order_id
        WHERE d.order_id=%s
          AND LOWER(COALESCE(o.payment_status,''))='paid'
        ORDER BY d.id ASC
        LIMIT 1
        ''',
        (order_id,)
    )
    if existing:
        return existing
    now = _tw_now()
    return _execute(
        get_db,
        '''
        INSERT INTO soundbank_downloads
        (order_id, track_id, download_count, expires_at, created_at)
        SELECT o.order_id,
               CASE WHEN COALESCE(o.track_id,'')='' THEN %s ELSE o.track_id END,
               0, %s, %s
        FROM soundbank_orders o
        WHERE o.order_id=%s
          AND LOWER(COALESCE(o.payment_status,''))='paid'
        RETURNING id, order_id, track_id, download_count, expires_at
        ''',
        (
            track_id,
            expires_at or (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S'),
            now,
            order_id,
        ),
        fetch_one=True,
    )


def _certificate_hash(bundle, certificate_id, issued_at):
    canonical = '|'.join([
        str(certificate_id or ''),
        str(bundle.get('order_id') or ''),
        str(bundle.get('track_id') or ''),
        str(bundle.get('track_title') or ''),
        str(bundle.get('license_type') or ''),
        str(bundle.get('buyer_legal_name') or ''),
        str(bundle.get('buyer_email') or ''),
        str(bundle.get('amount') or ''),
        str(bundle.get('terms_version') or ''),
        str(issued_at or ''),
    ])
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest().upper()


def _ensure_license_certificate(get_db, order_id, bot_base_url=''):
    bundle = _order_bundle(get_db, order_id)
    if not bundle or bundle.get('payment_status') != 'paid':
        return None
    existing = _fetch_one(
        get_db,
        '''
        SELECT c.certificate_id, c.order_id, c.buyer_name, c.track_id, c.track_title,
               c.license_type, c.usage_scope, c.terms_version, c.certificate_hash,
               c.certificate_url, c.verification_url, c.issued_at
        FROM soundbank_license_certificates c
        JOIN soundbank_orders o ON o.order_id=c.order_id
        WHERE c.order_id=%s
          AND COALESCE(c.revoked_at,'')=''
          AND LOWER(COALESCE(o.payment_status,''))='paid'
        ORDER BY c.issued_at DESC
        LIMIT 1
        ''',
        (order_id,)
    )
    if existing:
        return existing
    certificate_id = 'SB-CERT-' + uuid.uuid4().hex[:12].upper()
    issued_at = _tw_now()
    cert_hash = _certificate_hash(bundle, certificate_id, issued_at)
    certificate_url = _external_url('/soundbank/license-certificate/' + certificate_id, bot_base_url)
    verification_url = _external_url('/soundbank/verify/' + certificate_id, bot_base_url)
    return _execute(
        get_db,
        '''
        INSERT INTO soundbank_license_certificates
        (certificate_id, order_id, buyer_name, buyer_id, track_id, track_title,
         license_type, usage_scope, terms_version, certificate_hash,
         certificate_url, verification_url, issued_at)
        SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        FROM soundbank_orders o
        WHERE o.order_id=%s
          AND LOWER(COALESCE(o.payment_status,''))='paid'
        RETURNING certificate_id, order_id, buyer_name, track_id, track_title,
                  license_type, usage_scope, terms_version, certificate_hash,
                  certificate_url, verification_url, issued_at
        ''',
        (
            certificate_id,
            order_id,
            bundle.get('buyer_legal_name', ''),
            bundle.get('buyer_email', ''),
            bundle.get('track_id', ''),
            bundle.get('track_title', ''),
            bundle.get('license_type', ''),
            bundle.get('usage_scope', ''),
            bundle.get('terms_version', ''),
            cert_hash,
            certificate_url,
            verification_url,
            issued_at,
            order_id,
        ),
        fetch_one=True,
    )


def _finalize_paid_order(
    get_db,
    order_id,
    track_id,
    selected_license,
    license_type,
    buyer_name,
    buyer_email,
    payment_provider,
    merchant_order_no,
    bot_base_url='',
):
    now = _tw_now()
    terms_version = _active_terms_version(get_db)
    amount = int(selected_license.get('price') or 0)
    _execute(
        get_db,
        '''
        INSERT INTO soundbank_orders
        (order_id, track_id, license_id, license_type, amount, currency,
         buyer_legal_name, buyer_email, payment_provider, payment_status,
         merchant_order_no, terms_version, paid_at, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,'TWD',%s,%s,%s,'paid',%s,%s,%s,%s,%s)
        ON CONFLICT (order_id) DO UPDATE SET
            payment_status='paid',
            payment_provider=EXCLUDED.payment_provider,
            merchant_order_no=EXCLUDED.merchant_order_no,
            paid_at=CASE
                WHEN COALESCE(soundbank_orders.paid_at,'')='' THEN EXCLUDED.paid_at
                ELSE soundbank_orders.paid_at
            END,
            updated_at=EXCLUDED.updated_at
        ''',
        (
            order_id,
            track_id,
            selected_license.get('license_id', ''),
            license_type,
            amount,
            buyer_name,
            buyer_email,
            payment_provider,
            merchant_order_no or order_id,
            terms_version,
            now,
            now,
            now,
        )
    )
    _ensure_download_row(
        get_db,
        order_id,
        track_id,
        (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S'),
    )
    certificate = _ensure_license_certificate(get_db, order_id, bot_base_url)
    return {
        'order_id': order_id,
        'certificate_id': certificate.get('certificate_id') if certificate else '',
        'access_token': _make_token(
            {'purpose': 'order_access', 'order_id': order_id},
            _int_env('SOUNDBANK_ORDER_TOKEN_TTL_SECONDS', 3600),
        ),
    }


def _create_pending_order(
    get_db,
    order_id,
    track_id,
    selected_license,
    license_type,
    buyer_name,
    buyer_email,
    payment_provider,
    merchant_order_no,
):
    now = _tw_now()
    terms_version = _active_terms_version(get_db)
    amount = int(selected_license.get('price') or 0)
    return _execute(
        get_db,
        '''
        INSERT INTO soundbank_orders
        (order_id, track_id, license_id, license_type, amount, currency,
         buyer_legal_name, buyer_email, payment_provider, payment_status,
         merchant_order_no, terms_version, paid_at, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,'TWD',%s,%s,%s,'pending',%s,%s,'',%s,%s)
        ON CONFLICT (order_id) DO UPDATE SET
            buyer_legal_name=EXCLUDED.buyer_legal_name,
            buyer_email=EXCLUDED.buyer_email,
            payment_provider=EXCLUDED.payment_provider,
            merchant_order_no=EXCLUDED.merchant_order_no,
            updated_at=EXCLUDED.updated_at
        RETURNING order_id, track_id, license_id, license_type, amount, currency,
                  buyer_legal_name, buyer_email, payment_provider, payment_status,
                  merchant_order_no, terms_version, paid_at, created_at, updated_at
        ''',
        (
            order_id,
            track_id,
            selected_license.get('license_id', ''),
            license_type,
            amount,
            buyer_name,
            buyer_email,
            payment_provider,
            merchant_order_no,
            terms_version,
            now,
            now,
        ),
        fetch_one=True,
    )


def _verify_webhook_signature(raw_body):
    secret = os.environ.get('SOUNDBANK_PAYMENT_WEBHOOK_SECRET', '').strip()
    if not secret:
        return False, 'webhook secret is not configured'
    received = request.headers.get('X-SoundBank-Signature', '').strip()
    expected = 'sha256=' + hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received, expected):
        return False, 'signature mismatch'
    return True, ''


def starter_tracks():
    return [
        {
            'id': 'SB-AIRADIO-001',
            'title': '科技感 AI 電台開場',
            'description': '適合 AI 電台、科技節目、產品更新影片的 12 秒開場音樂。',
            'category': 'AI 電台片頭',
            'mood': '科技、俐落',
            'bpm': 118,
            'duration_seconds': 12,
            'preview_audio_url': '',
            'cover_image_url': '',
            'status': 'demo',
            'price_personal': 299,
            'price_commercial': 999,
            'price_project': 2999,
            'rights_status': 'demo_only',
        },
        {
            'id': 'SB-PODCAST-001',
            'title': '溫暖談話背景',
            'description': '適合訪談、故事型 Podcast、品牌內容說明的低干擾背景音。',
            'category': 'Podcast BGM',
            'mood': '溫暖、穩定',
            'bpm': 92,
            'duration_seconds': 45,
            'preview_audio_url': '',
            'cover_image_url': '',
            'status': 'demo',
            'price_personal': 299,
            'price_commercial': 999,
            'price_project': 2999,
            'rights_status': 'demo_only',
        },
        {
            'id': 'SB-SHORT-001',
            'title': '輕快產品展示',
            'description': '適合短影音、開箱、教學、活動花絮與社群品牌影片。',
            'category': '短影音配樂',
            'mood': '輕快、乾淨',
            'bpm': 124,
            'duration_seconds': 30,
            'preview_audio_url': '',
            'cover_image_url': '',
            'status': 'demo',
            'price_personal': 299,
            'price_commercial': 999,
            'price_project': 2999,
            'rights_status': 'demo_only',
        },
    ]


def init_soundbank_db(get_db):
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_tracks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT DEFAULT '',
        mood TEXT DEFAULT '',
        bpm INTEGER DEFAULT 0,
        duration_seconds INTEGER DEFAULT 0,
        preview_audio_url TEXT DEFAULT '',
        download_audio_url TEXT DEFAULT '',
        cover_image_url TEXT DEFAULT '',
        status TEXT DEFAULT 'draft',
        rights_status TEXT DEFAULT 'missing',
        review_status TEXT DEFAULT 'draft',
        rights_score INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        published_at TEXT DEFAULT '',
        retired_at TEXT DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_licenses (
        id SERIAL PRIMARY KEY,
        license_id TEXT UNIQUE NOT NULL,
        track_id TEXT NOT NULL,
        license_type TEXT NOT NULL,
        price INTEGER DEFAULT 0,
        usage_scope TEXT DEFAULT '',
        term TEXT DEFAULT 'perpetual',
        territory TEXT DEFAULT 'worldwide',
        channel_limit INTEGER DEFAULT 1,
        project_limit INTEGER DEFAULT 1,
        download_limit INTEGER DEFAULT 3,
        is_commercial INTEGER DEFAULT 0,
        content_id_prohibited INTEGER DEFAULT 1,
        sublicense_prohibited INTEGER DEFAULT 1,
        ai_training_prohibited INTEGER DEFAULT 1,
        distribution_restriction TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(track_id, license_type)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_license_terms_versions (
        version TEXT PRIMARY KEY,
        effective_date TEXT NOT NULL,
        terms_html TEXT NOT NULL,
        created_by TEXT DEFAULT '',
        status TEXT DEFAULT 'draft',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_orders (
        order_id TEXT PRIMARY KEY,
        user_id TEXT DEFAULT '',
        line_user_id TEXT DEFAULT '',
        track_id TEXT NOT NULL,
        license_id TEXT DEFAULT '',
        license_type TEXT DEFAULT '',
        amount INTEGER DEFAULT 0,
        currency TEXT DEFAULT 'TWD',
        buyer_legal_name TEXT DEFAULT '',
        buyer_email TEXT DEFAULT '',
        buyer_tax_id TEXT DEFAULT '',
        payment_provider TEXT DEFAULT '',
        payment_status TEXT DEFAULT 'pending',
        merchant_order_no TEXT DEFAULT '',
        provider_trade_no TEXT DEFAULT '',
        terms_version TEXT DEFAULT '',
        paid_at TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_downloads (
        id SERIAL PRIMARY KEY,
        order_id TEXT NOT NULL,
        user_id TEXT DEFAULT '',
        track_id TEXT NOT NULL,
        download_count INTEGER DEFAULT 0,
        last_downloaded_at TEXT DEFAULT '',
        expires_at TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_private_assets (
        asset_id TEXT PRIMARY KEY,
        track_id TEXT NOT NULL,
        filename TEXT DEFAULT '',
        content_type TEXT DEFAULT 'application/octet-stream',
        storage_provider TEXT DEFAULT 'db',
        storage_key TEXT DEFAULT '',
        byte_size INTEGER DEFAULT 0,
        sha256 TEXT DEFAULT '',
        data BYTEA,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_license_certificates (
        certificate_id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        buyer_name TEXT DEFAULT '',
        buyer_id TEXT DEFAULT '',
        track_id TEXT NOT NULL,
        track_title TEXT DEFAULT '',
        license_type TEXT DEFAULT '',
        usage_scope TEXT DEFAULT '',
        terms_version TEXT DEFAULT '',
        certificate_hash TEXT DEFAULT '',
        certificate_url TEXT DEFAULT '',
        verification_url TEXT DEFAULT '',
        issued_at TEXT DEFAULT CURRENT_TIMESTAMP,
        revoked_at TEXT DEFAULT '',
        revocation_reason TEXT DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_rights_proofs (
        id SERIAL PRIMARY KEY,
        track_id TEXT NOT NULL,
        creator TEXT DEFAULT '',
        creation_method TEXT DEFAULT '',
        ai_tool TEXT DEFAULT '',
        ai_plan TEXT DEFAULT '',
        prompt TEXT DEFAULT '',
        third_party_sample TEXT DEFAULT '',
        commercial_allowed INTEGER DEFAULT 0,
        sublicense_allowed INTEGER DEFAULT 0,
        source_contract_id TEXT DEFAULT '',
        proof_url TEXT DEFAULT '',
        proof_file_hash TEXT DEFAULT '',
        tool_terms_url TEXT DEFAULT '',
        tool_terms_snapshot_at TEXT DEFAULT '',
        human_edit_log_url TEXT DEFAULT '',
        sample_clearance_files TEXT DEFAULT '',
        voice_release_files TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS soundbank_violation_reports (
        id SERIAL PRIMARY KEY,
        reported_url TEXT NOT NULL,
        track_id TEXT DEFAULT '',
        reporter_contact TEXT DEFAULT '',
        reason TEXT DEFAULT '',
        evidence_url TEXT DEFAULT '',
        status TEXT DEFAULT 'new',
        resolution TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('ALTER TABLE soundbank_orders ADD COLUMN IF NOT EXISTS provider_trade_no TEXT DEFAULT \'\'')
    c.execute('CREATE INDEX IF NOT EXISTS idx_soundbank_tracks_status ON soundbank_tracks (status)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_soundbank_orders_status_created ON soundbank_orders (payment_status, created_at DESC)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_soundbank_downloads_order ON soundbank_downloads (order_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_soundbank_private_assets_track ON soundbank_private_assets (track_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_soundbank_certificates_order ON soundbank_license_certificates (order_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_soundbank_rights_track ON soundbank_rights_proofs (track_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_soundbank_reports_status ON soundbank_violation_reports (status)')
    conn.commit()
    conn.close()


def _manifest_bool(value, default=False):
    text = str(value or '').strip().lower()
    if text in TRUE_VALUES or text in {'y', 'allow', 'allowed'}:
        return True
    if text in {'0', 'false', 'no', 'n', 'off', 'deny', 'denied', ''}:
        return bool(default)
    return bool(default)


def _manifest_int(value, default=0):
    text = str(value or '').strip()
    if not text:
        return int(default)
    try:
        return int(float(text))
    except Exception:
        return int(default)


def _manifest_clean(row, key, default=''):
    value = (row or {}).get(key, default)
    if value is None:
        return default
    return str(value).strip()


def _beta_manifest_paths():
    root = Path(__file__).resolve().parent
    return {
        'root': root,
        'manifest': root / 'docs' / 'soundbank_materials_beta_originals.csv',
        'assets': root / 'static' / 'soundbank_assets',
    }


def _beta_asset_master_path(asset_dir, row):
    preview = _manifest_clean(row, 'preview_audio_url')
    preview_name = Path(preview).name
    if preview_name.endswith('-preview.wav'):
        return asset_dir / preview_name.replace('-preview.wav', '-master.wav')
    return None


def seed_soundbank_beta_originals(get_db):
    paths = _beta_manifest_paths()
    manifest_path = paths['manifest']
    asset_dir = paths['assets']
    if not manifest_path.exists():
        print('[SoundBank beta seed] manifest missing: ' + str(manifest_path))
        return {'tracks': 0, 'licenses': 0, 'proofs': 0, 'assets': 0, 'skipped': True}

    with manifest_path.open(newline='', encoding='utf-8-sig') as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if any(str(value or '').strip() for value in row.values())
        ]
    if not rows:
        print('[SoundBank beta seed] manifest has no rows.')
        return {'tracks': 0, 'licenses': 0, 'proofs': 0, 'assets': 0, 'skipped': True}

    conn = get_db()
    try:
        c = conn.cursor()
        now = _tw_now()
        terms_html = '''
        <h1>萬語聲庫授權條款</h1>
        <p>買方取得指定素材之使用授權，不取得著作權、原始檔所有權、獨家權或 Content ID 登記權。</p>
        <p>素材可嵌入較大的作品，例如影片、Podcast、直播、課程、廣告、遊戲、App 或品牌社群內容；實際範圍以所購買方案為準。</p>
        <ul>
          <li>不得註冊 Content ID、YouTube CID、Facebook Rights Manager 或任何第三方權利管理系統。</li>
          <li>不得轉售、再授權、重新包裝成素材庫、模板、beat pack、SaaS 內容庫或 marketplace 商品。</li>
          <li>不得把音樂單獨上架 Spotify、Apple Music、YouTube Music、KKBOX、SoundCloud 等串流平台或變成可被他人下載的音樂商品。</li>
          <li>不得作為 AI 訓練資料、模型微調資料、資料集或聲音克隆來源。</li>
        </ul>
        <p>付款、下載、授權證明、退費與客服處理，以訂單頁、授權驗證連結與 SoundBank 客服/退費頁之最新說明為準。</p>
        '''
        c.execute(
            '''
            INSERT INTO soundbank_license_terms_versions
            (version, effective_date, terms_html, created_by, status, created_at)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (version) DO UPDATE SET
                terms_html=EXCLUDED.terms_html,
                status=EXCLUDED.status
            ''',
            ('beta-v1', now[:10], terms_html, 'codex-beta-seed', 'active', now),
        )

        counts = {'tracks': 0, 'licenses': 0, 'proofs': 0, 'assets': 0, 'skipped': False}
        for row in rows:
            track_id = _manifest_clean(row, 'id')
            if not track_id:
                continue
            c.execute(
                '''
                INSERT INTO soundbank_tracks
                (id,title,description,category,mood,bpm,duration_seconds,preview_audio_url,
                 download_audio_url,cover_image_url,status,rights_status,review_status,rights_score,
                 created_at,updated_at,published_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                    title=EXCLUDED.title,
                    description=EXCLUDED.description,
                    category=EXCLUDED.category,
                    mood=EXCLUDED.mood,
                    bpm=EXCLUDED.bpm,
                    duration_seconds=EXCLUDED.duration_seconds,
                    preview_audio_url=EXCLUDED.preview_audio_url,
                    download_audio_url=EXCLUDED.download_audio_url,
                    cover_image_url=EXCLUDED.cover_image_url,
                    status=EXCLUDED.status,
                    rights_status=EXCLUDED.rights_status,
                    review_status=EXCLUDED.review_status,
                    rights_score=EXCLUDED.rights_score,
                    updated_at=EXCLUDED.updated_at,
                    published_at=EXCLUDED.published_at
                ''',
                (
                    track_id,
                    _manifest_clean(row, 'title'),
                    _manifest_clean(row, 'description'),
                    _manifest_clean(row, 'category'),
                    _manifest_clean(row, 'mood'),
                    _manifest_int(_manifest_clean(row, 'bpm'), 0),
                    _manifest_int(_manifest_clean(row, 'duration_seconds'), 0),
                    _manifest_clean(row, 'preview_audio_url'),
                    _manifest_clean(row, 'download_audio_url'),
                    _manifest_clean(row, 'cover_image_url'),
                    _manifest_clean(row, 'status', 'draft') or 'draft',
                    _manifest_clean(row, 'rights_status', 'pending_review') or 'pending_review',
                    _manifest_clean(row, 'review_status', 'reviewing') or 'reviewing',
                    _manifest_int(_manifest_clean(row, 'rights_score'), 60),
                    now,
                    now,
                    now,
                ),
            )
            counts['tracks'] += 1

            license_specs = [
                ('personal', 'license_personal_price', 'usage_scope_personal', 0, 3),
                ('commercial', 'license_commercial_price', 'usage_scope_commercial', 1, 5),
                ('project', 'license_project_price', 'usage_scope_project', 1, 10),
            ]
            for license_type, price_key, scope_key, is_commercial, download_limit in license_specs:
                c.execute(
                    '''
                    INSERT INTO soundbank_licenses
                    (license_id, track_id, license_type, price, usage_scope, term, territory,
                     channel_limit, project_limit, download_limit, is_commercial,
                     content_id_prohibited, sublicense_prohibited, ai_training_prohibited,
                     distribution_restriction, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,'perpetual','worldwide',1,1,%s,%s,1,1,1,%s,%s,%s)
                    ON CONFLICT (track_id, license_type) DO UPDATE SET
                        price=EXCLUDED.price,
                        usage_scope=EXCLUDED.usage_scope,
                        download_limit=EXCLUDED.download_limit,
                        is_commercial=EXCLUDED.is_commercial,
                        distribution_restriction=EXCLUDED.distribution_restriction,
                        updated_at=EXCLUDED.updated_at
                    ''',
                    (
                        track_id + '-' + license_type,
                        track_id,
                        license_type,
                        _manifest_int(_manifest_clean(row, price_key), 0),
                        _manifest_clean(row, scope_key),
                        download_limit,
                        is_commercial,
                        _manifest_clean(row, 'distribution_restriction'),
                        now,
                        now,
                    ),
                )
                counts['licenses'] += 1

            c.execute('DELETE FROM soundbank_rights_proofs WHERE track_id=%s', (track_id,))
            c.execute(
                '''
                INSERT INTO soundbank_rights_proofs
                (track_id, creator, creation_method, ai_tool, ai_plan, prompt,
                 third_party_sample, commercial_allowed, sublicense_allowed,
                 source_contract_id, proof_url, proof_file_hash, tool_terms_url,
                 tool_terms_snapshot_at, human_edit_log_url, sample_clearance_files,
                 voice_release_files, notes, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''',
                (
                    track_id,
                    _manifest_clean(row, 'creator'),
                    _manifest_clean(row, 'creation_method'),
                    _manifest_clean(row, 'ai_tool'),
                    _manifest_clean(row, 'ai_plan'),
                    _manifest_clean(row, 'prompt'),
                    _manifest_clean(row, 'third_party_sample', 'none'),
                    1 if _manifest_bool(_manifest_clean(row, 'commercial_allowed'), False) else 0,
                    1 if _manifest_bool(_manifest_clean(row, 'sublicense_allowed'), False) else 0,
                    _manifest_clean(row, 'source_contract_id'),
                    _manifest_clean(row, 'proof_url'),
                    _manifest_clean(row, 'proof_file_hash'),
                    _manifest_clean(row, 'tool_terms_url'),
                    _manifest_clean(row, 'tool_terms_snapshot_at'),
                    _manifest_clean(row, 'human_edit_log_url'),
                    _manifest_clean(row, 'sample_clearance_files'),
                    _manifest_clean(row, 'voice_release_files'),
                    _manifest_clean(row, 'notes', 'beta original seed'),
                    now,
                    now,
                ),
            )
            counts['proofs'] += 1

            download_ref = _manifest_clean(row, 'download_audio_url')
            if download_ref.startswith('db://'):
                asset_id = download_ref[len('db://'):].strip('/')
                master_path = _beta_asset_master_path(asset_dir, row)
                if asset_id and master_path and master_path.exists():
                    data = master_path.read_bytes()
                    sha256 = hashlib.sha256(data).hexdigest().upper()
                    content_type = mimetypes.guess_type(str(master_path))[0] or 'audio/wav'
                    c.execute(
                        '''
                        INSERT INTO soundbank_private_assets
                        (asset_id, track_id, filename, content_type, storage_provider,
                         storage_key, byte_size, sha256, data, created_at, updated_at)
                        VALUES (%s,%s,%s,%s,'db',%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (asset_id) DO UPDATE SET
                            track_id=EXCLUDED.track_id,
                            filename=EXCLUDED.filename,
                            content_type=EXCLUDED.content_type,
                            storage_provider=EXCLUDED.storage_provider,
                            storage_key=EXCLUDED.storage_key,
                            byte_size=EXCLUDED.byte_size,
                            sha256=EXCLUDED.sha256,
                            data=EXCLUDED.data,
                            updated_at=EXCLUDED.updated_at
                        ''',
                        (
                            asset_id,
                            track_id,
                            master_path.name,
                            content_type,
                            asset_id,
                            len(data),
                            sha256,
                            psycopg2.Binary(data),
                            now,
                            now,
                        ),
                    )
                    counts['assets'] += 1

        conn.commit()
        print(
            '[SoundBank beta seed] '
            + str(counts['tracks']) + ' tracks, '
            + str(counts['licenses']) + ' licenses, '
            + str(counts['proofs']) + ' proofs, '
            + str(counts['assets']) + ' private assets.'
        )
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


PUBLIC_TRACK_FILTER = (
    "status='published' "
    "AND COALESCE(preview_audio_url,'')<>'' "
    "AND rights_status='verified' "
    "AND review_status='approved' "
    "AND EXISTS ("
    "SELECT 1 FROM soundbank_rights_proofs rp "
    "WHERE rp.track_id=soundbank_tracks.id "
    "AND COALESCE(rp.creator,'')<>'' "
    "AND COALESCE(rp.creation_method,'')<>'' "
    "AND COALESCE(rp.third_party_sample,'')<>'' "
    "AND COALESCE(rp.proof_file_hash,'')<>'' "
    "AND rp.commercial_allowed=1 "
    "AND rp.sublicense_allowed=1"
    ")"
)


def _tracks_from_db(get_db, include_all=False):
    where = '' if include_all else 'WHERE ' + PUBLIC_TRACK_FILTER
    rows = _fetch_all(
        get_db,
        f'''
        SELECT id, title, description, category, mood, bpm, duration_seconds,
               preview_audio_url, download_audio_url, cover_image_url, status,
               rights_status, review_status, rights_score, created_at, updated_at,
               published_at, retired_at
        FROM soundbank_tracks
        {where}
        ORDER BY created_at DESC, id ASC
        '''
    )
    if rows:
        return rows
    if include_all or _bool_env('SOUNDBANK_SHOW_STARTER_DEMOS', False):
        return starter_tracks()
    return []


def _track_from_db(get_db, track_id):
    track = _fetch_one(
        get_db,
        '''
        SELECT id, title, description, category, mood, bpm, duration_seconds,
               preview_audio_url, download_audio_url, cover_image_url, status,
               rights_status, review_status, rights_score, created_at, updated_at,
               published_at, retired_at
        FROM soundbank_tracks
        WHERE id=%s AND ''' + PUBLIC_TRACK_FILTER + '''
        ''',
        (track_id,)
    )
    if track:
        return track
    return None


def _rights_proof_for_track(get_db, track_id):
    return _fetch_one(
        get_db,
        '''
        SELECT track_id, creator, creation_method, ai_tool, ai_plan,
               third_party_sample, commercial_allowed, sublicense_allowed,
               source_contract_id, proof_url, proof_file_hash,
               tool_terms_url, tool_terms_snapshot_at, human_edit_log_url,
               sample_clearance_files, voice_release_files, notes, updated_at
        FROM soundbank_rights_proofs
        WHERE track_id=%s
          AND COALESCE(creator,'')<>''
          AND COALESCE(creation_method,'')<>''
          AND COALESCE(third_party_sample,'')<>''
          AND COALESCE(proof_file_hash,'')<>''
          AND commercial_allowed=1
          AND sublicense_allowed=1
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        ''',
        (track_id,)
    )


def _starter_track(track_id):
    for item in starter_tracks():
        if item['id'] == track_id:
            return item
    return None


def _licenses_for_track(get_db, track_id):
    rows = _fetch_all(
        get_db,
        '''
        SELECT license_id, track_id, license_type, price, usage_scope, term,
               territory, channel_limit, project_limit, download_limit,
               is_commercial, content_id_prohibited, sublicense_prohibited,
               ai_training_prohibited, distribution_restriction
        FROM soundbank_licenses
        WHERE track_id=%s
        ORDER BY price ASC
        ''',
        (track_id,)
    )
    if rows:
        return rows
    if _starter_track(track_id):
        return _demo_licenses(track_id)
    return []


def _demo_licenses(track_id):
    return [
        {
            'license_id': 'demo-personal',
            'track_id': track_id,
            'license_type': 'personal',
            'price': 299,
            'usage_scope': '個人非商業內容、作品集展示、私人審稿與練習專案。',
            'download_limit': 3,
        },
        {
            'license_id': 'demo-commercial',
            'track_id': track_id,
            'license_type': 'commercial',
            'price': 999,
            'usage_scope': '單一商業專案，可用於 YouTube、Podcast、直播、課程、廣告、遊戲、App 或品牌社群內容。',
            'download_limit': 5,
        },
        {
            'license_id': 'demo-project',
            'track_id': track_id,
            'license_type': 'project',
            'price': 2999,
            'usage_scope': '單一品牌、活動或客戶專案，允許較廣通路發布但仍不得轉售或再授權。',
            'download_limit': 10,
        },
    ]


SOUNDBANK_SITE_NAME = '萬語聲庫 SoundBank'
SOUNDBANK_DEFAULT_PUBLIC_BASE_URL = 'https://one1stars-line-bot.onrender.com'
SOUNDBANK_DEFAULT_DESCRIPTION = (
    '萬語聲庫 SoundBank 提供 Podcast、短影音、直播、AI 電台與品牌內容可試聽、可購買、附憑證的音樂授權。'
)


def _public_base_url():
    base = str(os.environ.get('SOUNDBANK_PUBLIC_BASE_URL') or SOUNDBANK_DEFAULT_PUBLIC_BASE_URL).strip()
    base = base.rstrip('/')
    if base.endswith('/soundbank'):
        base = base[:-len('/soundbank')]
    if not base:
        base = SOUNDBANK_DEFAULT_PUBLIC_BASE_URL
    if not base.startswith(('http://', 'https://')):
        base = 'https://' + base.lstrip('/')
    return base.rstrip('/')


def _canonical_url(canonical_path=None):
    try:
        path = str(canonical_path or request.path or '/soundbank').strip()
    except Exception:
        path = str(canonical_path or '/soundbank').strip()
    if not path:
        path = '/soundbank'
    if path.startswith('http://') or path.startswith('https://'):
        return path
    if not path.startswith('/'):
        path = '/' + path
    return _public_base_url() + path


def _json_ld_script(json_ld):
    if not json_ld:
        return ''
    payload = json_ld
    if isinstance(payload, list):
        payload = {'@context': 'https://schema.org', '@graph': payload}
    elif isinstance(payload, dict) and '@context' not in payload:
        payload = dict(payload)
        payload['@context'] = 'https://schema.org'
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return '  <script type="application/ld+json">' + html.escape(raw, quote=False) + '</script>\n'


def _webpage_schema(name, description, canonical_path=None):
    url = _canonical_url(canonical_path)
    return {
        '@type': 'WebPage',
        'name': name,
        'url': url,
        'description': description,
        'isPartOf': {
            '@type': 'WebSite',
            'name': SOUNDBANK_SITE_NAME,
            'url': _canonical_url('/soundbank'),
        },
    }


def _duration_iso_8601(seconds):
    seconds = int(seconds or 0)
    if seconds <= 0:
        return ''
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    out = 'PT'
    if hours:
        out += str(hours) + 'H'
    if minutes:
        out += str(minutes) + 'M'
    if secs or out == 'PT':
        out += str(secs) + 'S'
    return out


def _meta_description(value):
    text = ' '.join(str(value or SOUNDBANK_DEFAULT_DESCRIPTION).split())
    if len(text) > 160:
        return text[:157].rstrip() + '...'
    return text


def _soundbank_manifest_payload():
    return {
        'name': '萬語聲庫 SoundBank',
        'short_name': '萬語聲庫',
        'description': '試聽、選授權、付款下載與保存授權憑證的音樂素材 Web App。',
        'start_url': '/soundbank?source=pwa',
        'scope': '/soundbank',
        'display': 'standalone',
        'background_color': '#dff7f2',
        'theme_color': '#0f766e',
        'orientation': 'portrait-primary',
        'lang': 'zh-Hant-TW',
        'categories': ['music', 'business', 'productivity'],
        'icons': [
            {
                'src': '/static/soundbank_assets/soundbank-app-icon-192.png',
                'sizes': '192x192',
                'type': 'image/png',
                'purpose': 'any maskable',
            },
            {
                'src': '/static/soundbank_assets/soundbank-app-icon-512.png',
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'any maskable',
            },
        ],
        'shortcuts': [
            {
                'name': '瀏覽素材',
                'short_name': '素材',
                'description': '查看可試聽素材',
                'url': '/soundbank/tracks',
            },
            {
                'name': '授權怎麼選',
                'short_name': '授權',
                'description': '查看授權方案',
                'url': '/soundbank/license',
            },
        ],
    }


def _soundbank_service_worker_js():
    public_assets = json.dumps(SOUNDBANK_PWA_PUBLIC_ASSETS, ensure_ascii=True)
    private_prefixes = json.dumps(SOUNDBANK_PWA_PRIVATE_PREFIXES, ensure_ascii=True)
    cache_name = 'soundbank-pwa-' + SOUNDBANK_PWA_CACHE_VERSION
    return """const CACHE_NAME = '""" + cache_name + """';
const PUBLIC_ASSETS = """ + public_assets + """;
const PRIVATE_PREFIXES = """ + private_prefixes + """;
const PUBLIC_PAGE_PATHS = new Set(['/soundbank', '/soundbank/tracks', '/soundbank/license', '/soundbank/support']);
const PUBLIC_ASSET_PATHS = new Set(PUBLIC_ASSETS);

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PUBLIC_ASSETS))
      .catch(() => undefined)
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key.startsWith('soundbank-pwa-') && key !== CACHE_NAME)
        .map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

function isPrivateSoundBankPath(pathname) {
  return PRIVATE_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function isCacheableStaticAsset(pathname) {
  return pathname.startsWith('/static/soundbank_assets/') && PUBLIC_ASSET_PATHS.has(pathname);
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) {
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkFirst(request, fallbackPath) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    return caches.match(request).then((cached) => cached || caches.match(fallbackPath));
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (isPrivateSoundBankPath(url.pathname)) return;
  if (PUBLIC_PAGE_PATHS.has(url.pathname)) {
    event.respondWith(networkFirst(request, '/soundbank'));
    return;
  }
  if (isCacheableStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(request));
  }
});
"""


def _track_list_schema(tracks, page_name, description, canonical_path):
    items = []
    for index, track in enumerate((tracks or [])[:12], start=1):
        track_id = str(track.get('id') or '').strip()
        if not track_id:
            continue
        items.append({
            '@type': 'ListItem',
            'position': index,
            'url': _canonical_url('/soundbank/tracks/' + urllib.parse.quote(track_id, safe='')),
            'name': _track_public_title(track),
        })
    graph = [_webpage_schema(page_name, description, canonical_path)]
    if items:
        graph.append({
            '@type': 'ItemList',
            'name': '可試聽音樂素材',
            'itemListElement': items,
        })
    return graph


def _track_detail_schema(track, licenses, description):
    title = _track_public_title(track)
    track_id = str(track.get('id') or '').strip()
    url = _canonical_url('/soundbank/tracks/' + urllib.parse.quote(track_id, safe=''))
    duration = _duration_iso_8601(_track_duration_seconds(track))
    offers = []
    for license_row in licenses or []:
        try:
            price = int(license_row.get('price') or 0)
        except Exception:
            price = 0
        if price <= 0:
            continue
        offers.append({
            '@type': 'Offer',
            'name': _license_label(license_row.get('license_type')),
            'price': price,
            'priceCurrency': 'TWD',
            'availability': 'https://schema.org/InStock',
            'url': url,
        })
    music = {
        '@type': 'MusicRecording',
        'name': title,
        'url': url,
        'description': description,
        'genre': _category_label(track.get('category')),
        'inLanguage': 'zh-Hant',
    }
    if duration:
        music['duration'] = duration
    product = {
        '@type': 'Product',
        'name': title + ' 音樂授權',
        'description': description,
        'category': _category_label(track.get('category')),
        'brand': {'@type': 'Brand', 'name': SOUNDBANK_SITE_NAME},
    }
    if offers:
        product['offers'] = offers
    return [_webpage_schema(title, description, '/soundbank/tracks/' + track_id), music, product]


def _page(title, body, active='soundbank', description=None, canonical_path=None, json_ld=None, robots=None):
    nav_items = [
        ('/soundbank', '首頁'),
        ('/soundbank/tracks', '素材'),
        ('/soundbank/license', '授權'),
        ('/soundbank/downloads', '下載'),
        ('/soundbank/support', '客服/退費'),
        ('/soundbank/report-misuse', '通報'),
    ]
    nav = ''.join(
        '<a class="' + ('active' if label == active else '') + '" href="' + href + '">' + label + '</a>'
        for href, label in nav_items
    )
    page_description = _meta_description(description)
    canonical = _canonical_url(canonical_path)
    full_title = _esc(title) + '｜萬語聲庫'
    robots_meta = ''
    if robots:
        robots_meta = '  <meta name="robots" content="' + _esc(robots) + '">\n'
    schema = json_ld if json_ld is not None else _webpage_schema(title, page_description, canonical_path)
    return '''<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#0f766e">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="萬語聲庫">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <meta name="description" content="''' + _esc(page_description) + '''">
''' + robots_meta + '''  <link rel="canonical" href="''' + _esc(canonical) + '''">
  <link rel="manifest" href="/soundbank.webmanifest">
  <link rel="icon" type="image/png" sizes="192x192" href="/static/soundbank_assets/soundbank-app-icon-192.png">
  <link rel="apple-touch-icon" href="/static/soundbank_assets/soundbank-app-icon-192.png">
  <meta property="og:site_name" content="''' + _esc(SOUNDBANK_SITE_NAME) + '''">
  <meta property="og:type" content="website">
  <meta property="og:title" content="''' + full_title + '''">
  <meta property="og:description" content="''' + _esc(page_description) + '''">
  <meta property="og:url" content="''' + _esc(canonical) + '''">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="''' + full_title + '''">
  <meta name="twitter:description" content="''' + _esc(page_description) + '''">
''' + _json_ld_script(schema) + '''  <title>''' + full_title + '''</title>
  <style>
    :root{color-scheme:light;--ink:#17202a;--muted:#64748b;--line:#d8dee8;--brand:#0f766e;--brand-dark:#115e59;--soft:#f6f8fb;--warn:#9a3412}
    *,*:before,*:after{box-sizing:border-box}
    html,body{width:100%;max-width:100%;overflow-x:hidden}
    body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",Arial,sans-serif;color:var(--ink);background:#e8f7f3;line-height:1.65;position:relative;min-height:100vh}
    body:before{content:"";position:fixed;z-index:0;inset:0;background-image:url('/static/soundbank_assets/soundbank-fullpage-wallpaper.png');background-repeat:repeat-y;background-size:min(2200px,146vw) auto;background-position:center top;opacity:.48;pointer-events:none}
    body:after{content:"";position:fixed;z-index:0;inset:0;background:linear-gradient(90deg,rgba(255,255,255,.44) 0%,rgba(255,255,255,.24) 24%,rgba(255,255,255,.20) 58%,rgba(255,255,255,.38) 100%),linear-gradient(180deg,rgba(255,255,255,.12) 0%,rgba(255,255,255,.20) 100%);pointer-events:none}
    a{color:var(--brand);text-decoration:none;overflow-wrap:anywhere}
    .top{border-bottom:1px solid rgba(196,214,211,.74);background:rgba(253,255,254,.84);backdrop-filter:saturate(1.18) blur(12px);box-shadow:0 14px 34px rgba(15,23,42,.06);position:sticky;top:0;z-index:10}
    .bar{width:100%;max-width:1120px;margin:0 auto;padding:14px 20px;display:flex;align-items:center;justify-content:space-between;gap:18px}
    .brand{font-weight:800;letter-spacing:0;min-width:0;overflow-wrap:anywhere}
    .nav{display:flex;gap:14px;flex-wrap:wrap;font-size:14px;min-width:0}
    .nav a{color:#334155;padding:6px 2px;border-bottom:2px solid transparent;white-space:nowrap}
    .nav a.active{color:var(--brand-dark);border-color:var(--brand-dark)}
    main{width:100%;max-width:1120px;margin:0 auto;padding:28px 20px 56px;position:relative;z-index:1;isolation:isolate}
    main:before{content:"";position:absolute;z-index:-1;inset:0 -18px;background:linear-gradient(180deg,rgba(255,255,255,.28),rgba(255,255,255,.16) 44%,rgba(255,255,255,.20));border-left:1px solid rgba(255,255,255,.58);border-right:1px solid rgba(255,255,255,.58);box-shadow:0 40px 90px rgba(15,23,42,.05);pointer-events:none}
    .hero{padding:34px 0 24px;border-bottom:1px solid var(--line)}
    .visual-hero{position:relative;isolation:isolate;overflow:hidden;min-height:390px;padding:54px 0 42px;background:linear-gradient(90deg,rgba(255,255,255,.74) 0%,rgba(255,255,255,.46) 42%,rgba(255,255,255,.14) 100%)}
    .visual-hero:before{content:"";position:absolute;z-index:-2;inset:0;left:24%;background-image:linear-gradient(90deg,rgba(255,255,255,.28) 0%,rgba(255,255,255,.07) 36%,rgba(255,255,255,0) 76%),url('/static/soundbank_assets/soundbank-hero-visual.png');background-repeat:no-repeat;background-size:cover;background-position:center right;opacity:.96;pointer-events:none}
    .visual-hero:after{content:"";position:absolute;z-index:-1;inset:auto 0 0 0;height:120px;background:linear-gradient(180deg,rgba(223,247,242,0),rgba(223,247,242,.18));pointer-events:none}
    .visual-hero h1,.visual-hero .lead,.visual-hero .hero-proof,.visual-hero .stack,.visual-hero .hero-actions,.visual-hero .decision-panel{position:relative}
    h1{font-size:34px;line-height:1.2;margin:0 0 12px;letter-spacing:0}
    h2{font-size:22px;margin:34px 0 12px;letter-spacing:0}
    h3{font-size:17px;margin:18px 0 6px;letter-spacing:0}
    main,main *,footer,footer *{min-width:0}
    main *{max-width:100%}
    h1,h2,h3,p,li,th,td,label,.card,.panel,.notice,.fact,.trust-item,.pill,.lead,.meta,footer{overflow-wrap:anywhere;word-break:break-word;line-break:anywhere}
    ul,ol{box-sizing:border-box;max-width:100%;padding-left:22px;margin:0 0 14px}
    li{margin-bottom:7px}
    p{margin:0 0 12px}
    .lead{font-size:18px;color:#334155;max-width:820px}
    .hero-lead{max-width:760px}
    .hero-proof{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
    .proof-chip{display:inline-flex;align-items:center;border:1px solid #bae6fd;background:#f0f9ff;color:#075985;border-radius:999px;padding:5px 10px;font-size:13px;font-weight:700}
    .hero-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:20px}
    .hero-action-note{font-size:13px;color:#475569;max-width:360px}
    .decision-panel{border:1px solid rgba(45,212,191,.82);background:rgba(248,255,253,.86);border-radius:8px;padding:16px;margin:18px 0 4px;box-shadow:0 18px 42px rgba(15,23,42,.07);backdrop-filter:blur(7px)}
    .decision-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:10px}
    .decision-item{border:1px solid rgba(203,213,225,.86);border-radius:8px;background:rgba(255,255,255,.90);padding:12px}
    .decision-item strong{display:block;color:#0f172a;margin-bottom:4px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;min-width:0}
    .card{border:1px solid rgba(196,214,211,.82);border-radius:8px;padding:16px;background:rgba(255,255,255,.88);box-shadow:0 14px 32px rgba(15,23,42,.06);backdrop-filter:blur(7px)}
    .card.compact h3{margin-top:0}
    .section-kicker{display:inline-flex;align-items:center;border:1px solid #99f6e4;background:#f0fdfa;color:#115e59;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:900;margin-bottom:8px}
    .page-head{max-width:760px;margin-bottom:18px}
    .page-head .lead{margin-top:8px}
    .section-lead{color:#475569;max-width:760px}
    .track-card{display:flex;flex-direction:column;gap:12px}
    .track-card:hover,.scenario-card:hover,.license-shortcut:hover{border-color:#5eead4;box-shadow:0 18px 44px rgba(15,118,110,.12)}
    .track-card h3{font-size:20px;line-height:1.25;margin:0}
    .track-eyebrow{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:13px}
    .duration-badge{display:inline-flex;align-items:center;border:1px solid #5eead4;background:#ccfbf1;color:#0f3f3a;border-radius:999px;padding:5px 11px;font-weight:900}
    .track-copy{font-size:15px;color:#334155;margin:0}
    .track-facts{display:flex;gap:6px;flex-wrap:wrap}
    .track-buyline{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:10px}
    .track-price{font-weight:900;color:#0f172a}
    .scenario-card{display:flex;flex-direction:column;gap:10px;min-height:160px}
    .scenario-top{display:flex;align-items:center;justify-content:space-between;gap:10px}
    .scenario-count{font-size:13px;font-weight:900;color:#115e59;border:1px solid #99f6e4;background:#f0fdfa;border-radius:999px;padding:3px 9px;white-space:nowrap}
    .scenario-card p{margin-bottom:0}
    .scenario-cta{margin-top:auto;font-weight:900;color:var(--brand-dark)}
    .license-cards{grid-template-columns:repeat(3,minmax(0,1fr))}
    .license-shortcut{display:flex;flex-direction:column;gap:8px}
    .license-fit{font-size:13px;color:#475569;border-top:1px solid var(--line);padding-top:8px;margin-top:auto}
    .audio-box{width:100%}
    .audio-summary{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:2px 0 6px;color:#334155;font-size:13px}
    .audio-summary strong{font-size:15px;color:#0f172a}
    .audio-duration{font-weight:900;color:#115e59}
    .audio-caption{font-size:13px;color:#475569;margin:0 0 5px}
    .quick-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:18px 0}
    .quick-card{border:1px solid rgba(196,214,211,.82);border-radius:8px;padding:12px;background:rgba(255,255,255,.88);box-shadow:0 12px 28px rgba(15,23,42,.055);backdrop-filter:blur(7px)}
    .quick-card strong{display:block;color:#0f172a;margin-bottom:2px}
    .support-checklist{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
    .support-checklist .card{padding:14px}
    .support-checklist .meta{line-height:1.75}
    details.policy-details{border:1px solid rgba(203,213,225,.88);border-radius:8px;background:rgba(255,255,255,.92);margin-top:12px;padding:10px 12px;box-shadow:0 12px 28px rgba(15,23,42,.055);backdrop-filter:blur(7px)}
    details.policy-details summary{cursor:pointer;font-weight:800;color:var(--brand-dark)}
    .split{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(280px,.85fr);gap:18px;align-items:start;min-width:0;margin-top:34px}
    .split h2:first-child{margin-top:0}
    .wedge-panel{display:block;margin-top:34px}
    .wedge-head{max-width:760px}
    .wedge-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-top:16px}
    .principles-panel{background:rgba(246,251,249,.92)}
    .panel{border:1px solid rgba(196,214,211,.82);border-radius:8px;padding:18px;background:rgba(251,253,255,.88);box-shadow:0 16px 36px rgba(15,23,42,.06);backdrop-filter:blur(7px)}
    .steps{counter-reset:step;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
    .step{border:1px solid rgba(196,214,211,.82);border-radius:8px;padding:14px;background:rgba(255,255,255,.88);box-shadow:0 12px 28px rgba(15,23,42,.055);backdrop-filter:blur(7px)}
    .step h3{display:flex;gap:8px;align-items:center;margin-top:0}
    .step h3:before{counter-increment:step;content:counter(step);display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:999px;background:#0f766e;color:#fff;font-size:13px;flex:0 0 auto}
    .trust-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:18px 0}
    .trust-item{border:1px solid rgba(196,214,211,.82);border-radius:8px;padding:12px;background:rgba(255,255,255,.88);box-shadow:0 12px 28px rgba(15,23,42,.055);backdrop-filter:blur(7px)}
    .trust-item strong{display:block;color:#0f172a}
    .kicker{font-size:12px;font-weight:800;color:var(--brand-dark);letter-spacing:0;text-transform:uppercase;margin-bottom:8px}
    .price{font-size:24px;font-weight:800;color:#0f172a;margin:4px 0 8px}
    .list{margin:10px 0 0;padding-left:18px}
    .list li{margin:4px 0}
    .meta{color:var(--muted);font-size:13px}
    .pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:3px 9px;font-size:12px;color:#475569;background:rgba(255,255,255,.92);margin:0 5px 6px 0}
    .pill.ok{border-color:#99f6e4;background:#f0fdfa;color:#115e59}
    .pill.warn{border-color:#fed7aa;background:#fff7ed;color:#9a3412}
    .button{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--brand-dark);background:var(--brand-dark);color:#fff;border-radius:6px;padding:9px 13px;font-weight:700;min-height:40px;max-width:100%;text-align:center;white-space:normal}
    .button.secondary{background:rgba(255,255,255,.95);color:var(--brand-dark)}
    .stack{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
    .notice{border-left:4px solid var(--brand);background:rgba(240,253,250,.92);padding:12px 14px;border-radius:6px;margin:16px 0;color:#134e4a;box-shadow:0 14px 30px rgba(15,23,42,.055);backdrop-filter:blur(7px)}
    .warn{border-left-color:var(--warn);background:#fff7ed;color:#7c2d12}
    .facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin:16px 0}
    .fact{border:1px solid rgba(196,214,211,.82);border-radius:8px;padding:12px;background:rgba(251,253,255,.88);box-shadow:0 12px 28px rgba(15,23,42,.055);backdrop-filter:blur(7px)}
    .fact strong{display:block;font-size:12px;color:var(--muted);margin-bottom:3px}
    .proof-code{display:block;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;line-height:1.45;overflow-wrap:anywhere}
    table{width:100%;max-width:100%;border-collapse:collapse;border:1px solid var(--line);border-radius:8px;overflow:hidden}
    th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
    th{background:var(--soft);font-size:13px;color:#334155}
    .license-table td:last-child{width:150px}
    form{display:grid;gap:12px;width:100%;max-width:720px;min-width:0}
    label{font-weight:700;font-size:14px}
    input,select,textarea{width:100%;min-width:0;border:1px solid var(--line);border-radius:6px;padding:9px 10px;font:inherit}
    textarea{min-height:120px}
    audio{width:100%;margin-top:4px}
    footer{border-top:1px solid var(--line);padding:20px;color:var(--muted);font-size:13px;position:relative;z-index:1;background:rgba(255,255,255,.72);backdrop-filter:blur(8px)}
    @media(max-width:1020px){.wedge-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
    @media(max-width:780px){.split{display:block}.split>*{width:100%;max-width:100%;margin-bottom:14px}}
    @media(max-width:700px){
      .bar{align-items:flex-start;flex-direction:column;padding:12px 14px;gap:10px}
      .brand{font-size:17px}
      .nav{width:100%;flex-wrap:nowrap;gap:12px;overflow-x:auto;padding-bottom:2px;-webkit-overflow-scrolling:touch}
      .nav a{flex:0 0 auto;padding:8px 0}
      main{width:calc(100% - 36px);max-width:calc(100% - 36px);margin:0 auto;padding:22px 0 48px}
      main:before{inset:0 -18px;background:linear-gradient(180deg,rgba(255,255,255,.22),rgba(255,255,255,.10) 44%,rgba(255,255,255,.20))}
      .hero{padding-top:18px}
      .visual-hero{width:100%;max-width:100%;min-height:auto;padding:174px 14px 26px;overflow:hidden}
      body:before{background-size:940px auto;background-position:center 72px;opacity:.50}
      body:after{background:linear-gradient(180deg,rgba(255,255,255,.30) 0%,rgba(255,255,255,.42) 34%,rgba(255,255,255,.34) 100%)}
      .visual-hero{background:linear-gradient(180deg,rgba(255,255,255,.68) 0%,rgba(255,255,255,.44) 56%,rgba(255,255,255,.22) 100%)}
      .visual-hero:before{left:0;right:0;bottom:auto;height:190px;background-image:linear-gradient(180deg,rgba(255,255,255,0) 0%,rgba(255,255,255,.03) 46%,rgba(247,251,250,.32) 100%),url('/static/soundbank_assets/soundbank-hero-visual.png');background-size:cover;background-position:70% center}
      .visual-hero:after{display:none}
      .visual-hero h1,.visual-hero .lead{width:auto;max-width:min(100%,21rem)}
      .visual-hero .hero-proof,.visual-hero .stack,.visual-hero .hero-actions,.visual-hero .decision-panel{width:100%;max-width:100%}
      h1{font-size:24px;line-height:1.3}
      h2{font-size:20px;margin-top:26px}
      .lead{font-size:14.5px;line-height:1.72}
      .hero-lead{max-width:100%}
      main,main *{min-width:0}
      main section,.page-head,.quick-grid{width:100%;max-width:100%}
      .page-head .lead{display:block;width:100%;max-width:100%;white-space:normal}
      .grid,.trust-strip,.facts,.decision-grid,.wedge-grid,.license-cards{grid-template-columns:1fr}
      .quick-grid,.support-checklist{grid-template-columns:1fr}
      .steps{grid-template-columns:1fr}
      .hero-proof{display:grid;grid-template-columns:1fr;gap:8px;width:100%}
      .proof-chip{justify-content:center;width:100%;min-width:0;text-align:center;padding-left:8px;padding-right:8px}
      .card,.panel,.decision-panel{padding:14px}
      .card,.panel,.notice,.fact,.trust-item,.quick-card,.decision-panel,.decision-item,.step{width:100%;max-width:100%}
      .lead,.panel p,.card p,.quick-card .meta,.trust-item .meta,.decision-item .meta{max-width:100%}
      main h1,main h2,main h3,main p,main li,main .notice,main .card,main .panel,main .fact,main .trust-item,main .quick-card,main .decision-item,main .meta,main th,main td,footer{overflow-wrap:anywhere;word-break:normal;line-break:anywhere}
      .pill,.proof-chip{white-space:normal}
      .stack{align-items:stretch;width:100%;display:grid;grid-template-columns:1fr;gap:10px}
      .stack .button{width:100%;padding-left:10px;padding-right:10px}
      .hero-actions{display:grid;grid-template-columns:1fr;gap:8px}
      .hero-action-note{text-align:center;max-width:100%}
      .stack .button,form .button,.track-buyline .button{width:100%}
      .track-card{gap:10px}
      .track-card h3{font-size:18px}
      .track-eyebrow{align-items:flex-start;justify-content:flex-start}
      .audio-summary{align-items:flex-start;flex-direction:column;gap:2px}
      .track-buyline{align-items:stretch}
      table{table-layout:fixed}
      tbody th{width:34%}
      th,td{min-width:0;max-width:100%;padding:9px;white-space:normal;overflow-wrap:anywhere;word-break:break-word}
      table:not(.license-table){border:0;border-collapse:separate}
      table:not(.license-table) tbody,table:not(.license-table) tr,table:not(.license-table) th,table:not(.license-table) td{display:block;width:100%}
      table:not(.license-table) tr{border:1px solid var(--line);border-radius:8px;margin-bottom:10px;background:rgba(255,255,255,.94);overflow:hidden}
      table:not(.license-table) th{border-bottom:1px solid var(--line);background:var(--soft)}
      table:not(.license-table) td{border-bottom:0}
      .license-table{border:0;border-collapse:separate}
      .license-table thead{display:none}
      .license-table tbody,.license-table tr,.license-table td{display:block;width:100%}
      .license-table tr{border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:10px;background:rgba(255,255,255,.94)}
      .license-table td{border-bottom:0;padding:5px 0}
      .license-table td:before{content:attr(data-label);display:block;font-size:12px;font-weight:800;color:var(--muted);margin-bottom:2px}
      .license-table td:last-child{width:100%;padding-top:8px}
      .license-table .button{width:100%}
      footer{padding:18px 14px}
      footer div{padding:0!important}
    }
    @media(max-width:500px){
      main{width:min(354px,calc(100vw - 36px));max-width:min(354px,calc(100vw - 36px));margin-left:18px;margin-right:18px}
      .page-head .lead,.notice{font-size:14px;line-height:1.72}
    }
  </style>
</head>
<body>
  <header class="top"><div class="bar"><a class="brand" href="/soundbank">萬語聲庫 SoundBank</a><nav class="nav">''' + nav + '''</nav></div></header>
  <main>''' + body + '''</main>
  <footer><div style="max-width:1120px;margin:0 auto;padding:0 20px">萬語聲庫提供的是音樂素材使用授權，不移轉著作權。正式條款以上線版本為準。</div></footer>
  <script>
    (function(){
      if (!('serviceWorker' in navigator)) return;
      window.addEventListener('load', function(){
        navigator.serviceWorker.register('/soundbank-sw.js', {scope: '/soundbank'}).catch(function(){});
      });
    })();
  </script>
</body>
</html>'''


CATEGORY_LABELS = {
    'Podcast BGM': '訪談與說明底樂',
    'Course BGM': '課程陪聽底樂',
    'AI radio stinger': '節目開場與轉場',
    'Short-form music': '短影音開場起伏',
    'Calm ambient': '專注安靜氛圍',
    'Tech underscore': '產品展示科技底',
    'Livestream loop': '直播等待循環',
    'Brand social': '品牌社群配樂',
}

TRACK_TITLE_PREFIXES = {
    'Podcast BGM': '人聲內容底樂',
    'Course BGM': '課程陪聽底樂',
    'AI radio stinger': '節目開場轉場',
    'Short-form music': '短影音配樂',
    'Calm ambient': '安靜空間底樂',
    'Tech underscore': '科技展示底樂',
    'Livestream loop': '直播等待底樂',
    'Brand social': '品牌社群底樂',
}

TRACK_PUBLIC_COPY = {
    'SB-BETA-PODCAST-001': {
        'title': '人聲暖底：開場第一段不空',
        'copy': '適合 Podcast 開頭、品牌說明和課程前言，讓人聲先站穩，不會乾乾地開始。',
    },
    'SB-BETA-AIRADIO-001': {
        'title': '節目亮相：三秒開場識別',
        'copy': '適合 AI 電台、資訊節目和短更新開場，快速讓聽眾知道段落開始了。',
    },
    'SB-BETA-SHORTS-001': {
        'title': '商品登場：一秒變有感',
        'copy': '適合商品短片、reels 開頭和快速展示，讓畫面一出來就有節奏。',
    },
    'SB-BETA-CALM-001': {
        'title': '安靜等待：畫面先沉下來',
        'copy': '適合等待畫面、溫和旁白和冥想前奏，讓觀眾先安靜進入內容。',
    },
    'SB-BETA-TECH-001': {
        'title': '產品脈動：介面更有速度',
        'copy': '適合 SaaS、工具展示和介面錄影，讓操作畫面有科技感但不吵。',
    },
    'SB-BETA-PODCAST-002': {
        'title': '訪談陪襯：對話更好入口',
        'copy': '適合訪談、創作者更新和教育型旁白，讓對話有溫度又不搶話。',
    },
    'SB-BETA-PODCAST-003': {
        'title': '商務解說：品牌聲音更可信',
        'copy': '適合商務簡報、創辦人旁白和服務介紹，讓內容聽起來更穩、更可信。',
    },
    'SB-BETA-PODCAST-004': {
        'title': '故事旁白：案例轉場慢慢推',
        'copy': '適合案例故事、紀錄片式介紹和產品課程，幫段落自然往下走。',
    },
    'SB-BETA-AIRADIO-002': {
        'title': '新聞快切：重點進來了',
        'copy': '適合標題播報、段落插入和資訊快訊，讓節奏明確、轉場俐落。',
    },
    'SB-BETA-AIRADIO-003': {
        'title': '提醒音：一句話前的亮點',
        'copy': '適合提示、贊助段落、短提醒和頻道 bumper，讓重要訊息被聽見。',
    },
    'SB-BETA-AIRADIO-004': {
        'title': '知識更新：乾淨未來感',
        'copy': '適合 AI 摘要、版本更新和知識節目轉場，科技感清楚但不刺耳。',
    },
    'SB-BETA-SHORTS-002': {
        'title': '開箱亮點：前後對比更順',
        'copy': '適合開箱、前後對比和短教學，讓節奏輕快，觀眾更容易看完。',
    },
    'SB-BETA-SHORTS-003': {
        'title': '生活短片：節奏乾淨不搶畫面',
        'copy': '適合美食、生活紀錄和社群短片，補上節奏但保留畫面主角。',
    },
    'SB-BETA-SHORTS-004': {
        'title': '行動呼籲：結尾推一把',
        'copy': '適合購物短片、App 教學和 CTA 結尾，讓最後一拍更有記憶點。',
    },
    'SB-BETA-SHORTS-005': {
        'title': '社群清單：字幕跟著跳',
        'copy': '適合清單影片、字幕短片和社群說明，活潑但不會壓過旁白。',
    },
    'SB-BETA-CALM-002': {
        'title': '冥想前奏：留一點空氣',
        'copy': '適合身心靈、諮詢內容和安靜等待頁，讓畫面多一點空間感。',
    },
    'SB-BETA-CALM-003': {
        'title': '溫柔收尾：把故事放慢',
        'copy': '適合片尾、慢教學和溫和敘事，讓內容結束得更柔順。',
    },
    'SB-BETA-CALM-004': {
        'title': '直播休息：安靜不尷尬',
        'copy': '適合直播暫停、呼吸練習和低干擾旁白，安靜但不空白。',
    },
    'SB-BETA-TECH-002': {
        'title': '軟體導覽：流程清楚往前走',
        'copy': '適合產品 onboarding、儀表板介紹和版本說明，讓操作節奏更清楚。',
    },
    'SB-BETA-TECH-003': {
        'title': '數據解說：理性但不冰冷',
        'copy': '適合數據分析、金融科技和功能教學，保留專業感也不單調。',
    },
    'SB-BETA-TECH-004': {
        'title': 'AI 工具展示：乾淨科技亮點',
        'copy': '適合 AI 工具、App walkthrough 和新功能展示，讓畫面更有完成度。',
    },
    'SB-BETA-COURSE-001': {
        'title': '課程鋪底：知識不被音樂搶走',
        'copy': '適合線上課、投影片和教學旁白，穩定支撐內容，不干擾學習。',
    },
    'SB-BETA-COURSE-002': {
        'title': '章節轉場：學習節奏更平穩',
        'copy': '適合章節切換、螢幕錄影和模組介紹，讓課程段落銜接更自然。',
    },
    'SB-BETA-LIVE-001': {
        'title': '開播等待：聊天室慢慢進場',
        'copy': '適合直播開場、倒數等待和中場轉換，讓觀眾進場時不冷場。',
    },
    'SB-BETA-LIVE-002': {
        'title': '直播中場：休息不冷場',
        'copy': '適合購物直播、Q&A 空檔和創作者休息畫面，輕快但不催促。',
    },
    'SB-BETA-BRAND-001': {
        'title': '品牌形象：輕快可信的第一印象',
        'copy': '適合品牌短片、服務說明和網站宣傳，讓第一印象更乾淨專業。',
    },
    'SB-BETA-BRAND-002': {
        'title': '客戶故事：穩穩把價值說完',
        'copy': '適合客戶案例、產品訊息和活動宣傳，聽起來有信任感又不沉重。',
    },
}

MOOD_LABELS = {
    'warm, steady': '溫暖穩定',
    'tech, bright': '明亮科技感',
    'upbeat, clean': '乾淨明亮',
    'soft, reflective': '柔和沉穩',
    'minimal, focused': '簡潔專注',
    'gentle, conversational': '溫和談話感',
    'neutral, trustworthy': '中性可信',
    'documentary, light': '輕紀錄片感',
    'fast, synthetic': '快速合成感',
    'bright, alert': '明亮提示感',
    'minimal, futuristic': '簡潔未來感',
    'optimistic, quick': '輕快正向',
    'clean, rhythmic': '乾淨節奏',
    'punchy, light': '輕巧有力',
    'playful, energetic': '活潑有能量',
    'spacious, gentle': '寬闊柔和',
    'warm, reflective': '溫暖內省',
    'transparent, quiet': '透明安靜',
    'focused, precise': '精準專注',
    'analytic, clean': '乾淨理性',
    'bright, minimal': '明亮簡潔',
    'steady, educational': '穩定教學感',
    'structured, calm': '有秩序且平穩',
    'loopable, friendly': '友善可循環',
    'soft, upbeat': '柔和輕快',
    'polished, light': '精緻輕盈',
    'confident, clean': '乾淨有信任感',
}

TRACK_USE_COPY = {
    'Podcast BGM': '適合談話、訪談、品牌說明或節目前後段襯底。',
    'Course BGM': '適合課程片段、章節銜接與知識型內容。',
    'AI radio stinger': '適合 AI 電台開場、段落切換、提示音與頻道識別。',
    'Short-form music': '適合 reels、商品短片、開箱與社群貼文。',
    'Calm ambient': '適合安靜工作、直播等待、冥想或溫和敘事。',
    'Tech underscore': '適合產品展示、介面錄影、科技簡報與工具介紹。',
    'Livestream loop': '適合直播開場、等待畫面與中場轉換。',
    'Brand social': '適合品牌短片、提案影片與社群形象內容。',
}


def _track_category(track):
    return str(track.get('category') or '').strip()


def _category_label(category):
    return CATEGORY_LABELS.get(str(category or '').strip(), str(category or '').strip() or '音樂素材')


def _track_title_number(track):
    title = str(track.get('title') or '').strip()
    tail = title.rsplit(' ', 1)[-1] if ' ' in title else ''
    return tail if tail.isdigit() else ''


def _track_id_number(track):
    identifier = str(track.get('id') or '').strip()
    tail = identifier.rsplit('-', 1)[-1] if '-' in identifier else ''
    return tail if tail.isdigit() else ''


def _track_number(track):
    return _track_title_number(track) or _track_id_number(track)


def _track_public_copy(track):
    return TRACK_PUBLIC_COPY.get(str(track.get('id') or '').strip(), {})


def _track_public_title(track):
    public_copy = _track_public_copy(track)
    if public_copy.get('title'):
        return public_copy['title']
    category = _track_category(track)
    prefix = TRACK_TITLE_PREFIXES.get(category)
    title_number = _track_title_number(track)
    id_number = _track_id_number(track)
    raw_title = str(track.get('title') or '').strip()
    if raw_title and not raw_title.lower().startswith('wanyu beta') and not (prefix and title_number):
        return raw_title
    if prefix and title_number:
        return prefix
    if prefix and id_number:
        return prefix
    return str(prefix or track.get('id') or '音樂素材').strip()


def _track_mood_label(track):
    mood = str(track.get('mood') or '').strip()
    return MOOD_LABELS.get(mood, mood or '情緒未標示')


def _track_use_copy(track):
    public_copy = _track_public_copy(track)
    if public_copy.get('copy'):
        return public_copy['copy']
    return TRACK_USE_COPY.get(_track_category(track), str(track.get('description') or '').strip() or '適合放進內容中試聽比對。')


def _track_duration_seconds(track):
    try:
        return max(0, int(float(track.get('duration_seconds') or 0)))
    except (TypeError, ValueError):
        return 0


def _duration_text(seconds):
    if seconds <= 0:
        return '長度待補'
    if seconds < 60:
        return str(seconds) + ' 秒'
    minutes, remainder = divmod(seconds, 60)
    if remainder:
        return str(minutes) + ' 分 ' + str(remainder) + ' 秒'
    return str(minutes) + ' 分'


def _duration_clock(seconds):
    if seconds <= 0:
        return '長度待補'
    minutes, remainder = divmod(seconds, 60)
    return str(minutes) + ':' + str(remainder).zfill(2)


def _track_preview_html(track):
    seconds = _track_duration_seconds(track)
    duration = _duration_text(seconds)
    if track.get('preview_audio_url'):
        return (
            '<div class="audio-box">'
            '<div class="audio-summary"><strong>試聽片段</strong><span class="audio-duration">完整長度 ' + _esc(duration) + '</span></div>'
            '<audio controls preload="metadata" controlsList="nodownload" aria-label="試聽 '
            + _esc(_track_public_title(track)) + '，長度 ' + _esc(duration)
            + '" src="' + _esc(track.get('preview_audio_url')) + '"></audio>'
            '</div>'
        )
    return '<div class="notice warn">這首尚未開放試聽，暫不販售。</div>'


def _track_card(track):
    category = _track_category(track)
    seconds = _track_duration_seconds(track)
    duration = _duration_text(seconds)
    bpm = str(track.get('bpm') or '').strip()
    bpm_chip = '<span class="pill">BPM ' + _esc(bpm) + '</span>' if bpm else ''
    return '''
    <article class="card track-card">
      <div class="track-eyebrow"><span>''' + _esc(_category_label(category)) + '''</span><span class="duration-badge">完整長度 ''' + _esc(duration) + '''</span></div>
      <h3>''' + _esc(_track_public_title(track)) + '''</h3>
      <p class="track-copy">''' + _esc(_track_use_copy(track)) + '''</p>
      <div class="track-facts">
        <span class="pill">''' + _esc(_track_mood_label(track)) + '''</span>
        ''' + bpm_chip + '''
        <span class="pill ok">付款後下載</span>
        <span class="pill ok">附授權憑證</span>
        <span class="pill warn">不含 Content ID / 轉售</span>
      </div>
      ''' + _track_preview_html(track) + '''
      <div class="track-buyline">
        <span class="track-price">NT$299 起</span>
        <a class="button" href="/soundbank/tracks/''' + _esc(track.get('id')) + '''">看授權與價格</a>
      </div>
    </article>
    '''


def _yes_no(value):
    text = str(value or '').strip().lower()
    if value is True or value == 1 or text in TRUE_VALUES:
        return '是'
    return '否'


def _display_value(value, fallback='未標示'):
    text = str(value or '').strip()
    return text if text else fallback


def _rights_proof_panel(proof):
    if not proof:
        return '<div class="notice warn">這首素材尚未完成公開權利紀錄，暫不販售。</div>'
    creator = _display_value(proof.get('creator'), '萬語聲庫原創素材團隊')
    creation_method = _display_value(proof.get('creation_method'), '原創音樂素材，已留存製作紀錄')
    if any(marker in creator.lower() for marker in ('codex', 'local synthesis', '11stars')):
        creator = '萬語聲庫原創素材團隊'
    if any(marker in creation_method.lower() for marker in ('deterministic', 'local synthesis', 'codex')):
        creation_method = '原創音樂素材，已留存製作紀錄'
    ai_tool = _display_value(proof.get('ai_tool'), '未使用外部 AI 音樂平台')
    third_party = _display_value(proof.get('third_party_sample'), '未使用第三方素材')
    if third_party.strip().lower() in ('none', 'no', 'n/a', 'na', '0'):
        third_party = '未使用第三方素材'
    return '''
        <div class="facts">
          <div class="fact"><strong>製作方</strong>''' + _esc(creator) + '''</div>
          <div class="fact"><strong>素材來源</strong>''' + _esc(creation_method) + '''</div>
          <div class="fact"><strong>外部 AI 音樂平台</strong>''' + _esc(ai_tool) + '''</div>
          <div class="fact"><strong>第三方素材</strong>''' + _esc(third_party) + '''</div>
          <div class="fact"><strong>商用使用</strong>可依所選方案使用</div>
          <div class="fact"><strong>授權轉讓</strong>不可轉讓或再授權給第三方</div>
          <div class="fact"><strong>付款後取得</strong>授權憑證與公開驗證連結</div>
          <div class="fact"><strong>平台留存</strong>來源紀錄與檔案指紋</div>
        </div>
        <div class="notice">這首已留存權利資料。若 YouTube、Facebook 或其他平台誤判，可用授權憑證申訴。</div>
    '''


def _license_label(kind):
    return {
        'personal': '個人授權',
        'commercial': '商業授權',
        'project': '專案授權',
    }.get(str(kind or ''), str(kind or '授權'))


def _count_tracks_by_category(tracks, *categories):
    wanted = set(categories)
    return sum(1 for track in tracks if str(track.get('category') or '').strip() in wanted)


def _scenario_entry_panel(tracks):
    podcast_count = _count_tracks_by_category(tracks, 'Podcast BGM', 'Course BGM')
    radio_count = _count_tracks_by_category(tracks, 'AI radio stinger')
    short_count = _count_tracks_by_category(tracks, 'Short-form music', 'Brand social')
    focus_count = _count_tracks_by_category(tracks, 'Calm ambient', 'Tech underscore', 'Livestream loop')
    return '''
        <section>
          <span class="section-kicker">從用途開始</span>
          <h2>先選你的作品場景</h2>
          <p class="section-lead">不用翻完整曲庫。先從常見用途進入素材頁，再用秒數、情緒和 BPM 快速比對。</p>
          <div class="grid">
            <a class="card compact scenario-card" href="/soundbank/tracks"><div class="scenario-top"><h3>Podcast / 課程</h3><span class="scenario-count">''' + _esc(str(podcast_count)) + ''' 首</span></div><p>人聲清楚、節奏不搶戲，適合片頭、段落底樂和課程背景。</p><span class="scenario-cta">去試聽</span></a>
            <a class="card compact scenario-card" href="/soundbank/tracks"><div class="scenario-top"><h3>AI 電台轉場</h3><span class="scenario-count">''' + _esc(str(radio_count)) + ''' 首</span></div><p>開場、片頭、提醒、段落切換，讓節目聽起來更完整。</p><span class="scenario-cta">去試聽</span></a>
            <a class="card compact scenario-card" href="/soundbank/tracks"><div class="scenario-top"><h3>短影音 / 社群</h3><span class="scenario-count">''' + _esc(str(short_count)) + ''' 首</span></div><p>商品短片、reels、貼文影片，先找能快速進畫面的音樂。</p><span class="scenario-cta">去試聽</span></a>
            <a class="card compact scenario-card" href="/soundbank/tracks"><div class="scenario-top"><h3>直播 / 科技</h3><span class="scenario-count">''' + _esc(str(focus_count)) + ''' 首</span></div><p>等待畫面、產品展示、介面錄影，保留乾淨科技感。</p><span class="scenario-cta">去試聽</span></a>
          </div>
        </section>
    '''


def _sales_decision_panel():
    return '''
          <div class="decision-panel">
            <div class="kicker">快速判斷</div>
            <div class="decision-grid">
              <div class="decision-item"><strong>看得到秒數</strong><span class="meta">每首先看完整長度。</span></div>
              <div class="decision-item"><strong>先買單首</strong><span class="meta">不用先訂閱整個曲庫。</span></div>
              <div class="decision-item"><strong>商用可選</strong><span class="meta">Podcast、短影音、直播、課程。</span></div>
              <div class="decision-item"><strong>付款留證</strong><span class="meta">正式檔、授權憑證、驗證連結。</span></div>
            </div>
          </div>
    '''


def _buyer_trust_panel():
    return '''
        <section>
          <div class="trust-strip">
            <div class="trust-item"><strong>27 首可試聽</strong><span class="meta">Podcast、短影音、直播先上架。</span></div>
            <div class="trust-item"><strong>每首有秒數</strong><span class="meta">完整長度與 BPM 先看。</span></div>
            <div class="trust-item"><strong>授權寫明</strong><span class="meta">可用範圍和禁止事項分開看。</span></div>
            <div class="trust-item"><strong>付款後留證</strong><span class="meta">下載、憑證、驗證連結。</span></div>
          </div>
        </section>
    '''


def _buyer_path_panel():
    return '''
        <section>
          <h2>怎麼買</h2>
          <div class="steps">
            <div class="step"><h3>先聽素材</h3><p>確認長度、情緒、BPM 和你的影片節奏是否合拍。</p></div>
            <div class="step"><h3>選授權</h3><p>個人、商業、專案三階，依作品用途選擇。</p></div>
            <div class="step"><h3>付款拿檔</h3><p>ECPay 確認後開通正式檔、授權憑證和驗證連結。</p></div>
          </div>
        </section>
    '''


def _license_shortcut_panel():
    return '''
        <section>
          <span class="section-kicker">授權方案</span>
          <h2>三種價格，一眼選</h2>
          <p class="section-lead">先用作品用途判斷，不確定時選商業授權比較穩。</p>
          <div class="grid license-cards">
            <a class="card license-shortcut" href="/soundbank/license"><h3>個人授權</h3><div class="price">NT$299</div><p>個人頻道、Podcast、練習作品或非商業內容。</p><span class="license-fit">適合先試水溫的小型作品。</span></a>
            <a class="card license-shortcut" href="/soundbank/license"><h3>商業授權</h3><div class="price">NT$999</div><p>YouTube、課程、直播、品牌社群或公司內容。</p><span class="license-fit">多數公開商用作品建議從這裡開始。</span></a>
            <a class="card license-shortcut" href="/soundbank/license"><h3>專案授權</h3><div class="price">NT$2,999</div><p>客戶案、廣告、活動或需要人工確認的用途。</p><span class="license-fit">適合交付給客戶或風險較高的專案。</span></a>
          </div>
        </section>
    '''


def _wedge_panel():
    return '''
        <section class="wedge-panel">
          <div class="wedge-head">
            <h2>小量精選，授權清楚</h2>
            <p class="lead">先買需要的那一首。試聽、用途、授權與憑證一次看清楚。</p>
          </div>
          <div class="wedge-grid">
            <div class="card"><h3>比免費素材更安心</h3><p>有訂單、有憑證、有授權驗證連結。</p></div>
            <div class="card"><h3>比大型訂閱更輕</h3><p>先買需要的那一首，不必先買整個曲庫。</p></div>
            <div class="card"><h3>比口頭承諾更可查</h3><p>素材保留來源與製作紀錄。</p></div>
            <aside class="panel principles-panel">
            <div class="kicker">上架原則</div>
            <h3>能試聽，才上架</h3>
            <ul class="list">
              <li>沒有試聽檔，不公開販售。</li>
              <li>沒有權利紀錄，不公開販售。</li>
              <li>不能商用或不能再授權，不公開販售。</li>
            </ul>
            </aside>
          </div>
        </section>
    '''


def _license_pricing_panel():
    return '''
        <section>
          <h2>授權價格</h2>
          <div class="grid">
            <div class="card"><h3>個人授權</h3><div class="price">NT$299</div><p>作品集、練習、非商業影片或個人內容。</p></div>
            <div class="card"><h3>商業授權</h3><div class="price">NT$999</div><p>單一 YouTube、Podcast、直播、課程或品牌社群專案。</p></div>
            <div class="card"><h3>專案授權</h3><div class="price">NT$2,999</div><p>單一品牌、活動、客戶案、廣告或需要人工確認的用途。</p></div>
          </div>
          <div class="notice">用在公司、品牌、營利頻道或客戶案，建議從商業授權開始。</div>
        </section>
    '''


def _content_id_policy_panel():
    return '''
        <section class="split">
          <div>
            <h2>買了也不能做的事</h2>
            <table><tbody>
              <tr><th>不要註冊 Content ID</th><td>不得把素材登記到 Content ID、YouTube CID、Facebook Rights Manager 或類似系統。</td></tr>
              <tr><th>不要轉售音檔</th><td>不得單獨販售、打包成素材庫、做成 beat pack 或上架 marketplace。</td></tr>
              <tr><th>不要發行成歌曲</th><td>不得把素材發行到 Spotify、Apple Music、YouTube Music、KKBOX 等音樂平台。</td></tr>
            </tbody></table>
          </div>
          <aside class="panel">
            <div class="kicker">為什麼限制</div>
            <h3>保護所有合法買家</h3>
            <p>如果有人把同一首拿去鎖權，其他買家可能被誤判。這些限制是為了讓授權可以長期使用。</p>
            <h3>遇到誤判</h3>
            <p>用訂單與授權證明向平台申訴；必要時再補授權紀錄。</p>
          </aside>
        </section>
    '''


def _policy_list(items):
    return '<ul class="list">' + ''.join('<li>' + _esc(item) + '</li>' for item in items) + '</ul>'


def _refund_support_panel():
    return '''
        <section class="split">
          <div>
            <h2>退費與客服</h2>
            <p class="lead">有付款、下載或憑證問題，請保留訂單與截圖。</p>
            <div class="quick-grid">
              <div class="quick-card"><strong>付款未成功</strong><span class="meta">不成立訂單，也不開通下載。</span></div>
              <div class="quick-card"><strong>重複扣款</strong><span class="meta">確認後優先退款。</span></div>
              <div class="quick-card"><strong>已下載正式檔</strong><span class="meta">原則上不退費。</span></div>
            </div>
            <details class="policy-details"><summary>查看完整退費規則</summary>''' + _policy_list(SOUNDBANK_REFUND_SUPPORT_RULES) + '''</details>
          </div>
          <aside class="panel">
            <div class="kicker">Support</div>
            <h3>權利爭議優先</h3>
            <p>遇到平台 claim、下載失敗或重複扣款，請附訂單與截圖。</p>
            <h3>處理依據</h3>
            <p>依訂單、付款、下載與授權紀錄判斷。</p>
          </aside>
        </section>
    '''


def register_soundbank_routes(app, get_db, is_admin_token_valid, check_admin_ip, log_admin_action, bot_base_url=''):
    @app.before_request
    def _soundbank_block_public_static_masters():
        if _is_public_static_master_request(request.path):
            abort(404)

    @app.route('/soundbank.webmanifest')
    def soundbank_webmanifest():
        response = make_response(json.dumps(_soundbank_manifest_payload(), ensure_ascii=False, separators=(',', ':')))
        response.headers['Content-Type'] = 'application/manifest+json; charset=utf-8'
        response.headers['Cache-Control'] = 'public, max-age=300'
        return response

    @app.route('/soundbank-sw.js')
    def soundbank_service_worker():
        response = make_response(_soundbank_service_worker_js())
        response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
        response.headers['Cache-Control'] = 'no-cache'
        return response

    @app.route('/soundbank')
    def soundbank_home():
        _require_public_enabled()
        try:
            all_tracks = _tracks_from_db(get_db)
            tracks = all_tracks[:3]
        except Exception:
            all_tracks = starter_tracks() if _bool_env('SOUNDBANK_SHOW_STARTER_DEMOS', False) else []
            tracks = all_tracks[:3]
        track_count = len(all_tracks)
        cards = ''.join(_track_card(track) for track in tracks)
        if not cards:
            cards = '<div class="notice warn">目前暫無可購買素材，請稍後再回來。</div>'
        body = '''
        <section class="hero visual-hero">
          <h1>先試聽，再買能直接放進作品的音樂</h1>
          <p class="lead hero-lead">每首都有秒數、BPM、用途與授權限制。適合 Podcast、短影音、直播和課程先買單首，不用先訂閱。</p>
          <div class="hero-proof">
            <span class="proof-chip">''' + _esc(track_count) + ''' 首可試聽素材</span>
            <span class="proof-chip">秒數 / BPM 已標示</span>
            <span class="proof-chip">單首 NT$299 起</span>
            <span class="proof-chip">付款後拿正式檔</span>
          </div>
          <div class="hero-actions">
            <a class="button" href="/soundbank/tracks">先聽素材</a>
            <a class="button secondary" href="/soundbank/license">看授權與價格</a>
            <span class="hero-action-note">不註冊 Content ID，不轉售素材，不二次上架音樂平台。</span>
          </div>
          ''' + _sales_decision_panel() + '''
        </section>
        ''' + _scenario_entry_panel(all_tracks) + '''
        <section>
          <h2>熱門試聽</h2>
          <p class="section-lead">先從這幾首開始聽。每張卡都能直接看到長度、情緒、用途與起始價格。</p>
          <div class="grid">''' + cards + '''</div>
          <div class="stack" style="margin-top:16px"><a class="button secondary" href="/soundbank/tracks">看全部素材</a></div>
        </section>
        ''' + _license_shortcut_panel() + '''
        ''' + _buyer_trust_panel() + '''
        ''' + _buyer_path_panel() + '''
        ''' + _wedge_panel() + '''
        '''
        home_description = '給 Podcast、AI 電台、短影音、課程、直播與品牌社群使用的小額商用音樂授權庫。先試聽，付款後取得正式檔案與授權憑證。'
        return _page(
            '小額商用音樂授權',
            body,
            '首頁',
            description=home_description,
            canonical_path='/soundbank',
            json_ld=_track_list_schema(all_tracks, SOUNDBANK_SITE_NAME, home_description, '/soundbank'),
        )

    @app.route('/soundbank/tracks')
    def soundbank_tracks():
        _require_public_enabled()
        try:
            tracks = _tracks_from_db(get_db)
        except Exception:
            tracks = starter_tracks() if _bool_env('SOUNDBANK_SHOW_STARTER_DEMOS', False) else []
        cards = ''.join(_track_card(track) for track in tracks)
        if not cards:
            cards = '<div class="notice warn">目前沒有達到公開標準的素材。未提供試聽檔或未完成權利核驗的素材不會出現在這裡。</div>'
        body = '''
        <section class="page-head">
          <h1>挑一首適合的音樂</h1>
          <p class="lead">先看秒數、BPM、情緒與用途，再試聽。喜歡就進單曲頁選授權。</p>
        </section>
        ''' + _sales_decision_panel() + '''
        ''' + _scenario_entry_panel(tracks) + '''
        <div class="grid">''' + cards + '''</div>
        '''
        tracks_description = '瀏覽可試聽音樂素材，快速比對長度、BPM、情緒、用途與授權價格。適合 Podcast、短影音、直播、課程與品牌內容。'
        return _page(
            '可試聽音樂素材',
            body,
            '素材',
            description=tracks_description,
            canonical_path='/soundbank/tracks',
            json_ld=_track_list_schema(tracks, '可試聽音樂素材', tracks_description, '/soundbank/tracks'),
        )

    @app.route('/soundbank/tracks/<track_id>')
    def soundbank_track_detail(track_id):
        _require_public_enabled()
        try:
            track = _track_from_db(get_db, track_id)
            licenses = _licenses_for_track(get_db, track_id)
            proof = _rights_proof_for_track(get_db, track_id) if track else None
        except Exception:
            if _bool_env('SOUNDBANK_SHOW_STARTER_DEMOS', False):
                track = _starter_track(track_id)
                licenses = _demo_licenses(track_id) if track else []
                proof = None
            else:
                track = None
                licenses = []
                proof = None
        if not track:
            abort(404)
        rows = ''
        for lic in licenses:
            rows += '<tr><td data-label="方案">' + _esc(_license_label(lic.get('license_type'))) + '</td><td data-label="價格">' + _money(lic.get('price')) + '</td><td data-label="可用範圍">' + _esc(lic.get('usage_scope')) + '</td><td data-label="購買"><a class="button secondary" href="/soundbank/checkout/' + _esc(track_id) + '?license=' + _esc(lic.get('license_type')) + '">選這個方案</a></td></tr>'
        preview = _track_preview_html(track)
        seconds = _track_duration_seconds(track)
        duration = _duration_text(seconds)
        detail_description = (
            _track_public_title(track) + '，完整長度 ' + duration + '。'
            + _track_use_copy(track)
            + ' 個人授權 NT$299 起，付款後下載正式檔案並附授權憑證。'
        )
        body = '''
        <a href="/soundbank/tracks">返回素材列表</a>
        <section class="hero">
          <div class="meta">''' + _esc(_category_label(track.get('category'))) + '''</div>
          <h1>''' + _esc(_track_public_title(track)) + '''</h1>
          <p class="lead">''' + _esc(_track_use_copy(track)) + '''</p>
          <div>
            <span class="pill ok">完整長度 ''' + _esc(duration) + '''</span>
            <span class="pill">''' + _esc(_track_mood_label(track)) + '''</span>
            <span class="pill">BPM ''' + _esc(track.get('bpm')) + '''</span>
          </div>
          ''' + preview + '''
        </section>
        <section>
          <h2>授權安心資料</h2>
          ''' + _rights_proof_panel(proof) + '''
        </section>
        ''' + _content_id_policy_panel() + '''
        <section>
          <h2>授權方案</h2>
          <table class="license-table"><thead><tr><th>方案</th><th>價格</th><th>可用範圍</th><th></th></tr></thead><tbody>''' + rows + '''</tbody></table>
        </section>
        <section>
          <h2>使用限制</h2>
          ''' + _policy_list(SOUNDBANK_LICENSE_RESTRICTIONS) + '''
          <div class="notice warn">不得轉售音檔、不得重新包裝成素材包、不得註冊 Content ID、不得發行至 Spotify / Apple Music / YouTube Music / KKBOX 等音樂平台、不得再授權給第三方。</div>
        </section>
        '''
        return _page(
            _track_public_title(track),
            body,
            '素材',
            description=detail_description,
            canonical_path='/soundbank/tracks/' + track_id,
            json_ld=_track_detail_schema(track, licenses, detail_description),
        )

    @app.route('/soundbank/license')
    def soundbank_license():
        _require_public_enabled()
        body = '''
        <section class="page-head">
          <h1>選對授權方案</h1>
          <p class="lead">先看用途，再選個人、商業或專案。付款後可保存授權憑證。</p>
        </section>
        ''' + _license_pricing_panel() + '''
        <h2>使用前看三件事</h2>
        <table><tbody>
          <tr><th>不是取得著作權</th><td>你取得的是使用授權，授權範圍依購買方案為準。</td></tr>
          <tr><th>保留憑證</th><td>付款後請保存訂單、授權憑證與驗證連結。</td></tr>
          <tr><th>遇到誤判</th><td>若平台誤判，先用授權證明申訴。</td></tr>
        </tbody></table>
        ''' + _content_id_policy_panel() + '''
        <h2>禁止事項</h2>
        <div class="quick-grid">
          <div class="quick-card"><strong>不做版權登記</strong><span class="meta">不可註冊 Content ID 或類似權利識別系統。</span></div>
          <div class="quick-card"><strong>不單賣素材</strong><span class="meta">不可轉售、打包素材庫或放到 marketplace。</span></div>
          <div class="quick-card"><strong>不轉讓授權</strong><span class="meta">不可把使用權轉讓或再授權給第三方。</span></div>
          <div class="quick-card"><strong>不發行成歌曲</strong><span class="meta">不可上架 Spotify、Apple Music、YouTube Music、KKBOX。</span></div>
          <div class="quick-card"><strong>不拿去訓練 AI</strong><span class="meta">不可作為模型訓練資料、資料集或聲音來源。</span></div>
        </div>
        <details class="policy-details"><summary>查看完整禁止事項</summary>''' + _policy_list(SOUNDBANK_LICENSE_RESTRICTIONS) + '''</details>
        ''' + _refund_support_panel() + '''
        '''
        license_description = '了解萬語聲庫個人、商業與專案授權差異，以及 Content ID、轉售、再授權、素材包與串流平台上架限制。'
        return _page(
            '授權方案與禁止事項',
            body,
            '授權',
            description=license_description,
            canonical_path='/soundbank/license',
        )

    @app.route('/soundbank/support')
    def soundbank_support():
        _require_public_enabled()
        body = '''
        <section class="page-head">
          <h1>客服與退費</h1>
          <p class="lead">付款、下載或憑證有問題，請保留訂單資料與截圖。</p>
        </section>
        ''' + _refund_support_panel() + '''
        <section>
          <h2>申請時請準備</h2>
          <div class="support-checklist">
            <div class="card"><h3>訂單問題</h3><p class="meta">訂單編號、付款時間、付款平台通知截圖、買方 email。</p></div>
            <div class="card"><h3>下載問題</h3><p class="meta">訂單編號、素材 ID、錯誤畫面、下載時間。</p></div>
            <div class="card"><h3>權利爭議</h3><p class="meta">平台通知截圖、claim ID、作品 URL、授權憑證編號。</p></div>
          </div>
        </section>
        <section>
          <h2>仍不允許</h2>
          <div class="quick-grid">
            <div class="quick-card"><strong>Content ID</strong><span class="meta">不可註冊或轉交權利識別系統。</span></div>
            <div class="quick-card"><strong>轉售素材</strong><span class="meta">不可單賣、打包或再上架。</span></div>
            <div class="quick-card"><strong>轉讓授權</strong><span class="meta">不可轉讓使用權或再授權。</span></div>
            <div class="quick-card"><strong>音樂平台發行</strong><span class="meta">不可當成歌曲上架串流平台。</span></div>
            <div class="quick-card"><strong>AI 訓練</strong><span class="meta">不可作為模型或資料集來源。</span></div>
          </div>
          <details class="policy-details"><summary>查看完整禁止事項</summary>''' + _policy_list(SOUNDBANK_LICENSE_RESTRICTIONS) + '''</details>
        </section>
        '''
        support_description = '萬語聲庫客服與退費說明，包含付款、下載、授權憑證、重複扣款與 Content ID 權利爭議所需資料。'
        return _page(
            '客服與退費說明',
            body,
            '客服/退費',
            description=support_description,
            canonical_path='/soundbank/support',
        )

    @app.route('/soundbank/checkout/<track_id>', methods=['GET', 'POST'])
    def soundbank_checkout(track_id):
        _require_public_enabled()
        fake_checkout = os.environ.get('SOUNDBANK_FAKE_CHECKOUT_ENABLED', 'false').strip().lower() in TRUE_VALUES
        selected = request.args.get('license', 'commercial')
        try:
            track = _track_from_db(get_db, track_id)
            licenses = _licenses_for_track(get_db, track_id)
        except Exception:
            track = _starter_track(track_id)
            licenses = _demo_licenses(track_id) if track else []
        if not track:
            abort(404)
        if not licenses:
            return _page('暫不開放購買', '<h1>暫不開放購買</h1><div class="notice warn">這首素材還沒有可購買的授權方案，請先選擇其他素材。</div>', '素材'), 404
        if request.method == 'GET':
            license_types = [row.get('license_type') for row in licenses]
            if selected not in license_types:
                selected = licenses[0].get('license_type', selected)
        if request.method == 'POST':
            payment_method = request.form.get('payment_method', 'fake').strip().lower()
            license_type = request.form.get('license_type', selected).strip() or selected
            selected_license = None
            for row in licenses:
                if row.get('license_type') == license_type:
                    selected_license = row
                    break
            if not selected_license:
                return _page('找不到授權方案', '<h1>找不到授權方案</h1><div class="notice warn">請回到素材頁重新選擇授權方案。</div>', '素材'), 404
            buyer_name = request.form.get('buyer_name', '').strip()
            buyer_email = request.form.get('buyer_email', '').strip()
            if payment_method == 'ecpay':
                if not _ecpay_configured():
                    return _page('付款暫停服務', '<h1>付款暫停服務</h1><div class="notice warn">目前付款服務暫時無法使用，請稍後再試。</div>', '素材'), 503
                order_id = 'SB-ORDER-ECPAY-' + datetime.utcnow().strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:8].upper()
                merchant_trade_no = _ecpay_trade_no()
                order = _create_pending_order(
                    get_db,
                    order_id,
                    track_id,
                    selected_license,
                    license_type,
                    buyer_name,
                    buyer_email,
                    'ecpay',
                    merchant_trade_no,
                )
                track = _track_from_db(get_db, track_id) or {'id': track_id}
                params = _ecpay_order_params(order, track, selected_license, bot_base_url)
                return _page('ECPay 付款單', _ecpay_payment_form(params), '素材', robots='noindex,nofollow')
            if not fake_checkout:
                return _page('尚未開放結帳', '<h1>此素材暫不開放結帳</h1><div class="notice warn">目前尚未開放這筆授權購買，請稍後再試或改選其他素材。</div>', '素材'), 400
            order_id = 'SB-ORDER-' + datetime.utcnow().strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:8].upper()
            result = _finalize_paid_order(
                get_db,
                order_id,
                track_id,
                selected_license,
                license_type,
                buyer_name,
                buyer_email,
                'staging_fake',
                order_id,
                bot_base_url,
            )
            success_url = '/soundbank/success?order_id=' + order_id
            if result.get('access_token'):
                success_url += '&access_token=' + result['access_token']
            return redirect(success_url)
        body = '''
        <h1>確認授權</h1>
        <div class="notice">確認買方資訊後前往 ECPay。付款成功後會開通下載、授權憑證與驗證連結。</div>
        <div class="notice warn">付款前請確認：授權不轉讓，不可註冊 Content ID，不可轉售素材，也不可上架 Spotify、Apple Music、YouTube Music、KKBOX 等音樂平台。</div>
        <form method="post">
          <label>素材編號<input name="track_id" value="''' + _esc(track_id) + '''" readonly></label>
          <label>授權方案<input name="license_type" value="''' + _esc(selected) + '''" readonly></label>
          <label>買方姓名或公司<input name="buyer_name" placeholder="例如：王小明 / 萬語聲庫"></label>
          <label>Email<input name="buyer_email" placeholder="用來接收訂單與授權資訊"></label>
          <button class="button" type="submit" name="payment_method" value="ecpay">建立 ECPay 付款單</button>
          ''' + ('<button class="button secondary" type="submit" name="payment_method" value="fake">建立測試訂單</button>' if fake_checkout else '') + '''
        </form>
        '''
        return _page('確認授權', body, '素材', robots='noindex,nofollow')

    def _order_portal_body(order_id, access_token):
        payload = _verify_token(access_token, 'order_access')
        if not order_id or not payload or payload.get('order_id') != order_id:
            return '''
            <section class="page-head">
              <h1>我的下載</h1>
              <p class="lead">付款完成後會建立專屬訂單頁。<br>請從付款成功頁回來下載；頁面關閉時請聯絡客服。</p>
            </section>
            <div class="notice warn">下載連結是短效連結。<br>若失效，請回訂單完成頁重新開啟。</div>
            <section>
              <h2>找不到訂單頁時</h2>
              <div class="quick-grid">
                <div class="quick-card"><strong>回付款完成頁</strong><span class="meta">完成付款後請點「開啟授權與下載」。</span></div>
                <div class="quick-card"><strong>查付款紀錄</strong><span class="meta">確認付款時間、金額與購買素材，不必等待系統寄信。</span></div>
                <div class="quick-card"><strong>準備訂單資訊</strong><span class="meta">保留訂單編號、付款時間與購買素材，客服可協助核對。</span></div>
                <div class="quick-card"><strong>不公開正式檔</strong><span class="meta">正式音檔只在付款驗證後提供，不會放在公開頁面。</span></div>
              </div>
            </section>
            <div class="stack" style="margin-top:16px">
              <a class="button" href="/soundbank/tracks">回素材列表</a>
              <a class="button secondary" href="/soundbank/support">聯絡客服</a>
            </div>
            '''
        order = _order_bundle_by_payment_ref(get_db, order_id)
        if not order or order.get('payment_status') != 'paid':
            return '''
            <section class="page-head">
              <h1>我的下載</h1>
              <p class="lead">目前沒有可下載訂單。<br>ECPay 驗證付款後才會開通。</p>
            </section>
            <div class="notice warn">若剛付款完成，請等候確認頁跳轉。<br>仍無法開啟時，請帶付款時間或訂單編號聯絡客服。</div>
            <div class="stack" style="margin-top:16px">
              <a class="button" href="/soundbank/tracks">回素材列表</a>
              <a class="button secondary" href="/soundbank/support">聯絡客服</a>
            </div>
            '''
        certificate = _ensure_license_certificate(get_db, order_id, bot_base_url)
        download_token = _make_token(
            {'purpose': 'download', 'order_id': order_id, 'track_id': order.get('track_id')},
            _int_env('SOUNDBANK_DOWNLOAD_TOKEN_TTL_SECONDS', 900),
        )
        cert_token = _make_token(
            {
                'purpose': 'certificate',
                'order_id': order_id,
                'certificate_id': certificate.get('certificate_id') if certificate else '',
            },
            _int_env('SOUNDBANK_CERTIFICATE_TOKEN_TTL_SECONDS', 86400),
        )
        certificate_link = ''
        verify_link = ''
        if certificate and cert_token:
            certificate_link = (
                '<a class="button secondary" href="/soundbank/license-certificate/'
                + _esc(certificate.get('certificate_id'))
                + '?token=' + _esc(cert_token)
                + '">查看授權憑證</a>'
            )
            verify_link = (
                '<a class="button secondary" href="/soundbank/verify/'
                + _esc(certificate.get('certificate_id'))
                + '">授權驗證連結</a>'
            )
        download_link = ''
        if download_token:
            download_link = (
                '<a class="button" href="/soundbank/download/'
                + _esc(order_id)
                + '?token=' + _esc(download_token)
                + '">下載正式檔案</a>'
            )
        return '''
        <h1>訂單完成</h1>
        <div class="notice">付款已確認。請先下載正式音檔，並保存授權憑證與驗證連結。</div>
        <table><tbody>
          <tr><th>訂單</th><td>''' + _esc(order_id) + '''</td></tr>
          <tr><th>素材</th><td>''' + _esc(order.get('track_title')) + '''</td></tr>
          <tr><th>授權</th><td>''' + _esc(order.get('license_type')) + '''</td></tr>
          <tr><th>金額</th><td>''' + _money(order.get('amount')) + '''</td></tr>
          <tr><th>條款版本</th><td>''' + _esc(order.get('terms_version')) + '''</td></tr>
        </tbody></table>
        <div class="stack" style="margin-top:16px">''' + download_link + certificate_link + verify_link + '''</div>
        '''

    @app.route('/soundbank/success')
    def soundbank_success():
        _require_public_enabled()
        order_id = request.args.get('order_id', '')
        access_token = request.args.get('access_token', '')
        body = _order_portal_body(order_id, access_token)
        return _page('訂單完成', body, '素材', robots='noindex,nofollow')

    @app.route('/soundbank/downloads')
    def soundbank_downloads():
        _require_public_enabled()
        order_id = request.args.get('order_id', '')
        access_token = request.args.get('access_token', '')
        body = _order_portal_body(order_id, access_token)
        return _page('我的下載', body, '下載', robots='noindex,nofollow')

    @app.route('/soundbank/download/<order_id>')
    def soundbank_download_file(order_id):
        _require_public_enabled()
        payload = _verify_token(request.args.get('token', ''), 'download')
        if not payload or payload.get('order_id') != order_id:
            return _page('下載連結失效', '<h1>下載連結失效</h1><div class="notice warn">請回到訂單頁重新取得短效下載連結。</div>', '下載'), 403
        order = _order_bundle(get_db, order_id)
        if not order or order.get('payment_status') != 'paid':
            return _page('不可下載', '<h1>不可下載</h1><div class="notice warn">找不到已付款訂單。</div>', '下載'), 403
        if payload.get('track_id') != order.get('track_id'):
            return _page('不可下載', '<h1>不可下載</h1><div class="notice warn">下載權限與素材不一致。</div>', '下載'), 403
        download = _fetch_one(
            get_db,
            '''
            SELECT id, download_count, expires_at
            FROM soundbank_downloads
            WHERE order_id=%s
            ORDER BY id ASC
            LIMIT 1
            ''',
            (order_id,)
        )
        if not download:
            return _page('不可下載', '<h1>不可下載</h1><div class="notice warn">找不到下載權限。</div>', '下載'), 403
        expires_dt = _parse_time(download.get('expires_at'))
        if expires_dt and expires_dt < datetime.utcnow():
            return _page('下載已過期', '<h1>下載已過期</h1><div class="notice warn">此訂單下載期限已過。</div>', '下載'), 403
        limit = int(order.get('download_limit') or 3)
        if int(download.get('download_count') or 0) >= limit:
            return _page('下載次數已滿', '<h1>下載次數已滿</h1><div class="notice warn">此授權方案的下載次數已用完。</div>', '下載'), 403
        download_response, download_error = _master_download_response(get_db, order)
        if not download_response:
            return _page('正式音檔暫時無法下載', '<h1>正式音檔暫時無法下載</h1><div class="notice warn">請保留訂單編號並聯絡客服，我們會協助重新開通下載。</div>', '下載'), 404
        _execute(
            get_db,
            '''
            UPDATE soundbank_downloads
            SET download_count=download_count+1, last_downloaded_at=%s
            WHERE id=%s
            ''',
            (_tw_now(), download.get('id'))
        )
        return download_response

    @app.route('/soundbank/license-certificate/<certificate_id>')
    def soundbank_license_certificate(certificate_id):
        _require_public_enabled()
        payload = _verify_token(request.args.get('token', ''), 'certificate')
        if not payload or payload.get('certificate_id') != certificate_id:
            return _page('憑證連結失效', '<h1>憑證連結失效</h1><div class="notice warn">請回到訂單頁重新取得短效憑證連結。</div>', '下載'), 403
        cert = _fetch_one(
            get_db,
            '''
            SELECT certificate_id, order_id, buyer_name, buyer_id, track_id, track_title,
                   license_type, usage_scope, terms_version, certificate_hash,
                   verification_url, issued_at, revoked_at, revocation_reason
            FROM soundbank_license_certificates
            WHERE certificate_id=%s
            LIMIT 1
            ''',
            (certificate_id,)
        )
        if not cert:
            abort(404)
        body = '''
        <h1>授權憑證</h1>
        <table><tbody>
          <tr><th>憑證編號</th><td>''' + _esc(cert.get('certificate_id')) + '''</td></tr>
          <tr><th>訂單</th><td>''' + _esc(cert.get('order_id')) + '''</td></tr>
          <tr><th>買方</th><td>''' + _esc(cert.get('buyer_name')) + '''</td></tr>
          <tr><th>素材</th><td>''' + _esc(cert.get('track_title')) + ''' (''' + _esc(cert.get('track_id')) + ''')</td></tr>
          <tr><th>授權</th><td>''' + _esc(cert.get('license_type')) + '''</td></tr>
          <tr><th>使用範圍</th><td>''' + _esc(cert.get('usage_scope')) + '''</td></tr>
          <tr><th>條款版本</th><td>''' + _esc(cert.get('terms_version')) + '''</td></tr>
          <tr><th>簽發時間</th><td>''' + _esc(cert.get('issued_at')) + '''</td></tr>
          <tr><th>憑證雜湊</th><td>''' + _esc(cert.get('certificate_hash')) + '''</td></tr>
        </tbody></table>
        <div class="notice">授權驗證連結：<a href="''' + _esc(cert.get('verification_url')) + '''">''' + _esc(cert.get('verification_url')) + '''</a></div>
        '''
        response = make_response(_page('授權憑證', body, '下載', robots='noindex,nofollow'))
        if request.args.get('download') == '1':
            response.headers['Content-Disposition'] = 'attachment; filename="' + certificate_id + '.html"'
        return response

    @app.route('/soundbank/verify/<certificate_id>')
    def soundbank_verify_certificate(certificate_id):
        _require_public_enabled()
        cert = _fetch_one(
            get_db,
            '''
            SELECT certificate_id, track_id, track_title, license_type,
                   terms_version, certificate_hash, issued_at, revoked_at
            FROM soundbank_license_certificates
            WHERE certificate_id=%s
            LIMIT 1
            ''',
            (certificate_id,)
        )
        if not cert:
            abort(404)
        status = 'revoked' if cert.get('revoked_at') else 'valid'
        body = '''
        <h1>授權憑證驗證</h1>
        <table><tbody>
          <tr><th>狀態</th><td>''' + _esc(status) + '''</td></tr>
          <tr><th>憑證編號</th><td>''' + _esc(cert.get('certificate_id')) + '''</td></tr>
          <tr><th>素材</th><td>''' + _esc(cert.get('track_title')) + ''' (''' + _esc(cert.get('track_id')) + ''')</td></tr>
          <tr><th>授權</th><td>''' + _esc(cert.get('license_type')) + '''</td></tr>
          <tr><th>條款版本</th><td>''' + _esc(cert.get('terms_version')) + '''</td></tr>
          <tr><th>簽發時間</th><td>''' + _esc(cert.get('issued_at')) + '''</td></tr>
          <tr><th>憑證雜湊</th><td>''' + _esc(cert.get('certificate_hash')) + '''</td></tr>
        </tbody></table>
        '''
        return _page('憑證驗證', body, '下載')

    @app.route('/soundbank/payment/webhook', methods=['POST'])
    def soundbank_payment_webhook():
        _require_public_enabled()
        raw_body = request.get_data() or b''
        ok, error = _verify_webhook_signature(raw_body)
        if not ok:
            status = 503 if 'not configured' in error else 403
            return jsonify({'ok': False, 'error': error}), status
        data = request.get_json(silent=True) or request.form.to_dict()
        order_id = str(data.get('order_id') or data.get('MerchantTradeNo') or '').strip()
        provider_trade_no = str(data.get('provider_trade_no') or data.get('TradeNo') or '').strip()
        status_value = str(data.get('status') or data.get('RtnCode') or '').strip().lower()
        amount_raw = data.get('amount') or data.get('TradeAmt') or ''
        if not order_id:
            return jsonify({'ok': False, 'error': 'missing order_id'}), 400
        order = _order_bundle(get_db, order_id)
        if not order:
            return jsonify({'ok': False, 'error': 'order not found'}), 404
        try:
            amount = int(amount_raw)
        except Exception:
            amount = -1
        if amount != int(order.get('amount') or 0):
            return jsonify({'ok': False, 'error': 'amount mismatch'}), 400
        paid_statuses = {'1', 'paid', 'success', 'succeeded'}
        if status_value not in paid_statuses:
            return jsonify({'ok': True, 'ignored': True, 'status': status_value})
        if _soundbank_order_blocks_paid_callback(order):
            return jsonify({
                'ok': True,
                'ignored': True,
                'status': status_value,
                'reason': 'order_finalized',
                'payment_status': order.get('payment_status'),
            })
        updated = _execute(
            get_db,
            '''
            UPDATE soundbank_orders
            SET payment_provider=%s, payment_status='paid', provider_trade_no=%s,
                paid_at=CASE WHEN COALESCE(paid_at,'')='' THEN %s ELSE paid_at END,
                updated_at=%s
            WHERE order_id=%s
              AND LOWER(COALESCE(payment_status,'')) NOT IN ('refunded','cancelled','canceled','voided','chargeback')
            RETURNING order_id
            ''',
            ('soundbank_webhook', provider_trade_no, _tw_now(), _tw_now(), order.get('order_id')),
            fetch_one=True,
        )
        if not updated:
            return jsonify({
                'ok': True,
                'ignored': True,
                'status': status_value,
                'reason': 'order_finalized',
            })
        download = _ensure_download_row(get_db, order.get('order_id'), order.get('track_id'))
        if not download:
            return jsonify({
                'ok': True,
                'ignored': True,
                'status': status_value,
                'reason': 'order_not_paid_after_update',
            })
        certificate = _ensure_license_certificate(get_db, order.get('order_id'), bot_base_url)
        return jsonify({
            'ok': True,
            'order_id': order.get('order_id'),
            'certificate_id': certificate.get('certificate_id') if certificate else '',
        })

    @app.route('/soundbank/payment/ecpay/notify', methods=['POST'])
    def soundbank_ecpay_notify():
        _require_public_enabled()
        data = request.form.to_dict()
        if not data:
            return '0|ErrorMessage', 200
        creds = _ecpay_credentials()
        if not creds.get('merchant_id') or not creds.get('hash_key') or not creds.get('hash_iv'):
            return '0|ECPay Config Error', 200
        received_mac = str(data.get('CheckMacValue') or '').strip().upper()
        expected_mac = _ecpay_check_mac(data, creds['hash_key'], creds['hash_iv'])
        if not received_mac or not hmac.compare_digest(received_mac, expected_mac):
            return '0|CheckMacValue Error', 200
        merchant_id = str(data.get('MerchantID') or '').strip()
        if merchant_id != creds['merchant_id']:
            return '0|MerchantID Error', 200
        merchant_trade_no = str(data.get('MerchantTradeNo') or '').strip()
        if not merchant_trade_no:
            return '0|MerchantTradeNo Error', 200
        order = _order_bundle_by_payment_ref(get_db, merchant_trade_no)
        if not order:
            return '0|Order Not Found', 200
        try:
            amount = int(data.get('TradeAmt') or 0)
        except Exception:
            amount = -1
        if amount != int(order.get('amount') or 0):
            return '0|Amount Error', 200
        if str(data.get('RtnCode') or '') != '1':
            return '1|OK', 200
        if str(data.get('SimulatePaid') or '0') == '1' and not _bool_env('SOUNDBANK_ECPAY_ACCEPT_SIMULATED', False):
            return '1|OK', 200
        if _soundbank_order_blocks_paid_callback(order):
            return '1|OK', 200
        provider_trade_no = str(data.get('TradeNo') or '').strip()
        updated = _execute(
            get_db,
            '''
            UPDATE soundbank_orders
            SET payment_provider='ecpay', payment_status='paid',
                merchant_order_no=%s, provider_trade_no=%s,
                paid_at=CASE WHEN COALESCE(paid_at,'')='' THEN %s ELSE paid_at END,
                updated_at=%s
            WHERE order_id=%s
              AND LOWER(COALESCE(payment_status,'')) NOT IN ('refunded','cancelled','canceled','voided','chargeback')
            RETURNING order_id
            ''',
            (merchant_trade_no, provider_trade_no, _tw_now(), _tw_now(), order.get('order_id')),
            fetch_one=True,
        )
        if not updated:
            return '1|OK', 200
        download = _ensure_download_row(get_db, order.get('order_id'), order.get('track_id'))
        if not download:
            return '1|OK', 200
        _ensure_license_certificate(get_db, order.get('order_id'), bot_base_url)
        return '1|OK', 200

    @app.route('/soundbank/payment/ecpay/return', methods=['GET', 'POST'])
    def soundbank_ecpay_return():
        _require_public_enabled()
        order_ref = (
            request.values.get('order_id', '')
            or request.values.get('MerchantTradeNo', '')
            or request.values.get('CustomField1', '')
        ).strip()
        order = _order_bundle_by_payment_ref(get_db, order_ref) if order_ref else None
        if not order:
            return _page('付款結果', '<h1>付款結果</h1><div class="notice warn">找不到 SoundBank 訂單。若剛完成付款，請稍候再查看訂單通知。</div>', '素材', robots='noindex,nofollow'), 404
        if order.get('payment_status') == 'paid':
            access_token = _make_token(
                {'purpose': 'order_access', 'order_id': order.get('order_id')},
                _int_env('SOUNDBANK_ORDER_TOKEN_TTL_SECONDS', 3600),
            )
            link = '/soundbank/success?order_id=' + _esc(order.get('order_id')) + '&access_token=' + _esc(access_token)
            body = '<h1>付款已確認</h1><div class="notice">付款已確認。你可以開啟授權與下載頁。</div><a class="button" href="' + link + '">開啟授權與下載</a>'
            return _page('付款已確認', body, '素材', robots='noindex,nofollow')
        body = '''
        <h1>付款處理中</h1>
        <div class="notice warn">付款資料仍在確認中。若你剛完成付款，請稍候重新整理，或從訂單入口回到授權與下載頁。</div>
        <table><tbody>
          <tr><th>訂單</th><td>''' + _esc(order.get('order_id')) + '''</td></tr>
          <tr><th>付款狀態</th><td>''' + _esc(order.get('payment_status')) + '''</td></tr>
          <tr><th>付款單號</th><td>''' + _esc(order.get('merchant_order_no')) + '''</td></tr>
        </tbody></table>
        '''
        return _page('付款處理中', body, '素材', robots='noindex,nofollow')

    @app.route('/soundbank/report-misuse', methods=['GET', 'POST'])
    def soundbank_report_misuse():
        _require_public_enabled()
        if request.method == 'POST':
            reported_url = request.form.get('reported_url', '').strip()
            track_id = request.form.get('track_id', '').strip()
            reporter_contact = request.form.get('reporter_contact', '').strip()
            reason = request.form.get('reason', '').strip()
            evidence_url = request.form.get('evidence_url', '').strip()
            if not reported_url or not reason:
                return _page('通報資料不足', '<h1>通報資料不足</h1><div class="notice warn">請至少填寫違規網址與原因。</div>', '通報'), 400
            try:
                _execute(
                    get_db,
                    '''
                    INSERT INTO soundbank_violation_reports
                    (reported_url, track_id, reporter_contact, reason, evidence_url, status, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,'new',%s,%s)
                    ''',
                    (reported_url, track_id, reporter_contact, reason, evidence_url, _tw_now(), _tw_now())
                )
                return _page('已收到通報', '<h1>已收到通報</h1><p>我們會依素材編號、授權紀錄與證據進行反查。</p>', '通報')
            except Exception:
                return _page('通報暫存失敗', '<h1>通報暫存失敗</h1><div class="notice warn">資料庫尚未啟用或暫時無法連線，請稍後再試。</div>', '通報'), 500
        body = '''
        <h1>違規使用通報</h1>
        <p class="lead">如果你發現萬語聲庫素材被轉售、註冊 Content ID、上架音樂平台或超出授權範圍使用，請提供證據。</p>
        <form method="post">
          <label>違規網址<input name="reported_url" required></label>
          <label>素材編號<input name="track_id" placeholder="例如 SB-PODCAST-001"></label>
          <label>聯絡方式<input name="reporter_contact" placeholder="Email 或 LINE ID"></label>
          <label>證據連結<input name="evidence_url" placeholder="截圖、錄影或公開頁面"></label>
          <label>原因<textarea name="reason" required></textarea></label>
          <button class="button" type="submit">送出通報</button>
        </form>
        '''
        return _page('違規通報', body, '通報')

    @app.route('/admin/soundbank')
    def admin_soundbank_home():
        guard = _admin_guard(is_admin_token_valid, check_admin_ip)
        if guard:
            return guard
        body = '''
        <h1>SoundBank 後台</h1>
        <div class="notice">目前功能開關：''' + ('啟用' if soundbank_enabled() else '關閉') + '''。正式站未設定 SOUNDBANK_ENABLED=true 時，前台 /soundbank 不會曝光。</div>
        <div class="grid">
          <a class="card" href="/admin/soundbank/tracks"><h3>素材管理</h3><p>新增、編輯、上下架素材與權利狀態。</p></a>
          <a class="card" href="/admin/soundbank/orders"><h3>訂單</h3><p>查看付款狀態、授權方案與下載權限。</p></a>
          <a class="card" href="/admin/soundbank/rights-proofs"><h3>權利證明</h3><p>檢查每首素材的 rights_proof 是否完整。</p></a>
          <a class="card" href="/admin/soundbank/violation-reports"><h3>違規通報</h3><p>處理轉售、Content ID、超範圍使用等案件。</p></a>
        </div>
        '''
        return _page('後台', body, 'soundbank')

    @app.route('/admin/soundbank/tracks', methods=['GET', 'POST'])
    def admin_soundbank_tracks():
        guard = _admin_guard(is_admin_token_valid, check_admin_ip)
        if guard:
            return guard
        if request.method == 'POST':
            data = request.form
            track_id = data.get('id') or ('SB-' + _slug(data.get('category'), 'TRACK').upper() + '-' + uuid.uuid4().hex[:6].upper())
            try:
                _execute(
                    get_db,
                    '''
                    INSERT INTO soundbank_tracks
                    (id,title,description,category,mood,bpm,duration_seconds,preview_audio_url,download_audio_url,cover_image_url,status,rights_status,review_status,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                    title=EXCLUDED.title,
                    description=EXCLUDED.description,
                    category=EXCLUDED.category,
                    mood=EXCLUDED.mood,
                    bpm=EXCLUDED.bpm,
                    duration_seconds=EXCLUDED.duration_seconds,
                    preview_audio_url=EXCLUDED.preview_audio_url,
                    download_audio_url=EXCLUDED.download_audio_url,
                    cover_image_url=EXCLUDED.cover_image_url,
                    status=EXCLUDED.status,
                    rights_status=EXCLUDED.rights_status,
                    review_status=EXCLUDED.review_status,
                    updated_at=EXCLUDED.updated_at
                    ''',
                    (
                        track_id,
                        data.get('title', '').strip(),
                        data.get('description', '').strip(),
                        data.get('category', '').strip(),
                        data.get('mood', '').strip(),
                        int(data.get('bpm') or 0),
                        int(data.get('duration_seconds') or 0),
                        data.get('preview_audio_url', '').strip(),
                        data.get('download_audio_url', '').strip(),
                        data.get('cover_image_url', '').strip(),
                        data.get('status', 'draft'),
                        data.get('rights_status', 'missing'),
                        data.get('review_status', 'draft'),
                        _tw_now(),
                    )
                )
                log_admin_action('soundbank_track_upsert', track_id, 'status=' + data.get('status', 'draft'))
                return redirect('/admin/soundbank/tracks')
            except Exception as e:
                return jsonify({'error': '素材儲存失敗', 'detail': str(e)}), 500
        try:
            tracks = _tracks_from_db(get_db, include_all=True)
        except Exception:
            tracks = starter_tracks()
        rows = ''.join(
            '<tr><td>' + _esc(t.get('id')) + '</td><td>' + _esc(t.get('title')) + '</td><td>' + _esc(t.get('category')) + '</td><td>' + _esc(t.get('status')) + '</td><td>' + _esc(t.get('rights_status')) + '</td></tr>'
            for t in tracks
        )
        body = '''
        <h1>素材管理</h1>
        <form method="post">
          <label>素材 ID<input name="id" placeholder="例如 SB-PODCAST-001"></label>
          <label>標題<input name="title" required></label>
          <label>描述<textarea name="description"></textarea></label>
          <label>分類<input name="category" placeholder="Podcast BGM"></label>
          <label>情緒<input name="mood" placeholder="溫暖、穩定"></label>
          <label>BPM<input name="bpm" type="number" min="0"></label>
          <label>長度秒數<input name="duration_seconds" type="number" min="0"></label>
          <label>公開試聽 URL<input name="preview_audio_url"></label>
          <label>正式下載 URL<input name="download_audio_url"></label>
          <label>封面 URL<input name="cover_image_url"></label>
          <label>狀態<select name="status"><option value="draft">draft</option><option value="published">published</option><option value="investigating">investigating</option><option value="retired">retired</option></select></label>
          <label>權利狀態<select name="rights_status"><option value="missing">missing</option><option value="pending_review">pending_review</option><option value="verified">verified</option><option value="blocked">blocked</option></select></label>
          <label>審核狀態<select name="review_status"><option value="draft">draft</option><option value="reviewing">reviewing</option><option value="approved">approved</option><option value="rejected">rejected</option></select></label>
          <button class="button" type="submit">儲存素材</button>
        </form>
        <h2>目前素材</h2>
        <table><thead><tr><th>ID</th><th>標題</th><th>分類</th><th>狀態</th><th>權利</th></tr></thead><tbody>''' + rows + '''</tbody></table>
        '''
        return _page('素材管理', body, 'soundbank')

    @app.route('/admin/soundbank/orders')
    def admin_soundbank_orders():
        guard = _admin_guard(is_admin_token_valid, check_admin_ip)
        if guard:
            return guard
        try:
            orders = _fetch_all(get_db, '''
                SELECT order_id, track_id, license_type, amount, currency, buyer_email,
                       payment_provider, payment_status, terms_version, created_at, paid_at
                FROM soundbank_orders
                ORDER BY created_at DESC
                LIMIT 100
            ''')
        except Exception:
            orders = []
        rows = ''.join(
            '<tr><td>' + _esc(o.get('order_id')) + '</td><td>' + _esc(o.get('track_id')) + '</td><td>' + _esc(o.get('license_type')) + '</td><td>' + _money(o.get('amount')) + '</td><td>' + _esc(o.get('payment_status')) + '</td><td>' + _esc(o.get('created_at')) + '</td></tr>'
            for o in orders
        ) or '<tr><td colspan="6">尚無聲庫訂單。</td></tr>'
        return _page('聲庫訂單', '<h1>聲庫訂單</h1><table><thead><tr><th>訂單</th><th>素材</th><th>授權</th><th>金額</th><th>狀態</th><th>建立</th></tr></thead><tbody>' + rows + '</tbody></table>', 'soundbank')

    @app.route('/admin/soundbank/rights-proofs')
    def admin_soundbank_rights_proofs():
        guard = _admin_guard(is_admin_token_valid, check_admin_ip)
        if guard:
            return guard
        try:
            rows_data = _fetch_all(get_db, '''
                SELECT track_id, creator, creation_method, ai_tool, third_party_sample,
                       commercial_allowed, sublicense_allowed, proof_url, updated_at
                FROM soundbank_rights_proofs
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 100
            ''')
        except Exception:
            rows_data = []
        rows = ''.join(
            '<tr><td>' + _esc(r.get('track_id')) + '</td><td>' + _esc(r.get('creator')) + '</td><td>' + _esc(r.get('creation_method')) + '</td><td>' + _esc(r.get('ai_tool')) + '</td><td>' + _esc(r.get('commercial_allowed')) + '/' + _esc(r.get('sublicense_allowed')) + '</td><td>' + _esc(r.get('proof_url')) + '</td></tr>'
            for r in rows_data
        ) or '<tr><td colspan="6">尚無 rights_proof。素材正式上架前必須補齊。</td></tr>'
        return _page('權利證明', '<h1>權利證明</h1><div class="notice warn">第一版規則：沒有明確可商用與可再授權證明，不應正式上架。</div><table><thead><tr><th>素材</th><th>創作者</th><th>方式</th><th>AI 工具</th><th>商用/再授權</th><th>證明</th></tr></thead><tbody>' + rows + '</tbody></table>', 'soundbank')

    @app.route('/admin/soundbank/violation-reports')
    def admin_soundbank_violation_reports():
        guard = _admin_guard(is_admin_token_valid, check_admin_ip)
        if guard:
            return guard
        try:
            reports = _fetch_all(get_db, '''
                SELECT id, reported_url, track_id, reporter_contact, reason, evidence_url,
                       status, resolution, created_at
                FROM soundbank_violation_reports
                ORDER BY created_at DESC
                LIMIT 100
            ''')
        except Exception:
            reports = []
        rows = ''.join(
            '<tr><td>' + _esc(r.get('id')) + '</td><td><a href="' + _esc(r.get('reported_url')) + '">' + _esc(r.get('reported_url')) + '</a></td><td>' + _esc(r.get('track_id')) + '</td><td>' + _esc(r.get('reason')) + '</td><td>' + _esc(r.get('status')) + '</td><td>' + _esc(r.get('created_at')) + '</td></tr>'
            for r in reports
        ) or '<tr><td colspan="6">尚無違規通報。</td></tr>'
        return _page('違規通報', '<h1>違規通報</h1><table><thead><tr><th>ID</th><th>網址</th><th>素材</th><th>原因</th><th>狀態</th><th>建立</th></tr></thead><tbody>' + rows + '</tbody></table>', 'soundbank')

    @app.route('/admin/soundbank/api/health')
    def admin_soundbank_health():
        guard = _admin_guard(is_admin_token_valid, check_admin_ip)
        if guard:
            return guard
        return jsonify({
            'soundbank_enabled': soundbank_enabled(),
            'soundbank_init_db': soundbank_should_initialize(),
            'public_routes': ['/soundbank', '/soundbank/tracks', '/soundbank/license', '/soundbank/support'],
            'secure_routes': [
                '/soundbank/download/<order_id>',
                '/soundbank/license-certificate/<certificate_id>',
                '/soundbank/verify/<certificate_id>',
                '/soundbank/payment/webhook',
                '/soundbank/payment/ecpay/notify',
                '/soundbank/payment/ecpay/return',
            ],
            'signing_secret_configured': _has_configured_soundbank_secret(),
            'webhook_secret_configured': bool(os.environ.get('SOUNDBANK_PAYMENT_WEBHOOK_SECRET', '').strip()),
            'public_master_urls_allowed': _allow_public_master_urls(),
            'fake_checkout_enabled': _bool_env('SOUNDBANK_FAKE_CHECKOUT_ENABLED', False),
            'object_storage_configured': bool(
                _storage_env('OBJECT_STORAGE_ACCESS_KEY_ID', '')
                and _storage_env('OBJECT_STORAGE_SECRET_ACCESS_KEY', '')
            ),
            'ecpay_configured': bool(
                _ecpay_credentials().get('merchant_id')
                and _ecpay_credentials().get('hash_key')
                and _ecpay_credentials().get('hash_iv')
            ),
            'ecpay_payment_url': _ecpay_payment_url(),
            'ecpay_autosubmit': _bool_env('SOUNDBANK_ECPAY_AUTOSUBMIT', False),
            'ecpay_accept_simulated': _bool_env('SOUNDBANK_ECPAY_ACCEPT_SIMULATED', False),
            'bot_base_url': bot_base_url,
        })

    @app.route('/admin/soundbank/api/soft-open-monitor')
    def admin_soundbank_soft_open_monitor():
        guard = _admin_guard(is_admin_token_valid, check_admin_ip)
        if guard:
            return guard

        known_order_id = (request.args.get('order_id') or '').strip()
        try:
            status_counts = _fetch_all(get_db, '''
                SELECT LOWER(COALESCE(payment_status,'')) AS payment_status, COUNT(*) AS count
                FROM soundbank_orders
                GROUP BY LOWER(COALESCE(payment_status,''))
                ORDER BY LOWER(COALESCE(payment_status,''))
            ''')
            latest_orders = _fetch_all(get_db, '''
                SELECT order_id, track_id, license_type, amount, currency,
                       payment_provider, payment_status, merchant_order_no,
                       provider_trade_no, terms_version, created_at, paid_at, updated_at
                FROM soundbank_orders
                ORDER BY created_at DESC
                LIMIT 20
            ''')
            risk_counts = {
                'downloads_for_non_paid_orders': _fetch_one(get_db, '''
                    SELECT COUNT(*) AS count
                    FROM soundbank_downloads d
                    JOIN soundbank_orders o ON o.order_id=d.order_id
                    WHERE LOWER(COALESCE(o.payment_status,''))!='paid'
                ''').get('count', 0),
                'active_certificates_for_non_paid_orders': _fetch_one(get_db, '''
                    SELECT COUNT(*) AS count
                    FROM soundbank_license_certificates c
                    JOIN soundbank_orders o ON o.order_id=c.order_id
                    WHERE LOWER(COALESCE(o.payment_status,''))!='paid'
                      AND COALESCE(c.revoked_at,'')=''
                ''').get('count', 0),
                'paid_orders_without_downloads': _fetch_one(get_db, '''
                    SELECT COUNT(*) AS count
                    FROM soundbank_orders o
                    WHERE LOWER(COALESCE(o.payment_status,''))='paid'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM soundbank_downloads d
                          WHERE d.order_id=o.order_id
                      )
                ''').get('count', 0),
                'paid_orders_without_active_certificates': _fetch_one(get_db, '''
                    SELECT COUNT(*) AS count
                    FROM soundbank_orders o
                    WHERE LOWER(COALESCE(o.payment_status,''))='paid'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM soundbank_license_certificates c
                          WHERE c.order_id=o.order_id
                            AND COALESCE(c.revoked_at,'')=''
                      )
                ''').get('count', 0),
            }
            known_order = None
            if known_order_id:
                known_order = _fetch_one(get_db, '''
                    SELECT o.order_id, o.track_id, o.license_type, o.amount, o.currency,
                           o.payment_provider, o.payment_status, o.merchant_order_no,
                           o.provider_trade_no, o.terms_version, o.created_at, o.paid_at,
                           (SELECT COUNT(*) FROM soundbank_downloads d WHERE d.order_id=o.order_id) AS download_rows,
                           (SELECT COUNT(*) FROM soundbank_license_certificates c WHERE c.order_id=o.order_id AND COALESCE(c.revoked_at,'')='') AS active_certificates,
                           (SELECT COUNT(*) FROM soundbank_license_certificates c WHERE c.order_id=o.order_id AND COALESCE(c.revoked_at,'')!='') AS revoked_certificates
                    FROM soundbank_orders o
                    WHERE o.order_id=%s
                    LIMIT 1
                ''', (known_order_id,))
        except Exception as exc:
            return jsonify({'error': 'soft-open monitor query failed', 'detail': str(exc)}), 500

        return jsonify({
            'soundbank_enabled': soundbank_enabled(),
            'fake_checkout_enabled': _bool_env('SOUNDBANK_FAKE_CHECKOUT_ENABLED', False),
            'ecpay_accept_simulated': _bool_env('SOUNDBANK_ECPAY_ACCEPT_SIMULATED', False),
            'public_master_urls_allowed': _allow_public_master_urls(),
            'status_counts': status_counts,
            'risk_counts': risk_counts,
            'latest_orders': latest_orders,
            'known_order': known_order,
        })
