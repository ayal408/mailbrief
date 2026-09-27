"""🔁 Recurring emails: "every 1st of the month — a payment reminder to X", "every Sunday — the report to Y". Set once;
each time it's due, a copy goes into the scheduled outbox (so never on Shabbat / Yom Tov — it waits for the end)."""
import datetime as dt
import secrets

from mailbrief import config
from mailbrief.features import outbox
from mailbrief.storage import load_json, save_json


DAYS = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת']
MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר']


def items():
    return load_json(config.RECURRING_FILE, [])


def add(account, to, subject, body, freq, day, at='09:00'):
    to_list = [a.strip() for a in to.replace(';', ',').split(',') if a.strip()]
    if not to_list or not all(outbox.EMAIL.fullmatch(a) for a in to_list):
        raise ValueError('כתובת הנמען לא נראית תקינה')
    if not subject.strip():
        raise ValueError('צריך נושא')
    if freq not in ('monthly', 'weekly'):
        raise ValueError('תדירות לא מוכרת')
    day = int(day)
    if not (1 <= day <= 28 if freq == 'monthly' else 0 <= day <= 5):      # never on Shabbat
        raise ValueError('יום לא תקין')
    hour, minute = (int(x) for x in (at or '09:00').split(':')[:2])
    item = {'id': secrets.token_hex(4), 'account': account, 'to': ', '.join(to_list), 'subject': subject.strip()[:300],
            'body': body[:20000], 'freq': freq, 'day': day, 'at': f'{hour:02d}:{minute:02d}', 'on': True, 'last': ''}
    save_json(config.RECURRING_FILE, items() + [item])
    return item


def set_item(item_id, action):
    rows = items()
    for r in rows:
        if r['id'] == item_id:
            r['on'] = action == 'on' if action in ('on', 'off') else r['on']
    save_json(config.RECURRING_FILE, [r for r in rows if not (r['id'] == item_id and action == 'delete')])


def when_text(r):
    return (f'כל {r["day"]} בחודש' if r['freq'] == 'monthly' else f'כל יום {DAYS[r["day"]]}') + f' ב-{r["at"]}'


def due_today(r, today):
    return today.day == r['day'] if r['freq'] == 'monthly' else (today.weekday() + 1) % 7 == r['day']


def fill(text, today):
    return (text.replace('{חודש}', MONTHS[today.month - 1]).replace('{month}', MONTHS[today.month - 1])
            .replace('{היום}', f'{today:%d/%m/%Y}').replace('{today}', f'{today:%d/%m/%Y}').replace('{שנה}', str(today.year)))


def run_recurring(now=None):
    """Queues today's copies (once a day each, from its hour on). Returns how many were queued."""
    now = now or dt.datetime.now().astimezone()
    today, rows, queued = now.date(), items(), 0
    for r in rows:
        if not r.get('on') or r.get('last') == today.isoformat() or not due_today(r, today):
            continue
        hour, minute = (int(x) for x in r['at'].split(':'))
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < when:
            continue
        outbox.schedule(r['account'], r['to'], fill(r['subject'], today), fill(r['body'], today), outbox.out_of_holy(now))
        r['last'] = today.isoformat()
        queued += 1
    if queued:
        save_json(config.RECURRING_FILE, rows)
    return queued
