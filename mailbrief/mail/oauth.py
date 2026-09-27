""""Sign in with Google / Microsoft" (OAuth 2 + PKCE) and access tokens."""
import base64
import hashlib
import json
import secrets
import urllib.request
from urllib.parse import urlencode

from mailbrief import config
from mailbrief.net import TLS, netfree_block, require_online
from mailbrief.storage import decrypt, encrypt, load_json


PROVIDERS = {
    'google': {
        'name': 'Google', 'host': 'imap.gmail.com',
        'auth': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token': 'https://oauth2.googleapis.com/token',
        'scope': 'openid email profile https://mail.google.com/',   # profile: the name and picture shown in MailBrief
        'redirect': f'http://127.0.0.1:{config.PORT}/oauth/callback',
        'extra': {'access_type': 'offline', 'prompt': 'consent select_account', 'include_granted_scopes': 'true'},
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


PENDING = {}    # state -> (provider, PKCE verifier, extra scope), lives only while the settings page is open


def bundled_client(provider):
    """The key built into MailBrief.exe (see RELEASING.md) — for Google only."""
    if provider != 'google':
        return '', ''
    cfg = load_json(config.BUNDLED_GOOGLE, {})
    cfg = cfg.get('installed', cfg)           # the file Google offers for download, or just {client_id, client_secret}
    if cfg.get('client_id'):                  # a build that carries a different key (google_client.json)
        return cfg['client_id'], cfg.get('client_secret', '')
    from mailbrief.mail import builtin_key
    return builtin_key.google()


def client_for(provider):
    """The user's own key when set in the settings, otherwise the one built into the program."""
    cfg = load_json(config.SETTINGS_FILE, {}).get(provider) or {}
    if cfg.get('client_id'):
        secret = decrypt(cfg['client_secret']) if cfg.get('client_secret') else ''
        return cfg['client_id'], secret
    return bundled_client(provider)


def clients(provider):
    """Every key this copy knows: the user's own (settings) and the built-in one."""
    cfg = load_json(config.SETTINGS_FILE, {}).get(provider) or {}
    own = [(cfg['client_id'], decrypt(cfg['client_secret']) if cfg.get('client_secret') else '')] if cfg.get('client_id') else []
    built_in = bundled_client(provider)
    return own + ([built_in] if built_in[0] and built_in[0] not in {c for c, _ in own} else [])


def token_request(provider, fields, client_id=None):
    """client_id: the key a mailbox was connected with — a refresh token only works with that same key."""
    known = dict(clients(provider))
    if client_id and client_id not in known:
        raise RuntimeError('התיבה חוברה עם מפתח התחברות אחר — צריך להתחבר מחדש לתיבה הזו (כפתור „חיבור עם Google”)')
    client_id, secret = (client_id, known[client_id]) if client_id else client_for(provider)
    fields = {'client_id': client_id, **fields}
    if secret:
        fields['client_secret'] = secret
    require_online()
    req = urllib.request.Request(PROVIDERS[provider]['token'], data=urlencode(fields).encode(),
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=30, context=TLS) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if netfree_block(exc):
            raise RuntimeError(netfree_block(exc)) from None
        detail = exc.read().decode('utf-8', 'replace')
        if 'invalid_grant' in detail or 'unauthorized_client' in detail:
            raise RuntimeError('ההרשאה פגה, בוטלה או ניתנה למפתח אחר — צריך להתחבר מחדש לתיבה הזו (כפתור „חיבור עם Google”)') from None
        raise RuntimeError(f'שגיאת התחברות מול {PROVIDERS[provider]["name"]}: {detail[:200]}') from None


def access_token(acc):
    fields = {'grant_type': 'refresh_token', 'refresh_token': decrypt(acc['refresh'])}
    if acc.get('client_id'):
        data = token_request(acc['auth'], fields, acc['client_id'])
    else:                                       # connected before MailBrief remembered the key: find the one that works
        error = None
        for client_id, _ in clients(acc['auth']) or [(None, '')]:
            try:
                data = token_request(acc['auth'], fields, client_id)
                if client_id:
                    acc['client_id'] = client_id
                break
            except RuntimeError as exc:
                error = exc
        else:
            raise error
    if data.get('refresh_token'):               # Microsoft rotates refresh tokens
        acc['refresh'] = encrypt(data['refresh_token'])
    return data['access_token']


def jwt_claims(token):
    try:
        payload = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except Exception:
        return {}


def start_oauth(provider, extra_scope='', login_hint=''):
    """extra_scope: more permissions on top of mail (Google Calendar / Tasks); login_hint: preselect that account."""
    client_id, _ = client_for(provider)
    if not client_id:
        raise RuntimeError(f'קודם צריך להשלים את ההגדרה החד-פעמית של {PROVIDERS[provider]["name"]} (למטה)')
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    state = secrets.token_urlsafe(24)
    PENDING[state] = (provider, verifier, extra_scope)
    p = PROVIDERS[provider]
    return p['auth'] + '?' + urlencode({
        'client_id': client_id, 'redirect_uri': p['redirect'], 'response_type': 'code',
        'scope': f"{p['scope']} {extra_scope}".strip(), 'state': state, 'code_challenge': challenge,
        'code_challenge_method': 'S256', **p['extra'], **({'login_hint': login_hint} if login_hint else {})})
