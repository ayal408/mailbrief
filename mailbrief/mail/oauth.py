""""Sign in with Google / Microsoft" (OAuth 2 + PKCE) and access tokens."""
import base64
import hashlib
import json
import secrets
import urllib.request
from urllib.parse import urlencode

from mailbrief import config
from mailbrief.storage import decrypt, encrypt, load_json


PROVIDERS = {
    'google': {
        'name': 'Google', 'host': 'imap.gmail.com',
        'auth': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token': 'https://oauth2.googleapis.com/token',
        'scope': 'openid email https://mail.google.com/',
        'redirect': f'http://127.0.0.1:{config.PORT}/oauth/callback',
        'extra': {'access_type': 'offline', 'prompt': 'consent select_account'},
    },
    'microsoft': {
        'name': 'Microsoft', 'host': 'outlook.office365.com',
        'auth': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
        'token': 'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        'scope': 'openid email offline_access https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send',
        'redirect': f'http://localhost:{config.PORT}/oauth/callback',
        'extra': {'prompt': 'select_account'},
    },
}


PENDING = {}    # state -> (provider, PKCE verifier), lives only while the settings page is open


def client_for(provider):
    cfg = load_json(config.SETTINGS_FILE, {}).get(provider) or {}
    secret = decrypt(cfg['client_secret']) if cfg.get('client_secret') else ''
    return cfg.get('client_id', ''), secret


def token_request(provider, fields):
    client_id, secret = client_for(provider)
    fields = {'client_id': client_id, **fields}
    if secret:
        fields['client_secret'] = secret
    req = urllib.request.Request(PROVIDERS[provider]['token'], data=urlencode(fields).encode(),
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        if 'invalid_grant' in detail:
            raise RuntimeError('ההרשאה פגה או בוטלה — צריך להתחבר מחדש לתיבה הזו') from None
        raise RuntimeError(f'שגיאת התחברות מול {PROVIDERS[provider]["name"]}: {detail[:200]}') from None


def access_token(acc):
    data = token_request(acc['auth'], {'grant_type': 'refresh_token', 'refresh_token': decrypt(acc['refresh'])})
    if data.get('refresh_token'):               # Microsoft rotates refresh tokens
        acc['refresh'] = encrypt(data['refresh_token'])
    return data['access_token']


def jwt_claims(token):
    try:
        payload = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except Exception:
        return {}


def start_oauth(provider):
    client_id, _ = client_for(provider)
    if not client_id:
        raise RuntimeError(f'קודם צריך להשלים את ההגדרה החד-פעמית של {PROVIDERS[provider]["name"]} (למטה)')
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    state = secrets.token_urlsafe(24)
    PENDING[state] = (provider, verifier)
    p = PROVIDERS[provider]
    return p['auth'] + '?' + urlencode({
        'client_id': client_id, 'redirect_uri': p['redirect'], 'response_type': 'code', 'scope': p['scope'],
        'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256', **p['extra']})
