"""Looking after clients: polite payment reminders for open invoices, and personal greetings on a client's own dates
(birthday, business anniversary). Everything goes out through the scheduled outbox — so never on Shabbat / Yom Tov."""
import datetime as dt
import os
import re
import secrets

from mailbrief import config
from mailbrief.features.greetings import first_name
from mailbrief.features.outbox import EMAIL, out_of_holy, schedule
from mailbrief.profile import profile
from mailbrief.storage import load_json, save_json


DEBTS_FILE = 'debts.json'
DATES_FILE = 'client-dates.json'
MAX_REMINDERS = 3

REMINDER_DEFAULT = ('שלום {first_name},\n\nרציתי להזכיר בעדינות את חשבונית {invoice} על סך {amount} מתאריך {date}.\n'
                    'אם כבר שולם — תודה רבה, ואפשר להתעלם מההודעה.\n\nבברכה,\n{my_name}')
DATE_KINDS = {'birthday': ('🎂', 'יום הולדת', 'מזל טוב {first_name}! 🎉\n\nמאחלים לך יום הולדת שמח, בריאות והצלחה.\n\n{my_name}'),
              'anniversary': ('🤝', 'שנה לעבודה משותפת', 'שלום {first_name},\n\nהיום בדיוק עוד שנה שאנחנו עובדים יחד — תודה על האמון!\n\n{my_name}'),
              'other': ('⭐', 'יום מיוחד', 'שלום {first_name},\n\nרציתי לאחל לך יום נפלא.\n\n{my_name}')}


def _path(name):
    return os.path.join(config.DATA, name)


def _now():
    return dt.datetime.now().astimezone()


def _fill(text, **values):
    return re.sub(r'\{(\w+)\}', lambda m: str(values.get(m.group(1), m.group(0))), text)


# ---- open invoices ----------------------------------------------------------------------------------------------------

def debts():
    return load_json(_path(DEBTS_FILE), [])


def add_debt(account, email, name, amount, invoice, sent, due_days=30, every=7, text=''):
    if not EMAIL.fullmatch(email.strip()):
        raise ValueError('כתובת הלקוח לא נראית תקינה')
    sent_day = dt.date.fromisoformat(sent) if sent else dt.date.today()
    item = {'id': secrets.token_hex(4), 'account': account, 'email': email.strip(), 'name': name.strip() or email.split('@')[0],
            'amount': amount.strip(), 'invoice': invoice.strip(), 'sent': sent_day.isoformat(),
            'due': (sent_day + dt.timedelta(days=int(due_days))).isoformat(), 'every': max(3, int(every)),
            'text': text.strip() or REMINDER_DEFAULT, 'reminders': [], 'status': 'open'}
    save_json(_path(DEBTS_FILE), debts() + [item])
    return item


def set_debt(debt_id, status):
    rows = debts()
    for d in rows:
        if d['id'] == debt_id:
            d['status'] = status
            if status == 'paid':
                d['paid'] = dt.date.today().isoformat()
    save_json(_path(DEBTS_FILE), [d for d in rows if d['status'] != 'deleted'])


THANKS_DEFAULT = ('שלום {first_name},\n\nתודה רבה על התשלום של חשבונית {invoice}{amount_text} — התקבל. 🙏\n'
                  'מצורפת הקבלה.\n\nבברכה,\n{my_name}')


def send_thanks(debt_id, files=(), text=''):
    """After "paid": a thank-you with the receipt attached, from your mailbox in two minutes (after Shabbat if it falls in one)."""
    d = next((x for x in debts() if x['id'] == debt_id), None)
    if not d:
        raise ValueError('החשבונית לא נמצאה')
    body = _fill(text.strip() or THANKS_DEFAULT, first_name=first_name(d['name']) or d['name'], name=d['name'],
                 invoice=d['invoice'] or '', amount_text=f" על סך {d['amount']}" if d['amount'] else '', my_name=profile().get('name', ''))
    subject = f'קבלה — חשבונית {d["invoice"]}' if d['invoice'] else 'קבלה על התשלום — תודה!'
    return schedule(d['account'], d['email'], subject, body, out_of_holy(_now() + dt.timedelta(minutes=2)), files=files)


def next_reminder(d):
    """The day the next reminder is due, or None (paid / stopped / all reminders sent)."""
    if d['status'] != 'open' or len(d['reminders']) >= MAX_REMINDERS:
        return None
    start = dt.date.fromisoformat(d['due'])
    return start + dt.timedelta(days=d['every'] * len(d['reminders']))


def payment_text(cfg=None):
    """💳 How to pay, from the settings: a Bit / PayBox link and / or bank details. '' when nothing is set."""
    cfg = (load_json(config.SETTINGS_FILE, {}).get('payment') or {}) if cfg is None else cfg
    lines = []
    if cfg.get('bit'):
        lines.append(f'💳 תשלום ב-Bit: {cfg["bit"]}')
    if cfg.get('paybox'):
        lines.append(f'💳 תשלום ב-PayBox: {cfg["paybox"]}')
    if cfg.get('bank'):
        lines.append(f'🏦 העברה בנקאית: {cfg["bank"]}')
    return ('לנוחותך, אפשר לשלם כאן:\n' + '\n'.join(lines)) if lines else ''


def with_payment(body, text):
    """The payment lines where {פרטי_תשלום} is written — else before the sign-off (the last paragraph)."""
    if not text:
        return body.replace('{פרטי_תשלום}', '').replace('{payment}', '')
    if '{פרטי_תשלום}' in body or '{payment}' in body:
        return body.replace('{פרטי_תשלום}', text).replace('{payment}', text)
    head, sep, tail = body.rstrip().rpartition('\n\n')
    return f'{head}\n\n{text}\n\n{tail}' if sep else f'{body.rstrip()}\n\n{text}'


def chase_due(today=None):
    """Queues today's payment reminders in the outbox (10:00, or after Shabbat / Yom Tov). Returns how many."""
    today = today or dt.date.today()
    rows, queued, me = debts(), 0, profile().get('name', '')
    pay = payment_text()
    for d in rows:
        day = next_reminder(d)
        if not day or day > today:
            continue
        body = _fill(with_payment(d['text'], pay), first_name=first_name(d['name']), name=d['name'], invoice=d['invoice'] or '',
                     amount=d['amount'] or '', date=dt.date.fromisoformat(d['sent']).strftime('%d/%m/%Y'), my_name=me)
        when = out_of_holy(max(_now(), _now().replace(hour=10, minute=0, second=0, microsecond=0)))
        subject = f'תזכורת: חשבונית {d["invoice"]}'.strip() if d['invoice'] else 'תזכורת לגבי תשלום'
        schedule(d['account'], d['email'], subject, body, when)
        d['reminders'].append(today.isoformat())
        queued += 1
    if queued:
        save_json(_path(DEBTS_FILE), rows)
    return queued


INVOICE_HINT = re.compile(r'חשבונית|דרישת תשלום|invoice|payment request', re.I)


def suggestions(snapshot=None):
    """Sent mail that looks like an invoice and got no answer ("📤 waiting for them") — candidates for a reminder."""
    snapshot = load_json(config.SNAPSHOT_FILE, {}) if snapshot is None else snapshot
    known = {d['email'].lower() for d in debts() if d['status'] == 'open'}
    return [r for r in snapshot.get('awaiting', []) if INVOICE_HINT.search(r.get('subject', ''))
            and r.get('to_email', '').lower() not in known][:10]


# ---- a client's own dates ---------------------------------------------------------------------------------------------

def client_dates():
    return load_json(_path(DATES_FILE), [])


def add_date(account, email, name, day, kind='birthday', text='', hebrew=False):
    """hebrew: the date repeats by the Hebrew calendar (a different Gregorian day every year)."""
    if not EMAIL.fullmatch(email.strip()):
        raise ValueError('כתובת הלקוח לא נראית תקינה')
    month_day = dt.date.fromisoformat(day)
    item = {'id': secrets.token_hex(4), 'account': account, 'email': email.strip(), 'name': name.strip() or email.split('@')[0],
            'month': month_day.month, 'day': month_day.day, 'kind': kind if kind in DATE_KINDS else 'other',
            'text': text.strip(), 'sent_years': []}
    if hebrew:
        from mailbrief.features.hebdate import g2h
        h = g2h(month_day)
        if not h:
            raise ValueError('אין חיבור לאינטרנט להמרת התאריך העברי — אפשר לנסות שוב')
        item['hebrew'] = {'hm': h['hm'], 'hd': h['hd'], 'text': ' '.join(h['hebrew'].split()[:2])}
    save_json(_path(DATES_FILE), client_dates() + [item])
    return item


def remove_date(date_id):
    save_json(_path(DATES_FILE), [d for d in client_dates() if d['id'] != date_id])


def upcoming_dates(today=None, days=14):
    today = today or dt.date.today()
    out = []
    for d in client_dates():
        if d.get('hebrew'):
            from mailbrief.features.hebdate import next_occurrence
            when = next_occurrence(d['hebrew']['hm'], d['hebrew']['hd'], today)
            if when and 0 <= (when - today).days <= days:
                out.append({**d, 'date': when})
            continue
        for year in (today.year, today.year + 1):
            try:
                when = dt.date(year, d['month'], d['day'])
            except ValueError:                   # 29/02 in a regular year
                when = dt.date(year, 2, 28)
            if 0 <= (when - today).days <= days:
                out.append({**d, 'date': when})
                break
    return sorted(out, key=lambda d: d['date'])


def greet_due(today=None):
    """On the day itself (or the day before, for a date that falls on Shabbat) — queue the greeting for 09:00."""
    today = today or dt.date.today()
    rows, queued, me = client_dates(), 0, profile().get('name', '')
    for d in rows:
        hit = next((u for u in upcoming_dates(today, 1) if u['id'] == d['id']), None)
        if not hit or hit['date'].year in d['sent_years']:
            continue
        send_at = dt.datetime.combine(hit['date'], dt.time(9)).astimezone()
        if send_at <= _now():
            send_at = _now() + dt.timedelta(minutes=2)
        icon, title, default = DATE_KINDS[d['kind']]
        body = _fill(d['text'] or default, first_name=first_name(d['name']), name=d['name'], my_name=me)
        schedule(d['account'], d['email'], f'{icon} {title} שמח!' if d['kind'] == 'birthday' else f'{icon} {title}',
                 body, out_of_holy(send_at))
        d['sent_years'].append(hit['date'].year)
        queued += 1
    if queued:
        save_json(_path(DATES_FILE), rows)
    return queued
