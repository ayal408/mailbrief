"""🧾 The month for the accountant, as one page ready to save as PDF: totals, VAT, by category, and every receipt."""
import datetime as dt
import re

from mailbrief import config
from mailbrief.money.accountant import previous_month
from mailbrief.money.books import VAT_RATE, book_for, vat_of, vat_summary, vendor_cfg
from mailbrief.money.ledger import ils
from mailbrief.profile import profile
from mailbrief.storage import load_json
from mailbrief.util import e, money
from mailbrief.web.layout import page


PRINT = '''<style>@media print{nav.tabs,.hero,#mb-a11y-btn,#mb-a11y,#mb-pal,#mb-load,#mb-bar,#mb-offline,.no-print,footer.foot,.undo{display:none!important}
body{background:#fff!important;color:#000!important}main{box-shadow:none!important;border:0!important;margin:0!important;max-width:none!important;padding:0!important}
a{color:#000!important;text-decoration:none!important}table{box-shadow:none!important}tr{break-inside:avoid}
main .kpi{border:1px solid #bbb!important}*{animation:none!important;transition:none!important}
@page{size:A4;margin:14mm}}</style>'''


def month_report_page(month=''):
    month = month if re.fullmatch(r'\d{4}-\d{2}', month or '') else previous_month()
    ledger = load_json(config.LEDGER_FILE, {})
    cfg = vendor_cfg()
    s = vat_summary(month, ledger)
    rows = sorted((r for r in ledger.values() if r['date'].startswith(month) and not r.get('duplicate')), key=lambda r: r['date'])
    me = profile()
    year, mon = int(month[:4]), int(month[5:])
    months = sorted({r['date'][:7] for r in ledger.values()} | {previous_month()}, reverse=True)[:18]
    picker = ''.join(f'<option value="{m}"{" selected" if m == month else ""}>{m[5:]}/{m[:4]}</option>' for m in months)
    books = ''.join(f'<tr><td>{e(b)}</td><td>{money(t)}</td><td>{money(v)}</td><td>{money(round(t - v, 2))}</td></tr>'
                    for b, (t, v) in sorted(s['books'].items(), key=lambda kv: -kv[1][0]))
    lines = ''.join(
        f'<tr><td style="white-space:nowrap">{r["date"][8:10]}/{r["date"][5:7]}</td><td dir="auto">{e(r.get("vendor", ""))}</td>'
        f'<td dir="auto">{e((r.get("subject") or "")[:60])}</td><td>{e(book_for(r, cfg))}</td>'
        f'<td dir="ltr" style="text-align:right;white-space:nowrap">{e(r.get("currency", ""))}{r["amount"] if r.get("amount") is not None else "—"}</td>'
        f'<td style="white-space:nowrap">{money(ils(r)) if ils(r) is not None else "—"}</td>'
        f'<td style="white-space:nowrap">{money(vat_of(r, cfg)) if ils(r) is not None else ""}</td>'
        f'<td>{"📎" if r.get("files") else ""}</td></tr>' for r in rows)
    who = ' · '.join(x for x in (me.get('business', ''), me.get('name', '')) if x)
    return page('דוח חודשי לרו״ח', f'''{PRINT}
<div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px">
<a href="/?s=money#accountant">→ חזרה לכסף</a>
<form method="get" action="/month_report" style="margin:0;display:flex;gap:6px;align-items:center">
<select name="month" onchange="this.form.submit()" style="font:inherit;padding:6px 10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">{picker}</select></form>
<button type="button" onclick="window.print()" style="margin:0;padding:8px 18px">🖨️ שמירה כ-PDF / הדפסה</button>
<span class="muted" style="font-size:13px">בחלון ההדפסה בוחרים „Microsoft Print to PDF” או „שמירה כ-PDF”.</span></div>
<h1 style="margin:0">🧾 דוח הוצאות — {mon:02d}/{year}</h1>
<p class="muted" style="margin:4px 0 0">{e(who) + ' · ' if who else ''}הופק ב-{dt.date.today():%d/%m/%Y} · MailBrief · לפי הקבלות שהגיעו במייל</p>
<div class="kpis"><div class="kpi"><b>{money(s["total"])}</b><span>סה״כ הוצאות</span></div>
<div class="kpi"><b>{money(s["vat"])}</b><span>מע״מ תשומות (משוער)</span></div>
<div class="kpi"><b>{money(s["net"])}</b><span>לפני מע״מ</span></div>
<div class="kpi"><b>{s["count"]}</b><span>קבלות</span></div></div>
{f'<p class="muted" style="font-size:13px">מתוכן {money(s["foreign"])} במטבע זר (בלי מע״מ ישראלי), מומר לפי השער היציג.</p>' if s["foreign"] else ''}
<h3>לפי סיווג</h3>
{f'<div class="scroll"><table><thead><tr><th>סיווג</th><th>סה״כ</th><th>מע״מ</th><th>לפני מע״מ</th></tr></thead><tbody>{books}</tbody></table></div>' if books else '<p class="muted">אין</p>'}
<h3>כל הקבלות</h3>
{f'<div class="scroll"><table><thead><tr><th>תאריך</th><th>ספק</th><th>נושא</th><th>סיווג</th><th>סכום</th><th>בש״ח</th><th>מע״מ</th><th></th></tr></thead><tbody>{lines}</tbody></table></div>' if lines else '<p class="muted">לא נמצאו קבלות בחודש הזה.</p>'}
<p class="muted" style="font-size:12px;margin-top:18px">המע״מ מחושב לפי {VAT_RATE:g}% מהסכום הכולל, חוץ מספקים שסומנו „בלי מע״מ” ומטבע זר. הקבצים עצמם — בחבילה לרו״ח (ZIP).</p>''', '/')
