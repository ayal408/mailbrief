"""Windows notifications and the Telegram mirror."""
import json
import os
import subprocess
import urllib.request
from urllib.parse import urlencode
from xml.sax.saxutils import escape as xml_escape
from xml.sax.saxutils import quoteattr

from mailbrief import config
from mailbrief.features.calendar import is_holy_time, paused_until
from mailbrief.net import _PUBLIC_TLS
from mailbrief.storage import decrypt, load_json


def telegram_cfg():
    cfg = load_json(config.SETTINGS_FILE, {}).get('telegram') or {}
    token = decrypt(cfg['token']) if cfg.get('token') else ''
    return token, cfg.get('chat_id'), cfg.get('mirror', True)


def telegram_api(token, method, fields):
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}', data=urlencode(fields).encode(),
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_PUBLIC_TLS) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')
        try:
            detail = json.loads(body).get('description', exc.code)
        except ValueError:
            detail = f'HTTP {exc.code}'
        if exc.code == 418 or 'netfree' in body.lower():
            detail = ('החיבור לטלגרם חסום ע״י נטפרי. אפשר לבקש מנטפרי לפתוח את api.telegram.org, '
                      'ובינתיים להשתמש בפעולת „✉️ מייל אליי” — היא מגיעה לאפליקציית Gmail בטלפון')
        elif exc.code in (401, 404):
            detail = 'ה-token לא תקין — להעתיק אותו שוב מ-@BotFather'
        raise RuntimeError(f'טלגרם: {detail}') from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f'אין חיבור לטלגרם ({exc.reason})') from None
    if not data.get('ok'):
        raise RuntimeError(f'טלגרם: {data.get("description", "שגיאה")}')
    return data['result']


def telegram_send(text, link=''):
    token, chat, _ = telegram_cfg()
    if not token or not chat:
        raise RuntimeError('טלגרם עוד לא מחובר (בדף ההגדרות)')
    fields = {'chat_id': chat, 'text': text[:4000], 'disable_web_page_preview': 'true'}
    if link.startswith('https://'):                # a local 127.0.0.1 link is useless on the phone
        fields['reply_markup'] = json.dumps({'inline_keyboard': [[{'text': '📬 פתיחה', 'url': link}]]})
    telegram_api(token, 'sendMessage', fields)


POWERSHELL_TOAST = r'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml($env:MAILBRIEF_TOAST)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
'''


def toast(title, lines, link=''):
    if is_holy_time() or paused_until():
        return
    token, chat, mirror = telegram_cfg()
    if token and chat and mirror:                # the same alert on the phone
        try:
            telegram_send(f'{title}\n' + '\n'.join(lines[:2]), link)
        except Exception:
            pass
    body = ''.join(f'<text>{xml_escape(line[:180])}</text>' for line in lines[:2])
    launch = f' activationType="protocol" launch={quoteattr(link)}' if link else ''
    xml = f'<toast{launch}><visual><binding template="ToastGeneric"><text>{xml_escape(title)}</text>{body}</binding></visual></toast>'
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', POWERSHELL_TOAST],
                   env={**os.environ, 'MAILBRIEF_TOAST': xml}, creationflags=0x08000000, timeout=30)
