"""Bookkeeping on top of the receipts ledger: a fixed category per supplier, the monthly input-VAT summary,
"this month's invoice from X hasn't arrived", and an export file for Hashavshevet (or any accounting software)."""
import csv
import datetime as dt
import io
import os
import statistics

from mailbrief import config
from mailbrief.money.ledger import ils, write_month_xlsx
from mailbrief.storage import load_json, save_json


VAT_RATE = 18            # Israel, since January 2025
BOOKS = ('רכב', 'תקשורת', 'תוכנה ומנויים', 'משרד', 'שכירות', 'חשמל ומים', 'ארנונה', 'ביטוח', 'בנק ועמלות',
         'פרסום', 'נסיעות', 'כיבוד', 'ציוד', 'שירותים מקצועיים', 'אחר')


# ---- a category per supplier ------------------------------------------------------------------------------------------

def vendor_cfg():
    """{vendor_key: {'book': category, 'no_vat': bool, 'account': supplier card in the accounting software}}"""
    return load_json(config.SETTINGS_FILE, {}).get('vendors') or {}


def book_for(r, cfg=None):
    cfg = vendor_cfg() if cfg is None else cfg
    return (cfg.get(r.get('vendor_key', '')) or {}).get('book') or r.get('book') or 'אחר'


def set_vendor(vkey, book=None, no_vat=None, account=None):
    """Saves the supplier's category and rewrites its rows (and the months' Excel files) so they match."""
    settings = load_json(config.SETTINGS_FILE, {})
    entry = settings.setdefault('vendors', {}).setdefault(vkey, {})
    for name, value in (('book', book), ('no_vat', no_vat), ('account', account)):
        if value is not None:
            entry[name] = value
    save_json(config.SETTINGS_FILE, settings)
    ledger = load_json(config.LEDGER_FILE, {})
    months = set()
    for r in ledger.values():
        if r.get('vendor_key') == vkey and book and r.get('book') != book:
            r['book'] = book
            months.add(r['date'][:7])
    if months:
        save_json(config.LEDGER_FILE, ledger)
        for month in months:
            try:
                write_month_xlsx(month, ledger)
            except OSError:
                pass
    return len(months)


def vendors(ledger=None):
    """Every supplier with its receipts count, total in ₪ and category, most used first."""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    cfg, out = vendor_cfg(), {}
    for r in ledger.values():
        v = out.setdefault(r['vendor_key'], {'key': r['vendor_key'], 'name': r['vendor'], 'count': 0, 'total': 0.0, 'last': ''})
        v['count'] += 1
        v['total'] += ils(r) or 0
        if r['date'] >= v['last']:
            v['last'], v['name'] = r['date'], r['vendor']
            v['book'] = book_for(r, cfg)
        v['no_vat'] = bool((cfg.get(r['vendor_key']) or {}).get('no_vat'))
        v['account'] = (cfg.get(r['vendor_key']) or {}).get('account', '')
    return sorted(out.values(), key=lambda v: (-v['count'], v['name']))


# ---- VAT ---------------------------------------------------------------------------------------------------------------

def vat_of(r, cfg=None):
    """Input VAT inside a ₪ receipt from an Israeli supplier (amount includes VAT). Foreign currency / exempt: 0."""
    cfg = vendor_cfg() if cfg is None else cfg
    if r.get('currency') != '₪' or r.get('amount') is None or (cfg.get(r.get('vendor_key', '')) or {}).get('no_vat'):
        return 0.0
    return round(r['amount'] * VAT_RATE / (100 + VAT_RATE), 2)


def vat_summary(month, ledger=None):
    """{'month', 'total', 'vat', 'net', 'count', 'books': {category: (total, vat)}, 'foreign': total ₪ without VAT}"""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    cfg = vendor_cfg()
    rows = [r for r in ledger.values() if r['date'].startswith(month) and not r.get('duplicate')]
    out = {'month': month, 'total': 0.0, 'vat': 0.0, 'count': 0, 'books': {}, 'foreign': 0.0}
    for r in rows:
        amount = ils(r)
        if amount is None:
            continue
        vat = vat_of(r, cfg)
        out['count'] += 1
        out['total'] += amount
        out['vat'] += vat
        if r.get('currency') != '₪':
            out['foreign'] += amount
        total, v = out['books'].get(book_for(r, cfg), (0.0, 0.0))
        out['books'][book_for(r, cfg)] = (round(total + amount, 2), round(v + vat, 2))
    out['total'], out['vat'] = round(out['total'], 2), round(out['vat'], 2)
    out['net'] = round(out['total'] - out['vat'], 2)
    return out


# ---- the invoice that usually arrives by now --------------------------------------------------------------------------

def _months_back(today, n):
    first, out = today.replace(day=1), []
    for _ in range(n):
        first = (first - dt.timedelta(days=1)).replace(day=1)
        out.append(first.strftime('%Y-%m'))
    return out


def missing_invoices(ledger=None, today=None, grace=3):
    """Suppliers that sent something in at least 3 of the last 4 months (including last month), usually by day D —
    and D + grace days have passed this month with nothing from them. [{'vendor', 'key', 'day', 'amount', 'last'}]"""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    today = today or dt.date.today()
    recent = _months_back(today, 4)
    this_month = today.strftime('%Y-%m')
    groups = {}
    for r in ledger.values():
        groups.setdefault(r['vendor_key'], []).append(r)
    out = []
    for key, rows in groups.items():
        by_month = {}
        for r in rows:
            by_month.setdefault(r['date'][:7], []).append(r)
        if this_month in by_month or recent[0] not in by_month or sum(m in by_month for m in recent) < 3:
            continue
        day = int(statistics.median(int(min(by_month[m], key=lambda r: r['date'])['date'][8:10]) for m in recent if m in by_month))
        if today.day < min(day + grace, 28):
            continue
        last = max(rows, key=lambda r: r['date'])
        out.append({'vendor': last['vendor'], 'key': key, 'day': day, 'amount': last.get('amount'),
                    'currency': last.get('currency', ''), 'last': last['date']})
    return sorted(out, key=lambda v: v['day'])


# ---- export for the accounting software -------------------------------------------------------------------------------

def export_cfg():
    cfg = load_json(config.SETTINGS_FILE, {}).get('export') or {}
    return {'vat_account': cfg.get('vat_account', ''), 'supplier_account': cfg.get('supplier_account', ''),
            'accounts': cfg.get('accounts') or {}}           # category -> expense account number


def export_month(month, ledger=None):
    """קבלות\\YYYY-MM\\ייבוא לחשבשבת YYYY-MM.csv — one line per receipt: date, reference, supplier, expense account,
    supplier account, VAT account, total, VAT, net. Windows-1255, the encoding Hashavshevet and Excel expect.
    Account numbers come from the settings (empty = to be filled in by the bookkeeper)."""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    cfg, exp = vendor_cfg(), export_cfg()
    rows = sorted((r for r in ledger.values() if r['date'].startswith(month) and not r.get('duplicate') and ils(r) is not None),
                  key=lambda r: r['date'])
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator='\r\n')
    out.writerow(['תאריך', 'אסמכתא', 'פרטים', 'ספק', 'סיווג', 'חשבון הוצאה', 'חשבון ספק', 'חשבון מע״מ',
                  'סכום כולל', 'מע״מ', 'סכום לפני מע״מ', 'מטבע מקור', 'סכום מקור'])
    for n, r in enumerate(rows, 1):
        book = book_for(r, cfg)
        total, vat = ils(r), vat_of(r, cfg)
        supplier = (cfg.get(r['vendor_key']) or {}).get('account') or exp['supplier_account']
        out.writerow([dt.date.fromisoformat(r['date']).strftime('%d/%m/%Y'), f'{month.replace("-", "")}{n:03d}',
                      r['subject'][:50], r['vendor'][:40], book, exp['accounts'].get(book, ''), supplier,
                      exp['vat_account'] if vat else '', f'{total:.2f}', f'{vat:.2f}', f'{total - vat:.2f}',
                      r.get('currency', ''), '' if r.get('amount') is None else f'{r["amount"]:.2f}'])
    folder = os.path.join(config.RECEIPTS_DIR, month)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'ייבוא לחשבשבת {month}.csv')
    with open(path, 'w', encoding='cp1255', errors='replace', newline='') as f:
        f.write(buf.getvalue())
    return path, len(rows)
