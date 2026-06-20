import logging
import os

import psycopg2
from flask import Flask, jsonify, request

from soundbank import (
    init_soundbank_db,
    register_soundbank_routes,
    seed_soundbank_beta_originals,
    soundbank_should_initialize,
    soundbank_should_seed_beta_originals,
)


TRUE_VALUES = {'1', 'true', 'yes', 'on', 'enabled'}
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('SOUNDBANK_DATABASE_URL') or ''

os.environ.setdefault('SOUNDBANK_ENABLED', 'true')
os.environ.setdefault('SOUNDBANK_SHOW_STARTER_DEMOS', 'true')
os.environ.setdefault('SOUNDBANK_INIT_DB', 'false')
os.environ.setdefault('SOUNDBANK_FAKE_CHECKOUT_ENABLED', 'false')
os.environ.setdefault('SOUNDBANK_ALLOW_PUBLIC_MASTER_URLS', 'false')
os.environ.setdefault('SOUNDBANK_PUBLIC_BASE_URL', 'http://127.0.0.1:5000')

app = Flask(
    __name__,
    static_folder=os.path.join(PROJECT_ROOT, 'static'),
    static_url_path='/static',
)
app.config['JSON_AS_ASCII'] = False
app.json.ensure_ascii = False
app.json.sort_keys = False
app.logger.setLevel(logging.INFO)


def get_db():
    if not DATABASE_URL:
        raise RuntimeError('DATABASE_URL is not configured for standalone SoundBank.')
    conn = psycopg2.connect(DATABASE_URL, sslmode=os.environ.get('DATABASE_SSLMODE', 'require'))
    conn.autocommit = False
    return conn


def get_client_ip():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip:
        ip = ip.split(',')[0].strip()
    return ip or 'unknown'


def check_admin_ip():
    allowed = [ip.strip() for ip in os.environ.get('ADMIN_ALLOWED_IPS', '').split(',') if ip.strip()]
    if not allowed:
        return os.environ.get('ADMIN_IP_ALLOWLIST_REQUIRED', '').strip().lower() not in TRUE_VALUES
    return get_client_ip() in allowed


def is_admin_token_valid():
    expected = os.environ.get('ADMIN_TOKEN', '').strip()
    token = request.headers.get('X-Admin-Token', '').strip()
    return bool(expected and token and token == expected)


def log_admin_action(action, target='', detail=''):
    app.logger.info('admin action: %s target=%s detail=%s', action, target, detail)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    if request.path.startswith('/admin') or request.path.startswith('/soundbank/download/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, max-age=0, must-revalidate'
    return response


@app.route('/')
def root():
    return (
        '<!doctype html><meta charset="utf-8">'
        '<meta http-equiv="refresh" content="0; url=/soundbank">'
        '<a href="/soundbank">SoundBank</a>'
    )


@app.route('/healthz')
def healthz():
    database_configured = bool(DATABASE_URL)
    return jsonify({
        'ok': True,
        'service': 'soundbank-standalone',
        'database_configured': database_configured,
        'mode': 'database' if database_configured else 'starter-demo',
    })


if DATABASE_URL and soundbank_should_initialize():
    init_soundbank_db(get_db)
    if soundbank_should_seed_beta_originals():
        seed_soundbank_beta_originals(get_db)

register_soundbank_routes(
    app,
    get_db,
    is_admin_token_valid,
    check_admin_ip,
    log_admin_action,
    os.environ.get('SOUNDBANK_PUBLIC_BASE_URL', ''),
)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', '').strip().lower() in TRUE_VALUES
    app.run(host='0.0.0.0', port=port, debug=debug)
