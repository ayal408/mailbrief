"""Explicit reminders and opt-in automatic suggestions, with persistent dismissal."""
import datetime as dt
import os
import secrets

from mailbrief import config
from mailbrief.features import notify
from mailbrief.storage import locked, load_json, save_json


def automatic_enabled():
    return bool(load_json(config.SETTINGS_FILE, {}).get('auto_reminders', False))


def _dismissed_path():
    return os.path.join(config.DATA, 'dismissed-reminders.json')


def _key(subject, account):
    return account.lower() + '|' + subject


def unwanted(subject, account):
    return _key(subject, account) in load_json(_dismissed_path(), {})


@locked(lambda: config.REMINDERS_FILE)
def decline(subject, account):
    declined = load_json(_dismissed_path(), {})
    declined[_key(subject, account)] = dt.datetime.now().isoformat()
    save_json(_dismissed_path(), declined)
    rows = load_json(config.REMINDERS_FILE, [])
    save_json(config.REMINDERS_FILE, [r for r in rows if _key(r['subject'], r.get('account', '')) != _key(subject, account)])


@locked(lambda: config.REMINDERS_FILE)
def remove(item_id):
    rows = load_json(config.REMINDERS_FILE, [])
    item = next((r for r in rows if r['id'] == item_id), None)
    if item:
        decline(item['subject'], item.get('account', ''))


@locked(lambda: config.REMINDERS_FILE)
def clear():
    declined = load_json(_dismissed_path(), {})
    for item in load_json(config.REMINDERS_FILE, []):
        declined[_key(item['subject'], item.get('account', ''))] = dt.datetime.now().isoformat()
    save_json(_dismissed_path(), declined)
    save_json(config.REMINDERS_FILE, [])


def add_reminder(days, subject, who, link, account, note='', source='manual'):
    due = dt.datetime.now().astimezone() + dt.timedelta(days=days)
    due = due.replace(hour=9, minute=0, second=0, microsecond=0) if days >= 1 else due
    return remind_at(due, subject, who, link, account, note, source)


@locked(lambda: config.REMINDERS_FILE)
def remind_at(when, subject, who, link, account, note='', source='manual'):
    if source != 'manual' and (not automatic_enabled() or unwanted(subject, account)):
        return None
    items = load_json(config.REMINDERS_FILE, [])
    if source == 'manual':  # an explicit request can restore a previously declined reminder
        declined = load_json(_dismissed_path(), {})
        declined.pop(_key(subject, account), None)
        save_json(_dismissed_path(), declined)
    if any(r['subject'] == subject and r.get('account', '').lower() == account.lower()
           and r['due'] == when.isoformat() for r in items):
        return when
    items.append({'id': secrets.token_hex(4), 'due': when.isoformat(), 'subject': subject, 'from': who,
                  'link': link, 'account': account, 'note': note, 'source': source})
    save_json(config.REMINDERS_FILE, items)
    return when


def _source(item):
    if item.get('source'):
        return item['source']
    # Recognize reminders made by older releases, before source metadata existed.
    if item.get('subject', '').startswith(('🤝 הבטחת ל', '📝 לשלוח סיכום פגישה:', 'מחר: ')):
        return 'automatic'
    return 'manual'


@locked(lambda: config.REMINDERS_FILE)
def fire_reminders():
    settings = load_json(config.SETTINGS_FILE, {})
    if not settings.get('reminders_enabled', True) or not settings.get('notifications_enabled', True):
        return 0
    items, now = load_json(config.REMINDERS_FILE, []), dt.datetime.now().astimezone()
    due = [r for r in items if not r.get('notified') and not unwanted(r['subject'], r.get('account', ''))
           and (_source(r) == 'manual' or automatic_enabled())
           and dt.datetime.fromisoformat(r['due']) <= now]
    if not due:
        return 0
    from mailbrief.address import link
    from mailbrief.features.toast_actions import buttons
    first = due[0]
    shown = notify.toast('⏰ תזכורת' if len(due) == 1 else f'⏰ {len(due)} תזכורות',
                         [f'{r["subject"]} — {r["from"]}' + (f' · {r["note"]}' if r.get('note') else '') for r in due[:2]], link('today#reminders'),
                         actions=buttons(dict(first, sender_name=first['from'])), kind='reminder')
    if shown is False:
        return 0
    for r in due:
        r['notified'] = now.isoformat()
    # Keep notified items visible until the user dismisses them; never pop the same reminder again.
    save_json(config.REMINDERS_FILE, items)
    return len(due)
