"""📝 Quotes (price offers) you sent: follow them, get a reminder when a client hasn't answered in a week,
and see how many you win. Marked by hand (won / lost), or suggested from sent mail that looks like a quote."""
import datetime as dt
import os
import re
import secrets

from mailbrief import config
from mailbrief.features.reminders import add_reminder
from mailbrief.storage import load_json, save_json


FOLLOW_UP_DAYS = 7
QUOTE_HINT = re.compile(r'הצעת מחיר|הצעה ל|quote|quotation|proposal|price offer|estimate', re.I)


def _path():
    return os.path.join(config.DATA, 'quotes.json')


def quotes():
    return load_json(_path(), [])


def add_quote(account, email, name, subject, amount='', sent=''):
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email.strip()):
        raise ValueError('כתובת הלקוח לא נראית תקינה')
    item = {'id': secrets.token_hex(4), 'account': account, 'email': email.strip(), 'name': name.strip() or email.split('@')[0],
            'subject': subject.strip()[:200], 'amount': amount.strip()[:40], 'sent': sent or dt.date.today().isoformat(),
            'status': 'open', 'reminded': False}
    save_json(_path(), quotes() + [item])
    return item


def set_quote(quote_id, status):
    rows = quotes()
    for q in rows:
        if q['id'] == quote_id:
            q['status'] = status
            q['closed'] = dt.date.today().isoformat()
    save_json(_path(), [q for q in rows if q['status'] != 'deleted'])


def follow_up(today=None):
    """A week without an answer -> one reminder to call / write. Returns how many were created."""
    today = today or dt.date.today()
    rows, made = quotes(), 0
    for q in rows:
        if q['status'] == 'open' and not q['reminded'] and (today - dt.date.fromisoformat(q['sent'])).days >= FOLLOW_UP_DAYS:
            add_reminder(0, f'📝 הצעת המחיר ל{q["name"]} — שבוע בלי תשובה. כדאי לבדוק איתם', q['name'], '', q['account'],
                         note=q['subject'])
            q['reminded'] = True
            made += 1
    if made:
        save_json(_path(), rows)
    return made


def win_rate(days=90, today=None):
    """{'won', 'lost', 'open', 'rate'} for quotes sent in the last `days` days."""
    since = ((today or dt.date.today()) - dt.timedelta(days=days)).isoformat()
    recent = [q for q in quotes() if q['sent'] >= since]
    won, lost = sum(q['status'] == 'won' for q in recent), sum(q['status'] == 'lost' for q in recent)
    return {'won': won, 'lost': lost, 'open': sum(q['status'] == 'open' for q in recent),
            'rate': round(100 * won / (won + lost)) if won + lost else None}


def suggestions(snapshot=None):
    """Sent mail that looks like a quote and got no answer yet."""
    snapshot = load_json(config.SNAPSHOT_FILE, {}) if snapshot is None else snapshot
    known = {(q['email'].lower(), q['subject'].lower()) for q in quotes()}
    return [r for r in snapshot.get('awaiting', []) if QUOTE_HINT.search(r.get('subject', ''))
            and (r.get('to_email', '').lower(), r.get('subject', '').lower()) not in known][:8]
