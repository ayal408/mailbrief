""""Remind me" items."""
import datetime as dt
import secrets

from mailbrief import config
from mailbrief.features import notify
from mailbrief.storage import load_json, save_json


def add_reminder(days, subject, who, link, account, note=''):
    items = load_json(config.REMINDERS_FILE, [])
    due = dt.datetime.now().astimezone() + dt.timedelta(days=days)
    due = due.replace(hour=9, minute=0, second=0, microsecond=0) if days >= 1 else due
    items.append({'id': secrets.token_hex(4), 'due': due.isoformat(), 'subject': subject, 'from': who,
                  'link': link, 'account': account, 'note': note})
    save_json(config.REMINDERS_FILE, items)
    return due


def fire_reminders():
    items, now, left, fired = load_json(config.REMINDERS_FILE, []), dt.datetime.now().astimezone(), [], 0
    for r in items:
        if dt.datetime.fromisoformat(r['due']) <= now:
            notify.toast('⏰ תזכורת', [f'{r["subject"]} — {r["from"]}' + (f' · {r["note"]}' if r.get('note') else '')], r.get('link', ''))
            fired += 1
        else:
            left.append(r)
    if fired:
        save_json(config.REMINDERS_FILE, left)
    return fired
