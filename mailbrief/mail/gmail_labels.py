"""🎨 Gmail's own label colours. IMAP doesn't carry them, so they come from the Gmail API with the same sign-in
(the https://mail.google.com/ permission covers it). When the Gmail API isn't turned on for the key's Google Cloud
project, or offline, there are simply no colours — and MailBrief asks again only an hour later."""
import json
import time
import urllib.request

from mailbrief.net import TLS

_CACHE = {}         # address -> (when, {label path: {'bg', 'fg'}})


def colors(acc):
    if acc.get('auth') != 'google':
        return {}
    key = acc['email'].lower()
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < (6 * 3600 if hit[1] else 3600):
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
