"""For the accountant: the monthly package (Excel + every receipt file, zipped, optionally emailed),
price increases in regular charges, and the yearly summary by vendor and category."""
import collections
import datetime as dt
import os
import zipfile
from email.message import EmailMessage

from mailbrief import config
from mailbrief.mail import smtp
from mailbrief.money.excel import write_xlsx
from mailbrief.money.ledger import find_subscriptions, ils, write_month_xlsx
from mailbrief.storage import load_json
from mailbrief.util import e, money


MAX_ATTACH = 20_000_000      # Gmail rejects mail above 25MB (after encoding) — above this, send the Excel alone


# ---- the monthly package ----------------------------------------------------------------------------------------------

def previous_month(today=None):
    first = (today or dt.date.today()).replace(day=1)
    return (first - dt.timedelta(days=1)).strftime('%Y-%m')


def month_package(month, ledger=None):
    """קבלות\\YYYY-MM\\חבילה לרו״ח YYYY-MM.zip — the month's Excel and all its receipt files. Returns (path, rows, total ₪)."""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    rows = sorted((r for r in ledger.values() if r['date'].startswith(month)), key=lambda r: r['date'])
    folder = os.path.join(config.RECEIPTS_DIR, month)
    os.makedirs(folder, exist_ok=True)
    write_month_xlsx(month, ledger)
    path = os.path.join(folder, f'חבילה לרו״ח {month}.zip')
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(folder, f'קבלות {month}.xlsx'), f'קבלות {month}.xlsx')
        added = set()
        for r in rows:
            for rel in r.get('files', []):
                src = os.path.join(config.RECEIPTS_DIR, rel)
                name = os.path.basename(rel)
                if os.path.isfile(src) and name not in added:
                    z.write(src, f'קבצים/{name}')
                    added.add(name)
    os.replace(tmp, path)
    total = round(sum(ils(r) for r in rows if ils(r) is not None), 2)
    return path, rows, total


def accountant_cfg():
    cfg = load_json(config.SETTINGS_FILE, {}).get('accountant') or {}
    return {'email': cfg.get('email', ''), 'day': int(cfg.get('day', 2)), 'on': bool(cfg.get('on')),
            'account': cfg.get('account', ''), 'name': cfg.get('name', '')}


def send_package(month, acc, to, name=''):
    path, rows, total = month_package(month)
    msg = EmailMessage()
    msg['From'], msg['To'] = acc['email'], to
    msg['Subject'] = f'קבלות וחשבוניות — {month[5:]}/{month[:4]}'
    msg['X-MailBrief-Forwarded'] = '1'
    greeting = f'שלום {name},' if name else 'שלום,'
    text = (f'{greeting}\n\nמצורפות הקבלות והחשבוניות של {month[5:]}/{month[:4]}: {len(rows)} מסמכים, סה״כ {money(total)} (בש״ח, לפי שער יציג).\n'
            'בקובץ האקסל — כל השורות עם תאריך, ספק, סכום, מטבע וסיווג מוצע; בתיקייה „קבצים” — המסמכים עצמם.\n\nתודה!')
    msg.set_content(text)
    msg.add_alternative(f'<div dir="rtl" style="font-family:Arial">{e(text).replace(chr(10), "<br>")}</div>', subtype='html')
    big = os.path.getsize(path) > MAX_ATTACH
    attach = os.path.join(config.RECEIPTS_DIR, month, f'קבלות {month}.xlsx') if big else path
    with open(attach, 'rb') as f:
        msg.add_attachment(f.read(), maintype='application',
                           subtype='zip' if attach.endswith('.zip') else 'vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                           filename=os.path.basename(attach))
    smtp.send_mail(acc, msg)
    return len(rows), total, big


def maybe_send_monthly(state, accounts, today=None):
    """From the chosen day of the month, once per month: last month's package to the accountant (never on Shabbat —
    this runs from the hourly check, which doesn't run then)."""
    cfg, today = accountant_cfg(), today or dt.date.today()
    month = previous_month(today)
    if not cfg['on'] or not cfg['email'] or not accounts or today.day < cfg['day'] or state.get('_accountant') == month:
        return None
    acc = next((a for a in accounts if a['email'].lower() == cfg['account'].lower()), accounts[0])
    result = send_package(month, acc, cfg['email'], cfg['name'])
    state['_accountant'] = month
    return result


# ---- price increases ---------------------------------------------------------------------------------------------------

def price_changes(ledger, min_rise=0.03, since_days=45):
    """A regular charge that went up: same vendor and currency, the latest charge vs the one before it."""
    groups = collections.defaultdict(list)
    for r in ledger.values():
        if r.get('amount') is not None:
            groups[(r['vendor_key'], r['currency'])].append(r)
    cutoff = (dt.date.today() - dt.timedelta(days=since_days)).isoformat()
    changes = []
    for (key, currency), rows in groups.items():
        rows.sort(key=lambda r: r['date'])
        months = {}
        for r in rows:                                 # one charge per month (the month's last)
            months[r['date'][:7]] = r
        seq = [months[m] for m in sorted(months)]
        if len(seq) < 2 or seq[-1]['date'] < cutoff:
            continue
        old, new = seq[-2], seq[-1]
        if old['amount'] and new['amount'] > old['amount'] * (1 + min_rise):
            changes.append({'vendor': new['vendor'], 'key': key, 'currency': currency, 'old': old['amount'],
                            'new': new['amount'], 'old_date': old['date'], 'date': new['date'],
                            'percent': round((new['amount'] / old['amount'] - 1) * 100)})
    return sorted(changes, key=lambda c: c['date'], reverse=True)


def price_change_text(c):
    return f'{c["vendor"]}: {c["currency"]}{c["old"]:g} ← {c["currency"]}{c["new"]:g} (+{c["percent"]}%)'


# ---- the yearly summary --------------------------------------------------------------------------------------------------

def yearly_report(year, ledger=None):
    """קבלות\\סיכום שנתי YYYY.xlsx — per category and vendor: documents and totals in ₪, for the annual tax report."""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    rows = [r for r in ledger.values() if r['date'].startswith(str(year))]
    by = collections.defaultdict(lambda: {'count': 0, 'ils': 0.0, 'missing': 0, 'vendor': '', 'book': ''})
    for r in rows:
        g = by[(r.get('book') or 'אחר', r['vendor_key'])]
        g['count'] += 1
        g['vendor'], g['book'] = r['vendor'], r.get('book') or 'אחר'
        value = ils(r)
        if value is None:
            g['missing'] += 1
        else:
            g['ils'] += value
    body, bold = [], []              # bold: row numbers in the sheet (the header is row 0)
    subscriptions = {s['key'] for s in find_subscriptions(ledger)}
    for book in sorted({b for b, _ in by}):
        items = sorted(((k, g) for (b, k), g in by.items() if b == book), key=lambda kv: -kv[1]['ils'])
        for key, g in items:
            body.append([book, g['vendor'], key, g['count'], round(g['ils'], 2),
                         '🔁 קבוע' if key in subscriptions else '', f'{g["missing"]} בלי סכום' if g['missing'] else ''])
        body.append(['', f'סה״כ {book}', '', sum(g['count'] for _, g in items), round(sum(g['ils'] for _, g in items), 2), '', ''])
        bold.append(len(body))
    body.append(['', 'סה״כ לשנה', '', len(rows), round(sum(g['ils'] for g in by.values()), 2), '', ''])
    bold.append(len(body))
    os.makedirs(config.RECEIPTS_DIR, exist_ok=True)
    path = os.path.join(config.RECEIPTS_DIR, f'סיכום שנתי {year}.xlsx')
    write_xlsx(path, f'סיכום {year}', ['סיווג', 'ספק', 'מזהה', 'מסמכים', 'סה״כ בש״ח', 'קבוע?', 'הערה'],
               body, [16, 28, 24, 10, 14, 10, 16], bold_rows=bold)
    return path, len(rows)
