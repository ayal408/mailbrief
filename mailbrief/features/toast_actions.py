"""Buttons on the Windows notification: "⏰ in an hour" / "📅 tomorrow". Windows opens a MailBrief address for the
button; the address carries a signature (HMAC with this copy's secret), so only MailBrief's own notifications can set
reminders — a link in some email can't."""
import datetime as dt
import hashlib
import hmac
import os
import secrets

from mailbrief import config
from mailbrief.address import link
from mailbrief.features.reminders import remind_at
from mailbrief.storage import load_json, save_json
from mailbrief.web.token import TOKEN


def _path():
    return os.path.join(config.DATA, 'toast-items.json')


def sign(item_id, action):
    return hmac.new(TOKEN.encode(), f'{item_id}|{action}'.encode(), hashlib.sha256).hexdigest()[:20]


def buttons(item):
    """[(label, url)] for the email the notification is about."""
    items = load_json(_path(), {})
    item_id = secrets.token_hex(5)
    items[item_id] = {'subject': item.get('subject', ''), 'from': item.get('sender_name', ''), 'link': item.get('link', ''),
                      'account': item.get('account', ''), 'at': dt.datetime.now().isoformat(timespec='minutes')}
    save_json(_path(), dict(sorted(items.items(), key=lambda kv: kv[1]['at'])[-60:]))
    return [(label, link(f'toast_act?id={item_id}&do={action}&sig={sign(item_id, action)}'))
            for label, action in (('⏰ להזכיר בעוד שעה', 'hour'), ('📅 מחר בבוקר', 'tomorrow'))]


def act(item_id, action, signature, now=None):
    """Sets the reminder. Returns a short message, or raises ValueError for a bad / old link."""
    if action not in ('hour', 'tomorrow') or not hmac.compare_digest(signature or '', sign(item_id, action)):
        raise ValueError('קישור לא תקין')
    item = load_json(_path(), {}).get(item_id)
    if not item:
        raise ValueError('ההתראה ישנה מדי')
    now = now or dt.datetime.now().astimezone()
    when = now + dt.timedelta(hours=1) if action == 'hour' else (now + dt.timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    remind_at(when, item['subject'], item['from'], item['link'], item['account'])
    return when
