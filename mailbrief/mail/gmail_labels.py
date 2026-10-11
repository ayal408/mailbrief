"""🎨 Gmail's own label colours. IMAP doesn't carry them, so they come from the Gmail API with the same sign-in
(the https://mail.google.com/ permission covers it). When the Gmail API isn't turned on for the key's Google Cloud
project, or offline, there are simply no colours — and MailBrief asks again 5 minutes later (so turning the
API on shows them soon)."""
import json
import time
import urllib.error
import urllib.request

from mailbrief.net import TLS

_CACHE = {}         # address -> (when, {label path: {'bg', 'fg'}})


def colors(acc):
    if acc.get('auth') != 'google':
        return {}
    key = acc['email'].lower()
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < (6 * 3600 if hit[1] else 5 * 60):     # no colours yet: ask again in 5 minutes
        return hit[1]
    out = {}
    try:
        from mailbrief.mail.oauth import access_token
        req = urllib.request.Request('https://gmail.googleapis.com/gmail/v1/users/me/labels',
                                     headers={'Authorization': 'Bearer ' + access_token(acc)})
        with urllib.request.urlopen(req, timeout=15, context=TLS) as resp:
            for label in json.load(resp).get('labels', []):
                c = label.get('color') or {}
                if c.get('backgroundColor'):
                    out[label['name']] = {'bg': c['backgroundColor'], 'fg': c.get('textColor', '')}
    except Exception:
        pass
    _CACHE[key] = (time.time(), out)
    return out


# ---- changing things in Gmail (the same Gmail API) -----------------------------------------------------------------------

def _call(acc, method, path, body=None):
    from mailbrief.mail.oauth import access_token
    req = urllib.request.Request('https://gmail.googleapis.com/gmail/v1/users/me/' + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': 'Bearer ' + access_token(acc), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20, context=TLS) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        if exc.code == 403 and ('has not been used' in detail or 'disabled' in detail):
            raise RuntimeError('צריך להפעיל את Gmail API בפרויקט של המפתח ב-Google Cloud') from None
        raise RuntimeError(f'Gmail: שגיאה {exc.code}') from None


# 🗂️ Gmail's categories by their label ids (ראשי is CATEGORY_PERSONAL)
CATEGORY_IDS = {'primary': 'CATEGORY_PERSONAL', 'promotions': 'CATEGORY_PROMOTIONS', 'social': 'CATEGORY_SOCIAL',
                'updates': 'CATEGORY_UPDATES', 'forums': 'CATEGORY_FORUMS'}


def set_category(acc, gids, key):
    """Moves messages (Gmail ids, hex) to another inbox category — and back into the inbox, where categories show."""
    if key not in CATEGORY_IDS:
        raise ValueError('קטגוריה לא מוכרת')
    ids = [g for g in gids if g]
    if not ids:
        raise RuntimeError('לא נמצא מזהה Gmail להודעות')
    for i in range(0, len(ids), 1000):
        _call(acc, 'POST', 'messages/batchModify', {'ids': ids[i:i + 1000], 'addLabelIds': [CATEGORY_IDS[key], 'INBOX'],
                                                    'removeLabelIds': [v for k, v in CATEGORY_IDS.items() if k != key]})


# Gmail accepts only its own palette for label colours: MailBrief's colours, each matched to the nearest one
GMAIL_PALETTE = {'#7c3aed': '#8e63ce', '#f97316': '#ffad47', '#0ea5e9': '#4a86e8', '#16a34a': '#16a766', '#ec4899': '#f691b3',
                 '#ca8a04': '#d5ae49', '#dc2626': '#cc3a21', '#14b8a6': '#2da2bb', '#6366f1': '#3c78d8', '#64748b': '#666666'}


def set_color(acc, label_path, color):
    """🎨 The label's colour in Gmail itself (so Gmail and every other device show it too)."""
    if color not in GMAIL_PALETTE:
        raise ValueError('צבע לא מוכר')
    labels = _call(acc, 'GET', 'labels').get('labels', [])
    label = next((l for l in labels if l.get('name') == label_path), None)
    if not label or label.get('type') == 'system':
        raise RuntimeError('התווית לא נמצאה ב-Gmail')
    _call(acc, 'PATCH', 'labels/' + label['id'], {'color': {'backgroundColor': GMAIL_PALETTE[color], 'textColor': '#ffffff'}})
    _CACHE.pop(acc['email'].lower(), None)                 # the new colour shows at once
