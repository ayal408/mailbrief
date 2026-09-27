"""📊 The whole year on one page, ready to save as PDF for the annual report: income, expenses and VAT month by month,
the biggest suppliers, and who paid the most."""
import datetime as dt
import re

from mailbrief import config
from mailbrief.features import income
from mailbrief.money.books import VAT_RATE, vat_summary
from mailbrief.money.ledger import ils
from mailbrief.profile import profile
from mailbrief.storage import load_json
from mailbrief.util import e, money
from mailbrief.web.layout import page
from mailbrief.web.month_report import PRINT


MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר']


def year_data(year):
    ledger = load_json(config.LEDGER_FILE, {})
    months = []
    for n in range(1, 13):
        key = f'{year}-{n:02d}'
        s = vat_summary(key, ledger)
        got, _ = income.month_total(key)
        months.append({'month': key, 'name': MONTHS[n - 1], 'income': got, 'spent': s['total'], 'vat': s['vat'], 'count': s['count']})
    vendors, payers = {}, {}
    for r in ledger.values():
        if r['date'].startswith(str(year)) and not r.get('duplicate') and ils(r) is not None:
            vendors[r.get('vendor', '')] = vendors.get(r.get('vendor', ''), 0) + ils(r)
    for r in income.income().values():
        if r['date'].startswith(str(year)):
            value = r['amount'] if r['currency'] == '₪' else r.get('amount_ils')
            if value is not None:
                who = r.get('payer') or r['service']
                payers[who] = payers.get(who, 0) + value
    top = lambda d: sorted(d.items(), key=lambda kv: -kv[1])[:10]
    return months, top(vendors), top(payers)


def year_report_page(year=''):
    year = int(year) if re.fullmatch(r'20\d\d', year or '') else dt.date.today().year
    months, vendors, payers = year_data(year)
    total_in, total_out = sum(m['income'] for m in months), sum(m['spent'] for m in months)
    total_vat = sum(m['vat'] for m in months)
    rows = ''.join(
        f'<tr><td>{m["name"]}</td><td style="color:var(--good)">{money(m["income"]) if m["income"] else "—"}</td>'
        f'<td>{money(m["spent"]) if m["spent"] else "—"}</td><td>{money(m["vat"]) if m["vat"] else "—"}</td>'
        f'<td style="color:{"var(--good)" if m["income"] >= m["spent"] else "var(--bad)"}">{money(m["income"] - m["spent"]) if m["income"] or m["spent"] else "—"}</td>'
        f'<td>{m["count"] or ""}</td></tr>' for m in months)
    peak = max((m['spent'] for m in months), default=0) or 1
    bars = ''.join(f'<div style="display:flex;gap:8px;align-items:center;font-size:13px"><span style="width:56px">{m["name"][:3]}</span>'
                   f'<div class="bar" style="width:{max(2, round(100 * m["spent"] / peak))}%;max-width:70%"></div>'
                   f'<span class="muted">{money(m["spent"]) if m["spent"] else ""}</span></div>' for m in months)
    top_rows = lambda items: ''.join(f'<tr><td dir="auto">{e(k)}</td><td>{money(v)}</td></tr>' for k, v in items)
    years = sorted({int(r['date'][:4]) for r in load_json(config.LEDGER_FILE, {}).values() if r.get('date', '')[:4].isdigit()}
                   | {dt.date.today().year}, reverse=True)
    picker = ''.join(f'<option{" selected" if y == year else ""}>{y}</option>' for y in years)
    me = profile()
    who = ' · '.join(x for x in (me.get('business', ''), me.get('name', '')) if x)
    return page('סיכום שנתי', f'''{PRINT}
<div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
<a href="/?s=money">→ חזרה לכסף</a>
<form method="get" action="/year_report" style="margin:0"><select name="year" onchange="this.form.submit()" style="font:inherit;padding:6px 10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">{picker}</select></form>
<button type="button" onclick="window.print()" style="margin:0;padding:8px 18px">🖨️ שמירה כ-PDF / הדפסה</button>
<a href="/month_report" style="margin-inline-start:6px">🧾 דוח חודשי</a></div>
<h1 style="margin:0">📊 סיכום שנת {year}</h1>
<p class="muted" style="margin:4px 0 0">{e(who) + ' · ' if who else ''}הופק ב-{dt.date.today():%d/%m/%Y} · MailBrief · לפי הקבלות והודעות התשלום שהגיעו במייל</p>
<div class="kpis"><div class="kpi"><b style="color:var(--good)">{money(total_in)}</b><span>הכנסות שזוהו</span></div>
<div class="kpi"><b>{money(total_out)}</b><span>הוצאות</span></div>
<div class="kpi"><b>{money(total_vat)}</b><span>מע״מ תשומות (משוער)</span></div>
<div class="kpi"><b style="color:{'var(--good)' if total_in >= total_out else 'var(--bad)'}">{money(total_in - total_out)}</b><span>נשאר</span></div></div>
<h3>חודש אחר חודש</h3>
<div class="scroll"><table><thead><tr><th>חודש</th><th>הכנסות</th><th>הוצאות</th><th>מע״מ</th><th>נשאר</th><th>קבלות</th></tr></thead><tbody>{rows}</tbody></table></div>
<h3>הוצאות לפי חודש</h3><div style="display:grid;gap:4px">{bars}</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-top:10px">
<div><h3>🏷️ הספקים הגדולים</h3>{f'<table><tbody>{top_rows(vendors)}</tbody></table>' if vendors else '<p class="muted">אין</p>'}</div>
<div><h3>💚 מי שילם הכי הרבה</h3>{f'<table><tbody>{top_rows(payers)}</tbody></table>' if payers else '<p class="muted">עוד לא זוהו תשלומים</p>'}</div></div>
<p class="muted" style="font-size:12px;margin-top:18px">הכנסות — רק מה שזוהה מהודעות Bit, PayBox, PayPal והבנקים. המע״מ לפי {VAT_RATE:g}% מהסכום הכולל,
חוץ מספקים שסומנו „בלי מע״מ” ומטבע זר. זה סיכום עזר — הדוח השנתי עצמו נעשה עם רואה החשבון.</p>''', '/')
