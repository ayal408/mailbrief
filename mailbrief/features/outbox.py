"""Scheduled sending: write now, send later — "after Shabbat", "Sunday morning", or any time. Nothing is ever sent
during Shabbat / Yom Tov: a time that falls inside one moves to its end."""
import datetime as dt
import mimetypes
import os
import re
import secrets
import shutil
from email.message import EmailMessage

from mailbrief import config
from mailbrief.features.calendar import holy_windows, is_holy_time
from mailbrief.mail import smtp
from mailbrief.storage import load_json, save_json
from mailbrief.util import e, safe_name


AFTER_HAVDALAH = dt.timedelta(minutes=20)
MAX_PER_RUN = 25              # per round (every few minutes while MailBrief runs) — gentle on Gmail's sending limits
EMAIL = re.compile(r'[^@\s<>",;]+@[^@\s<>",;]+\.[^@\s<>",;]+')


def _now():
    return dt.datetime.now().astimezone()


def outbox():
    return load_json(config.OUTBOX_FILE, [])


def out_of_holy(when, windows=None):
    """A moment inside Shabbat / Yom Tov moves to its end (+20 minutes)."""
    for start, end in (holy_windows() if windows is None else windows) or []:
        if start <= when < end + AFTER_HAVDALAH:
            return end + AFTER_HAVDALAH
    return when


def when_for(choice, custom='', now=None, windows=None):
    now = now or _now()
    windows = holy_windows() if windows is None else windows
    if choice == 'after_holy':
        upcoming = [w for w in (windows or []) if w[1] > now]
        if upcoming:
            return upcoming[0][1] + AFTER_HAVDALAH
        days = (5 - now.weekday()) % 7                  # no calendar: Saturday 20:30
        return (now + dt.timedelta(days=days)).replace(hour=20, minute=30, second=0, microsecond=0)
    if choice == 'sunday8':
        days = (6 - now.weekday()) % 7 or 7
        return out_of_holy((now + dt.timedelta(days=days)).replace(hour=8, minute=0, second=0, microsecond=0), windows)
    if choice == 'tomorrow8':
        return out_of_holy((now + dt.timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0), windows)
    moment = dt.datetime.fromisoformat(custom)
    moment = moment.astimezone() if moment.tzinfo is None else moment
    if moment <= now:
        raise ValueError('הזמן שנבחר כבר עבר')
    return out_of_holy(moment, windows)


def schedule(account, to, subject, body, send_at, files=(), thread=None):
    to = [a.strip() for a in re.split(r'[,;\s]+', to) if a.strip()]
    if not to or not all(EMAIL.fullmatch(a) for a in to):
        raise ValueError('כתובת הנמען לא נראית תקינה')
    if not subject.strip() and not body.strip():
        raise ValueError('המייל ריק')
    item = {'id': secrets.token_hex(4), 'account': account, 'to': to, 'subject': subject.strip()[:300], 'body': body[:50000],
            'send_at': send_at.isoformat(timespec='minutes'), 'created': _now().isoformat(timespec='minutes'), 'status': 'waiting'}
    if thread:
        item['thread'] = {k: thread.get(k, '') for k in ('in_reply_to', 'references')}
    if files:
        folder = os.path.join(config.DATA, 'outbox-files', item['id'])
        os.makedirs(folder, exist_ok=True)
        item['files'] = []
        for name, data in files:
            name = safe_name(name) or 'file'
            with open(os.path.join(folder, name), 'wb') as f:
                f.write(data)
            item['files'].append(name)
    save_json(config.OUTBOX_FILE, outbox() + [item])
    return item


def cancel(item_id):
    items = outbox()
    for it in items:
        if it['id'] == item_id and it['status'] == 'waiting':
            it['status'] = 'cancelled'
    save_json(config.OUTBOX_FILE, items)


def build(item, acc):
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = acc['email'], ', '.join(item['to']), item['subject']
    msg['X-MailBrief-Scheduled'] = '1'
    for header, key in (('In-Reply-To', 'in_reply_to'), ('References', 'references')):
        if (item.get('thread') or {}).get(key):
            msg[header] = item['thread'][key]
    msg.set_content(item['body'])
    msg.add_alternative(f'<div dir="auto" style="font-family:Arial;white-space:pre-wrap">{e(item["body"])}</div>', subtype='html')
    for name in item.get('files', []):
        path = os.path.join(config.DATA, 'outbox-files', item['id'], name)
        with open(path, 'rb') as f:
            ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
            main, sub = ctype.split('/', 1)
            msg.add_attachment(f.read(), maintype=main, subtype=sub, filename=name)
    return msg


def send_due(accounts=None, now=None):
    """Sends every scheduled mail whose time came (never during Shabbat / Yom Tov). Returns how many went out."""
    now = now or _now()
    if is_holy_time(now):
        return 0
    accounts = load_json(config.ACCOUNTS_FILE, []) if accounts is None else accounts
    items, sent = outbox(), 0
    for it in items:
        if it['status'] != 'waiting' or dt.datetime.fromisoformat(it['send_at']) > now:
            continue
        if sent >= MAX_PER_RUN:                        # greetings to many clients go out in small batches
            break
        acc = next((a for a in accounts if a['email'].lower() == it['account'].lower()), None)
        try:
            if not acc:
                raise RuntimeError('התיבה כבר לא מחוברת')
            smtp.send_mail(acc, build(it, acc))
            it['status'], it['sent'] = 'sent', now.isoformat(timespec='minutes')
            sent += 1
        except Exception as exc:
            it['status'], it['error'] = 'failed', str(exc)[:200]
    for it in items:                                  # sent or cancelled: their copies of the files can go
        if it['status'] in ('sent', 'cancelled') and it.get('files'):
            shutil.rmtree(os.path.join(config.DATA, 'outbox-files', it['id']), ignore_errors=True)
    done = [it for it in items if it['status'] != 'waiting']
    save_json(config.OUTBOX_FILE, [it for it in items if it['status'] == 'waiting'] + done[-50:])
    return sent
