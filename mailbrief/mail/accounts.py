"""Connecting a mailbox after sign-in, and friendly Hebrew error messages."""
import imaplib
import re
import secrets

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.mail.domains import MICROSOFT
from mailbrief.mail.oauth import jwt_claims, PENDING, PROVIDERS, token_request
from mailbrief.storage import encrypt, load_json, save_json


APPS_SCOPES = ('https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/tasks')
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file'      # only files MailBrief itself creates (the encrypted backup)


def finish_oauth(query):
    pending = PENDING.pop(query.get('state', [''])[0], None)
    if not pending:
        return 'הבקשה פגה — צריך ללחוץ שוב על כפתור החיבור'
    if 'error' in query:
        return f'ההתחברות בוטלה ({query["error"][0]})'
    provider, verifier, extra_scope = pending
    p = PROVIDERS[provider]
    data = token_request(provider, {'grant_type': 'authorization_code', 'code': query['code'][0],
                                    'redirect_uri': p['redirect'], 'code_verifier': verifier})
    claims = jwt_claims(data.get('id_token', ''))
    address = claims.get('email') or claims.get('preferred_username') or ''
    if not address or not data.get('refresh_token'):
        return 'ההתחברות הצליחה חלקית — לא התקבלה כתובת או הרשאה קבועה. אפשר לנסות שוב.'
    accounts = load_json(config.ACCOUNTS_FILE, [])
    old = next((a for a in accounts if a['email'].lower() == address.lower()), {})
    acc = {'id': secrets.token_hex(4), 'tag': True, **old, 'email': address, 'user': address, 'auth': provider,
           'host': p['host'], 'port': 993, 'refresh': encrypt(data['refresh_token'])}    # reconnecting keeps settings
    acc.pop('password', None)
    if (acc.get('last') or {}).get('error'):
        acc.pop('last')                           # the old sign-in error no longer applies
    granted = set(data.get('scope', '').split())
    acc['gapps'] = provider == 'google' and all(s in granted for s in APPS_SCOPES)
    acc['drive'] = provider == 'google' and DRIVE_SCOPE in granted
    try:
        imap.connect(acc).logout()
    except Exception as exc:
        return f'{address}: ההתחברות אושרה אבל IMAP נכשל — {friendly_error(exc, acc)}'
    save_json(config.ACCOUNTS_FILE, [a for a in accounts if a['email'].lower() != address.lower()] + [acc])
    if DRIVE_SCOPE in extra_scope:
        return (f'✓ Google Drive של {address} מחובר — אפשר לשמור גיבוי מוצפן' if acc['drive'] else
                f'{address}: בלי גישה ל-Google Drive — צריך לסמן את תיבת הסימון בחלון של Google')
    if extra_scope and not acc['gapps']:
        return f'{address} חוברה, אבל בלי גישה ליומן ולמשימות — צריך לסמן את שתי תיבות הסימון בחלון של Google'
    if extra_scope:
        return f'✓ היומן והמשימות של {address} מחוברים — מופיעים עכשיו ב„היום שלי”'
    return f'✓ {address} חוברה בהצלחה'


def friendly_error(exc, acc):
    text = str(exc)
    if isinstance(exc, RuntimeError):
        return text
    if isinstance(exc, imaplib.IMAP4.error) and re.search(r'auth|login|credential|password', text, re.I):
        if acc.get('auth') in PROVIDERS:
            return 'השרת דחה את ההרשאה — צריך להתחבר מחדש לתיבה הזו'
        domain = acc['email'].rsplit('@', 1)[-1].lower()
        if domain in MICROSOFT or domain in ('gmail.com', 'googlemail.com'):
            return 'לחשבון הזה צריך להשתמש בכפתור „חיבור עם Google / Microsoft” ולא בסיסמה.'
        return 'ההתחברות נכשלה — כדאי לבדוק את הסיסמה ושהגישה ב-IMAP מופעלת בהגדרות התיבה.'
    return f'{type(exc).__name__}: {text[:200]}'
