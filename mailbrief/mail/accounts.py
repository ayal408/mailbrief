"""Connecting a mailbox after sign-in, and friendly Hebrew error messages."""
import imaplib
import re
import secrets

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.mail.domains import MICROSOFT
from mailbrief.mail.oauth import jwt_claims, PENDING, PROVIDERS, token_request
from mailbrief.storage import encrypt, load_json, save_json


def finish_oauth(query):
    pending = PENDING.pop(query.get('state', [''])[0], None)
    if not pending:
        return 'הבקשה פגה — לחצי שוב על כפתור החיבור'
    if 'error' in query:
        return f'ההתחברות בוטלה ({query["error"][0]})'
    provider, verifier = pending
    p = PROVIDERS[provider]
    data = token_request(provider, {'grant_type': 'authorization_code', 'code': query['code'][0],
                                    'redirect_uri': p['redirect'], 'code_verifier': verifier})
    claims = jwt_claims(data.get('id_token', ''))
    address = claims.get('email') or claims.get('preferred_username') or ''
    if not address or not data.get('refresh_token'):
        return 'ההתחברות הצליחה חלקית — לא התקבלה כתובת או הרשאה קבועה. נסי שוב.'
    acc = {'id': secrets.token_hex(4), 'email': address, 'user': address, 'auth': provider,
           'host': p['host'], 'port': 993, 'tag': True, 'refresh': encrypt(data['refresh_token'])}
    try:
        imap.connect(acc).logout()
    except Exception as exc:
        return f'{address}: ההתחברות אושרה אבל IMAP נכשל — {friendly_error(exc, acc)}'
    accounts = [a for a in load_json(config.ACCOUNTS_FILE, []) if a['email'].lower() != address.lower()]
    save_json(config.ACCOUNTS_FILE, accounts + [acc])
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
        return 'ההתחברות נכשלה — בדקי את הסיסמה ושהגישה ב-IMAP מופעלת בהגדרות התיבה.'
    return f'{type(exc).__name__}: {text[:200]}'
