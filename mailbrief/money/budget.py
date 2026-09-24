"""Budgets per category, "who is cheaper" between suppliers of the same kind, and the year's tax-refund documents
(medical expenses, donations under section 46, life insurance / pension) gathered into one folder."""
import datetime as dt
import os
import re
import shutil

from mailbrief import config
from mailbrief.money.books import book_for, vendor_cfg
from mailbrief.money.excel import write_xlsx
from mailbrief.money.ledger import ils
from mailbrief.storage import load_json
from mailbrief.util import safe_name


# ---- budgets ----------------------------------------------------------------------------------------------------------

def budgets():
    """{category: monthly amount in ₪}"""
    return {k: float(v) for k, v in (load_json(config.SETTINGS_FILE, {}).get('budgets') or {}).items() if v}


def budget_status(month=None, ledger=None):
    """[{'book', 'budget', 'spent', 'pct', 'over'}] for every category that has a budget, the fullest first."""
    month = month or dt.date.today().strftime('%Y-%m')
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    cfg, spent = vendor_cfg(), {}
    for r in ledger.values():
        if r['date'].startswith(month) and not r.get('duplicate') and ils(r) is not None:
            spent[book_for(r, cfg)] = spent.get(book_for(r, cfg), 0) + ils(r)
    rows = [{'book': b, 'budget': amount, 'spent': round(spent.get(b, 0), 2), 'pct': round(100 * spent.get(b, 0) / amount),
             'over': spent.get(b, 0) > amount} for b, amount in budgets().items()]
    return sorted(rows, key=lambda r: -r['pct'])


# ---- who is cheaper ---------------------------------------------------------------------------------------------------

def compare_suppliers(months=6, ledger=None):
    """Categories with two suppliers or more in the last months: each supplier's average monthly cost in ₪.
    {category: [{'vendor', 'key', 'monthly', 'months'}]} — cheapest first."""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    since = (dt.date.today().replace(day=1) - dt.timedelta(days=31 * months)).isoformat()
    cfg, groups = vendor_cfg(), {}
    for r in ledger.values():
        if r['date'] < since or r.get('duplicate') or ils(r) is None:
            continue
        v = groups.setdefault(book_for(r, cfg), {}).setdefault(r['vendor_key'], {'vendor': r['vendor'], 'key': r['vendor_key'],
                                                                                'total': 0.0, 'months': set()})
        v['total'] += ils(r)
        v['months'].add(r['date'][:7])
    out = {}
    for book, vendors in groups.items():
        rows = [{'vendor': v['vendor'], 'key': v['key'], 'monthly': round(v['total'] / len(v['months']), 2), 'months': len(v['months'])}
                for v in vendors.values()]
        if len(rows) >= 2 and book != 'אחר':
            out[book] = sorted(rows, key=lambda r: r['monthly'])
    return out


# ---- tax refund documents ---------------------------------------------------------------------------------------------

TAX_KINDS = {
    'medical': ('🩺', 'הוצאות רפואיות', re.compile(r'קופת חולים|מכבי|כללית|מאוחדת|לאומית|רופא|מרפאה|בית חולים|רפואי|שיניים|אופטיקה|משקפיים|'
                                                  r'פיזיותרפיה|פסיכולוג|טיפול|בית מרקחת|סופר.?פארם|pharm|clinic|medical|dental|hospital', re.I)),
    'donation': ('💝', 'תרומות (סעיף 46)', re.compile(r'תרומה|תרומתך|עמותה|קבלה לפי סעיף 46|סעיף 46|donation|charity|donate', re.I)),
    'insurance': ('🛡️', 'ביטוח חיים ופנסיה', re.compile(r'ביטוח חיים|ביטוח מנהלים|פנסיה|קופת גמל|קרן השתלמות|אובדן כושר|life insurance|pension', re.I)),
}


def tax_kind(r):
    text = f"{r.get('vendor', '')} {r.get('subject', '')} {r.get('email', '')}"
    return next((k for k, (_, _, rx) in TAX_KINDS.items() if rx.search(text)), None)


def tax_documents(year, ledger=None):
    """{kind: [receipt rows]} for the tax year."""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    out = {}
    for r in ledger.values():
        if r['date'].startswith(str(year)) and not r.get('duplicate'):
            kind = tax_kind(r)
            if kind:
                out.setdefault(kind, []).append(r)
    return {k: sorted(v, key=lambda r: r['date']) for k, v in out.items()}


def collect_tax_documents(year):
    """קבלות\\מסמכים להחזר מס YYYY\\ — a folder per kind with copies of the files, and a summary Excel. Returns (folder, count)."""
    docs = tax_documents(year)
    root = os.path.join(config.RECEIPTS_DIR, f'מסמכים להחזר מס {year}')
    os.makedirs(root, exist_ok=True)
    rows, count = [], 0
    for kind, items in docs.items():
        icon, title, _ = TAX_KINDS[kind]
        folder = os.path.join(root, safe_name(title))
        os.makedirs(folder, exist_ok=True)
        for r in items:
            for rel in r.get('files', []):
                src = os.path.join(config.RECEIPTS_DIR, rel)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(folder, os.path.basename(rel)))
                    count += 1
            rows.append([title, r['date'], r['vendor'], r['subject'], ils(r) if ils(r) is not None else '', ', '.join(r.get('files', []))])
    totals = [[TAX_KINDS[k][1], '', 'סה״כ', '', round(sum(ils(r) or 0 for r in items), 2), ''] for k, items in docs.items()]
    write_xlsx(os.path.join(root, f'סיכום להחזר מס {year}.xlsx'), f'החזר מס {year}',
               ['סוג', 'תאריך', 'ספק', 'נושא', 'סכום בש״ח', 'קבצים'], rows + ([[]] if totals else []) + totals,
               [20, 12, 26, 40, 14, 50], bold_rows=range(len(rows) + 2, len(rows) + 2 + len(totals)))
    return root, count
