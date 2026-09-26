"""↩️ Undo: the last action that changed something can be taken back for a few minutes — an inbox cleanup (the mail
goes back to the inbox), "paid" (the invoice is open again and the thank-you mail is cancelled), and deleting a rule,
template, text shortcut, client date or tracked invoice. One action at a time: the newest replaces the one before."""
import datetime as dt
import os
import secrets

from mailbrief import config
from mailbrief.storage import load_json, save_json


WINDOW = dt.timedelta(minutes=5)


def _path():
    return os.path.join(config.DATA, 'undo.json')


def record(kind, label, payload):
    """Remember how to take back what was just done. Returns its id."""
    item = {'id': secrets.token_hex(4), 'kind': kind, 'label': label, 'payload': payload,
            'at': dt.datetime.now().isoformat(timespec='seconds')}
    save_json(_path(), item)
    return item['id']


def last(now=None):
    """The action that can still be undone, or None."""
    item = load_json(_path(), None)
    if not item or item.get('done'):
        return None
    if (now or dt.datetime.now()) - dt.datetime.fromisoformat(item['at']) > WINDOW:
        return None
    return item


def seconds_left(item, now=None):
    return max(0, int((dt.datetime.fromisoformat(item['at']) + WINDOW - (now or dt.datetime.now())).total_seconds()))


def _restore_setting(key, row, match='id'):
    settings = load_json(config.SETTINGS_FILE, {})
    rows = settings.get(key)
    if key == 'templates' and rows is None:
        from mailbrief.features.replies import reply_templates
        rows = reply_templates()
    settings[key] = [r for r in rows or [] if r.get(match) != row.get(match)] + [row]
    save_json(config.SETTINGS_FILE, settings)


def _restore_list(path, row):
    rows = load_json(path, [])
    save_json(path, [r for r in rows if r.get('id') != row.get('id')] + [row])


def undo(item_id):
    """Takes the action back. Returns a message for the page."""
    item = last()
    if not item or item['id'] != item_id:
        raise RuntimeError('כבר אי אפשר לבטל את הפעולה הזו')
    kind, p = item['kind'], item['payload']
    if kind == 'clean_inbox':
        from mailbrief.features.cleanup import restore_cleaned
        back = restore_cleaned(p)
        text = f'↩️ {back} מיילים חזרו לדואר הנכנס'
    elif kind == 'debt_paid':
        from mailbrief.features import clientcare, outbox
        clientcare.set_debt(p['id'], 'open')
        if p.get('outbox'):
            outbox.cancel(p['outbox'])
        text = '↩️ החשבונית פתוחה שוב' + (' — ומייל התודה בוטל' if p.get('outbox') else '')
    elif kind == 'rule':
        _restore_list(config.RULES_FILE, p)
        text = '↩️ הכלל חזר'
    elif kind in ('template', 'snippet'):
        _restore_setting('templates' if kind == 'template' else 'snippets', p, 'id' if kind == 'template' else 'key')
        text = '↩️ חזר'
    elif kind in ('debt', 'date'):
        from mailbrief.features import clientcare
        _restore_list(clientcare._path(clientcare.DEBTS_FILE if kind == 'debt' else clientcare.DATES_FILE), p)
        text = '↩️ חזר'
    else:
        raise RuntimeError('פעולה לא מוכרת')
    item['done'] = True
    save_json(_path(), item)
    return text
