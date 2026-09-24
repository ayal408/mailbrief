"""The receipts ledger: amounts, Bank of Israel rates, double charges, subscriptions, saved PDFs, monthly Excel."""
import datetime as dt
import os
import re
import urllib.request

from mailbrief import config
from mailbrief.mail.classify import RX
from mailbrief.mail.domains import FREE_MAIL
from mailbrief.mail.message import decode
from mailbrief.money.excel import write_xlsx
from mailbrief.money.pdftext import total_from_pdf
from mailbrief.net import _PUBLIC_TLS
from mailbrief.storage import load_json, save_json
from mailbrief.util import safe_name, write_once


def save_attachments(msg, it):
    """Keep the receipt's PDF (or image) under קבלות\\YYYY-MM\\; no attachment -> keep the email itself (.eml)."""
    month = it['iso'][:7]
    folder = os.path.join(config.RECEIPTS_DIR, month)
    prefix = f"{it['iso'][:10]} {safe_name(it['sender_name'])[:40]}"
    saved = []
    for part in msg.iter_attachments():
        name = decode(part.get_filename()) or ''
        ctype = part.get_content_type()
        is_pdf = ctype == 'application/pdf' or name.lower().endswith('.pdf')
        data = part.get_payload(decode=True) or b''
        if not (is_pdf or (ctype.startswith('image/') and len(data) > 30_000)) or not data or len(data) > 25_000_000:
            continue
        saved.append(write_once(folder, f'{prefix} - {safe_name(name or "receipt.pdf")}', data))
    if not saved:
        saved.append(write_once(folder, f'{prefix} - {safe_name(it["subject"])[:60]}.eml', msg.as_bytes()))
    return [os.path.relpath(p, config.RECEIPTS_DIR) for p in saved]


RECURRING_HINT = re.compile(RX['subscription'].pattern + r'|[A-Z][a-z]{2} \d{1,2}\s?[–-]\s?[A-Z][a-z]{2} \d{1,2}', re.I)


def vendor_key(address):
    """Group by company domain; people on free mail services are grouped by their own address."""
    if address.rsplit('@', 1)[-1].lower() in FREE_MAIL:
        return address.lower()
    parts = address.rsplit('@', 1)[-1].lower().split('.')
    keep = 3 if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in ('co', 'org', 'ac', 'gov', 'net', 'com') else 2
    return '.'.join(parts[-keep:])


def parse_amount(text):
    found = re.match(r'([₪$€])([\d,]+(?:\.\d+)?)', text or '')
    return (float(found.group(2).replace(',', '')), found.group(1)) if found else (None, '')


def item_key(account, it):
    return it.get('message_id') or f"{account}|{it['subject']}|{it['iso']}"


def update_ledger(results):
    ledger = load_json(config.LEDGER_FILE, {})
    chosen = load_json(config.SETTINGS_FILE, {}).get('vendors') or {}      # the category picked for a supplier wins
    months = set()
    for res in results:
        for it in res['items']:
            if 'receipts' not in it['cats']:
                continue
            amount, currency = parse_amount(it.get('amount'))
            ledger[item_key(res['email'], it)] = {
                'date': it['iso'][:10], 'vendor': it['sender_name'], 'email': it['sender'],
                'vendor_key': vendor_key(it['sender']), 'subject': it['subject'], 'amount': amount,
                'currency': currency, 'book': (chosen.get(vendor_key(it['sender'])) or {}).get('book') or it.get('book', 'אחר'),
                'account': res['email'],
                'files': it.get('files', []), 'link': it.get('link', ''), 'rules': it.get('rules', []),
                'recurring': bool(RECURRING_HINT.search(f"{it['subject']} {it['snippet']}")), 'due': it.get('due', '')}
            months.add(it['iso'][:7])
    for key, r in ledger.items():
        if r['amount'] is None and not r.get('pdf_checked'):      # the total may be only inside the saved PDF
            r['pdf_checked'] = True
            for rel in r.get('files', []):
                path = os.path.join(config.RECEIPTS_DIR, rel)
                if rel.lower().endswith('.pdf') and os.path.isfile(path):
                    with open(path, 'rb') as f:
                        r['amount'], r['currency'] = parse_amount(total_from_pdf(f.read()))
                    if r['amount'] is not None:
                        r['amount_from'] = 'pdf'
                        months.add(r['date'][:7])
                        break
        if r['currency'] in BOI_CODES and r['amount'] is not None and r.get('amount_ils') is None:
            rate = boi_rate(r['currency'], r['date'])
            if rate:
                r['rate'], r['amount_ils'] = rate, round(r['amount'] * rate, 2)
                months.add(r['date'][:7])
        elif r['currency'] == '₪':
            r['amount_ils'] = r['amount']
        dup = find_duplicate(ledger, key, r['vendor_key'], r['amount'], r['date'], r['subject'])
        if dup != r.get('duplicate', ''):
            r['duplicate'] = dup
            months.add(r['date'][:7])
    save_json(config.LEDGER_FILE, ledger)
    for month in months:
        try:
            write_month_xlsx(month, ledger)
        except OSError:                          # the file is open in Excel right now — next run will refresh it
            pass
    return ledger


BOI_CODES = {'$': 'USD', '€': 'EUR'}


def boi_rate(currency, day):
    """Bank of Israel representative rate for the date (the last published one on or before it). Cached forever."""
    code = BOI_CODES.get(currency)
    if not code:
        return None
    key = f'{code}|{day}'
    known = load_json(config.CACHE_FILE, {}).get('rates', {})
    if key in known:
        return known[key]
    start = (dt.date.fromisoformat(day) - dt.timedelta(days=10)).isoformat()
    url = (f'https://edge.boi.org.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0/RER_{code}_ILS'
           f'?startperiod={start}&endperiod={day}&format=csv')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MailBrief/1.0'})
        with urllib.request.urlopen(req, timeout=15, context=_PUBLIC_TLS) as resp:
            lines = resp.read().decode('utf-8', 'replace').splitlines()
        head = lines[0].split(',')
        t, v = head.index('TIME_PERIOD'), head.index('OBS_VALUE')
        values = sorted((r[t], float(r[v])) for r in (l.split(',') for l in lines[1:]) if len(r) > v and r[v])
    except Exception:
        return None
    if not values:
        return None
    cache = load_json(config.CACHE_FILE, {})
    cache.setdefault('rates', {})[key] = values[-1][1]
    save_json(config.CACHE_FILE, cache)
    return values[-1][1]


def doc_kind(subject):
    s = subject.lower()
    return 'invoice' if re.search(r'invoice|חשבונית', s) else 'receipt' if re.search(r'receipt|קבלה', s) else 'other'


def find_duplicate(ledger, key, vkey, amount, day, subject):
    """Same supplier + same amount + same document type within 5 days = a possible double charge."""
    if amount is None:
        return ''
    d0, kind = dt.date.fromisoformat(day), doc_kind(subject)
    for k, r in ledger.items():
        if (k != key and r['vendor_key'] == vkey and r['amount'] == amount and doc_kind(r['subject']) == kind
                and abs((dt.date.fromisoformat(r['date']) - d0).days) <= 5):
            return r['date']
    return ''


def ils(r):
    return r['amount'] if r['currency'] == '₪' else r.get('amount_ils')


def find_subscriptions(ledger):
    groups = {}
    for r in ledger.values():
        groups.setdefault(r['vendor_key'], []).append(r)
    today, subs = dt.date.today(), []
    for key, rows in groups.items():
        rows.sort(key=lambda r: r['date'])
        months = {r['date'][:7] for r in rows}
        if len(months) < 2 and not any(r.get('recurring') for r in rows):
            continue
        last = rows[-1]
        subs.append({'vendor': last['vendor'], 'key': key, 'amount': last['amount'], 'currency': last['currency'],
                     'last': last['date'], 'months': len(months), 'book': last['book'],
                     'new': (today - dt.date.fromisoformat(rows[0]['date'])).days <= 35})
    return sorted(subs, key=lambda s: s['last'], reverse=True)


def write_month_xlsx(month, ledger):
    rows = sorted((r for r in ledger.values() if r['date'].startswith(month)), key=lambda r: r['date'])
    body = [[r['date'], r['vendor'], r['email'], r['subject'], r['amount'] if r['amount'] is not None else '',
             r['currency'], r.get('rate', ''), r.get('amount_ils') if r.get('amount_ils') is not None else '',
             r['book'], ', '.join(r.get('rules', [])), r['account'], ', '.join(r.get('files', [])),
             f'⚠️ ייתכן חיוב כפול (גם ב-{r["duplicate"]})' if r.get('duplicate') else '']
            for r in rows]
    n = len(body) + 1
    totals = [['', f'סה״כ {c}', '', '', f'=SUMIF(F2:F{n},"{c}",E2:E{n})', c]
              for c in sorted({r['currency'] for r in rows if r['currency']})]
    if any(r['currency'] in BOI_CODES for r in rows):
        totals.append(['', 'סה״כ בש״ח (לפי שער יציג)', '', '', '', '', '', f'=SUM(H2:H{n})'])
    folder = os.path.join(config.RECEIPTS_DIR, month)
    os.makedirs(folder, exist_ok=True)
    write_xlsx(os.path.join(folder, f'קבלות {month}.xlsx'), f'קבלות {month}',
               ['תאריך', 'ספק', 'מייל הספק', 'נושא', 'סכום', 'מטבע', 'שער יציג', 'סכום בש״ח', 'סיווג מוצע',
                'לקוח / תווית', 'תיבה', 'קובץ', 'הערה'],
               body + ([[]] if totals else []) + totals, [12, 22, 28, 40, 12, 7, 10, 12, 16, 16, 26, 50, 30],
               bold_rows=range(n + 1, n + 1 + len(totals)), plain_cols={6})
