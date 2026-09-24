"""Snooze: an email leaves the inbox and comes back — unread, with a notification — on the chosen day.
Gmail: the Inbox label comes off and a "💤" label goes on. Other mailboxes: it moves to a "💤" folder and back.
Nothing wakes up during Shabbat / Yom Tov; it waits for the end."""
import datetime as dt
import secrets

from mailbrief import config
from mailbrief.features import notify
from mailbrief.features.calendar import is_holy_time
from mailbrief.mail import imap
from mailbrief.mail.classify import TAG_PREFIX
from mailbrief.mail.imap import delimiter, is_gmail, special_folder, utf7
from mailbrief.storage import load_json, save_json


LABEL = '💤 נודניק'


def snoozed():
    return load_json(config.SNOOZE_FILE, [])


def _folder(m, acc):
    sep = '/' if is_gmail(acc) else delimiter(m)
    name = utf7(f'{TAG_PREFIX}{sep}{LABEL}')
    m.create(f'"{utf7(TAG_PREFIX)}"')
    m.create(f'"{name}"')                               # "already exists" is fine
    return name


def _find(m, message_id):
    typ, data = m.uid('SEARCH', None, 'HEADER', 'Message-ID', f'"{message_id.replace(chr(34), "")}"')
    uids = data[0].split() if typ == 'OK' and data and data[0] else []
    return uids[-1] if uids else None


def _account(address):
    accounts = load_json(config.ACCOUNTS_FILE, [])
    acc = next((a for a in accounts if a['email'].lower() == (address or '').lower()), None)
    if not acc:
        raise RuntimeError('התיבה לא נמצאה')
    return acc, accounts


def snooze(account, message_id, subject, until, link=''):
    if not message_id:
        raise RuntimeError('אין מזהה להודעה הזו')
    acc, accounts = _account(account)
    m = imap.connect(acc)
    try:
        name = _folder(m, acc)
        if is_gmail(acc):
            m.select(f'"{special_folder(m, chr(92) + "All") or "INBOX"}"')
            uid = _find(m, message_id)
            if not uid:
                raise RuntimeError('ההודעה לא נמצאה בתיבה')
            m.uid('STORE', uid, '+X-GM-LABELS', f'("{name}")')
            m.uid('STORE', uid, '-X-GM-LABELS', r'(\Inbox)')
        else:
            m.select('INBOX')
            uid = _find(m, message_id)
            if not uid:
                raise RuntimeError('ההודעה לא נמצאה בתיבת הדואר הנכנס')
            if m.uid('MOVE', uid, f'"{name}"')[0] != 'OK':          # servers without MOVE: copy + delete
                m.uid('COPY', uid, f'"{name}"')
                m.uid('STORE', uid, '+FLAGS', r'(\Deleted)')
                m.expunge()
    finally:
        m.logout()
        save_json(config.ACCOUNTS_FILE, accounts)
    item = {'id': secrets.token_hex(4), 'account': acc['email'], 'message_id': message_id, 'subject': subject[:200],
            'link': link, 'until': until.isoformat(timespec='minutes')}
    save_json(config.SNOOZE_FILE, [s for s in snoozed() if s['message_id'] != message_id] + [item])
    return item


def _wake(acc, item):
    m = imap.connect(acc)
    try:
        name = _folder(m, acc)
        if is_gmail(acc):
            m.select(f'"{special_folder(m, chr(92) + "All") or "INBOX"}"')
            uid = _find(m, item['message_id'])
            if uid:
                m.uid('STORE', uid, '+X-GM-LABELS', r'(\Inbox)')
                m.uid('STORE', uid, '-X-GM-LABELS', f'("{name}")')
                m.uid('STORE', uid, '-FLAGS', r'(\Seen)')
        else:
            m.select(f'"{name}"')
            uid = _find(m, item['message_id'])
            if uid:
                m.uid('STORE', uid, '-FLAGS', r'(\Seen)')
                if m.uid('MOVE', uid, 'INBOX')[0] != 'OK':
                    m.uid('COPY', uid, 'INBOX')
                    m.uid('STORE', uid, '+FLAGS', r'(\Deleted)')
                    m.expunge()
    finally:
        m.logout()


def wake_now(item_id):
    item = next((s for s in snoozed() if s['id'] == item_id), None)
    if not item:
        return None
    acc, accounts = _account(item['account'])
    _wake(acc, item)
    save_json(config.ACCOUNTS_FILE, accounts)
    save_json(config.SNOOZE_FILE, [s for s in snoozed() if s['id'] != item_id])
    return item


def wake_due(now=None):
    """Brings back every snoozed email whose day came. Returns how many."""
    now = now or dt.datetime.now().astimezone()
    items = snoozed()
    if not items or is_holy_time(now):
        return 0
    accounts = load_json(config.ACCOUNTS_FILE, [])
    left, woke = [], []
    for item in items:
        acc = next((a for a in accounts if a['email'].lower() == item['account'].lower()), None)
        if dt.datetime.fromisoformat(item['until']) > now or not acc:
            left.append(item) if acc else None
            continue
        try:
            _wake(acc, item)
            woke.append(item)
        except Exception:
            left.append(item)                              # try again next time
    save_json(config.SNOOZE_FILE, left)
    save_json(config.ACCOUNTS_FILE, accounts)
    if woke:
        notify.toast('💤 חזר לתיבה' if len(woke) == 1 else f'💤 {len(woke)} מיילים חזרו לתיבה',
                     [w['subject'] for w in woke[:2]], woke[0].get('link', ''))
    return len(woke)
