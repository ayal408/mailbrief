"""💚 Income: payment notices from Bit, PayBox, PayPal and the banks ("X transferred you ₪350") become a list of what came in —
next to the expenses, and an open invoice of the same client and amount is marked as paid by itself (can be undone)."""
import datetime as dt
import re

from mailbrief import config
from mailbrief.mail.message import body_text
from mailbrief.storage import load_json, save_json


SERVICES = [                         # (name, sender domains / words in the sender)
    ('Bit', ('bit.co.il', 'bitpay', 'bit-app', 'ביט')),
    ('PayBox', ('payboxapp', 'paybox', 'פייבוקס')),
    ('PayPal', ('paypal.com', 'paypal.co.il')),
    ('העברה בנקאית', ('bankhapoalim', 'poalim', 'leumi', 'discountbank', 'mizrahi-tefahot', 'tefahot', 'mercantile', 'fibi',
                      'bankjerusalem', 'bank-yahav', 'yahav', 'onezerobank', 'pepper', 'otsar-hahayal', 'massad', 'unionbank')),
]
IN = re.compile(r'קיבלת|העביר(?:ה|ו)? לך|העבירה אלייך|שלח(?:ה)? לך|הועבר(?:ו)? (?:אליך|לחשבונך)|זיכוי (?:ב|ל)חשבון|העברה נכנסת|'
                r'התקבל(?:ה)? (?:תשלום|העברה)|you(?:\'ve| have)? received|sent you|payment received|money received', re.I)
OUT = re.compile(r'שילמת|העברת ל|ביצעת|חיוב|חויב|you sent|you paid|payment to|you\'ve sent|בקשת תשלום|ביקש(?:ה)? ממך', re.I)
AMOUNT = [re.compile(r'(₪|ש"ח|ש״ח|NIS|ILS|\$|USD|€|EUR)\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)', re.I),
          re.compile(r'(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s?(₪|ש"ח|ש״ח|שקלים|שקל|NIS|ILS|\$|USD|€|EUR)', re.I)]
CURRENCY = {'$': '$', 'usd': '$', '€': '€', 'eur': '€'}
PAYER = [re.compile(r'([֐-׿A-Za-z][֐-׿A-Za-z\'"׳-]*(?: [֐-׿A-Za-z\'"׳-]+){0,2}) (?:העביר|שלח)(?:ה|ו)? לך'),
         re.compile(r'(?:מאת|מ-|השולח(?:/ת)?|שם המעביר|from)\s*:?\s*([֐-׿A-Za-z][^\n,.:|<>]{1,38})', re.I),
         re.compile(r'([A-Z][\w\'-]+(?: [A-Z][\w\'-]+){0,2}) sent you', re.I)]


def service_of(sender, text=''):
    s = (sender or '').lower()
    return next((name for name, marks in SERVICES if any(m in s for m in marks)), '')


def parse(sender, subject, text):
    """{'service', 'amount', 'currency', 'payer'} for an incoming-payment notice, else None."""
    service = service_of(sender)
    head = f'{subject}\n{text[:2500]}'
    if not service or not IN.search(head) or OUT.search(subject or ''):
        return None
    amount = currency = None
    for pattern in AMOUNT:
        m = pattern.search(head)
        if m:
            sym, num = (m[1], m[2]) if pattern is AMOUNT[0] else (m[2], m[1])
            amount, currency = float(num.replace(',', '')), CURRENCY.get(sym.lower(), '₪')
            break
    if not amount:
        return None
    payer = ''
    for pattern in PAYER:
        m = pattern.search(head)
        if m:
            payer = re.sub(r'\s+', ' ', m[1]).strip(' -:')[:40]
            if payer.lower() not in ('you', 'אתה', 'את'):
                break
            payer = ''
    return {'service': service, 'amount': amount, 'currency': currency, 'payer': payer}


def income():
    return load_json(config.INCOME_FILE, {})


def learn(pairs, account):
    """From the latest check: new payment notices -> income; a matching open invoice -> paid. Returns the new rows."""
    rows, new = income(), []
    for it, msg in pairs:
        key = (msg.get('Message-ID') or '').strip() or f"{it.get('sender')}|{it.get('iso')}|{it.get('subject')}"
        if key in rows:
            continue
        found = parse(it.get('sender', ''), it.get('subject', ''), body_text(msg) or '')
        if not found:
            continue
        row = dict(found, date=(it.get('iso') or dt.date.today().isoformat())[:10], subject=(it.get('subject') or '')[:200],
                   account=account, link=it.get('link', ''))
        if row['currency'] != '₪':                       # by the Bank of Israel rate of that day
            try:
                from mailbrief.money.ledger import boi_rate
                rate = boi_rate(row['currency'], row['date'])
                row['amount_ils'] = round(row['amount'] * rate, 2) if rate else None
            except Exception:
                row['amount_ils'] = None
        rows[key] = row
        new.append(row)
        try:
            row['debt'] = settle(row)
        except Exception:
            pass
    if new:
        save_json(config.INCOME_FILE, rows)
    return new


def _number(text):
    m = re.search(r'\d[\d,]*(?:\.\d+)?', str(text or ''))
    return float(m[0].replace(',', '')) if m else None


def _same_person(payer, name):
    words = lambda s: {w for w in re.split(r'[\s\-_.״"\']+', (s or '').lower()) if len(w) > 1}
    return bool(words(payer) & words(name))


def settle(row):
    """An open invoice with the same amount whose client name matches the payer: marked as paid (with undo). Returns its id."""
    from mailbrief.features import clientcare, undo
    if not row.get('payer') or row.get('currency') != '₪':
        return ''
    match = [d for d in clientcare.debts() if d['status'] == 'open' and _number(d.get('amount')) == row['amount']
             and (_same_person(row['payer'], d['name']) or _same_person(row['payer'], d['email'].split('@')[0]))]
    if len(match) != 1:
        return ''
    d = match[0]
    clientcare.set_debt(d['id'], 'paid')
    undo.record('debt_paid', f'{d["name"]} סומן כשולם ({row["service"]} ₪{row["amount"]:g})', {'id': d['id'], 'outbox': ''})
    return d['id']


def remove(key):
    rows = income()
    rows.pop(key, None)
    save_json(config.INCOME_FILE, rows)


def month_rows(month):
    return sorted(((k, r) for k, r in income().items() if r['date'].startswith(month)), key=lambda kv: kv[1]['date'], reverse=True)


def month_total(month):
    """(₪ total, by service {name: ₪}) — foreign currency by the day's official rate when known."""
    total, by = 0.0, {}
    for _, r in month_rows(month):
        value = r['amount'] if r['currency'] == '₪' else r.get('amount_ils')
        if value is None:
            continue
        total += value
        by[r['service']] = round(by.get(r['service'], 0) + value, 2)
    return round(total, 2), by
