"""One-click unsubscribe through the sender's official link."""
import datetime as dt
import hashlib
import urllib.request

from mailbrief import config
from mailbrief.net import TLS, _NoRedirect, safe_public_https
from mailbrief.storage import load_json, save_json


def unsub_id(account, sender):
    return hashlib.sha1(f'{account.lower()}|{sender.lower()}'.encode()).hexdigest()[:12]


def remember_unsubs(results):
    """Keep every newsletter's official unsubscribe link, so the report and settings page can act on it."""
    unsubs = load_json(config.UNSUBS_FILE, {})
    for res in results:
        for it in res['items']:
            if 'newsletters' in it['cats'] and it.get('unsub'):
                key = unsub_id(res['email'], it['sender'])
                entry = unsubs.setdefault(key, {'account': res['email'], 'sender': it['sender'], 'count': 0})
                entry.update(it['unsub'], name=it['sender_name'], last=dt.date.today().isoformat())
                entry['count'] += 1
    save_json(config.UNSUBS_FILE, unsubs)


def unsubscribe(entry):
    """Returns ('done', msg) when handled here, or ('open', url) when the user must finish on the sender's page."""
    url = entry.get('url', '')
    if url and entry.get('one_click') and safe_public_https(url):
        req = urllib.request.Request(url, data=b'List-Unsubscribe=One-Click', method='POST', headers={
            'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'MailBrief/1.0'})
        try:
            with urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=TLS)).open(req, timeout=20) as resp:
                ok = 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            ok = 200 <= exc.code < 400
        if ok:
            return 'done', f'✓ בוטל המנוי ל-{entry.get("name") or entry["sender"]}'
    if url and safe_public_https(url):
        return 'open', url
    if entry.get('mailto'):
        return 'open', entry['mailto']
    return 'done', 'לשולח הזה אין קישור ביטול בטוח — אפשר לסמן אותו כספאם ב-Gmail'
