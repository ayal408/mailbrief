"""Client cards and the clients dashboard: reply rate, last contact, who waits, who owes."""
import datetime as dt
from urllib.parse import quote

from mailbrief.features.clientcare import debts
from mailbrief.features.history import client_groups
from mailbrief.mail.classify import CATS
from mailbrief.money.ledger import ils, vendor_key
from mailbrief.util import e, money
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def clients_page():
    groups = client_groups()
    today = dt.date.today()
    owed = {}
    for d in debts():
        if d['status'] == 'open':
            owed[vendor_key(d['email'])] = owed.get(vendor_key(d['email']), 0) + 1
    rows = []
    for k, g in groups.items():
        if not (g['emails'] or g['invoices']):
            continue
        people = [h for h in g['emails'] if 'people' in h['cats'] and h.get('answered') is not None]
        rate = round(100 * sum(1 for h in people if h['answered']) / len(people)) if people else None
        since = (today - dt.date.fromisoformat(g['last'])).days if g['last'] else None
        keys = {vendor_key(h['sender']) for h in g['emails']}
        debt = sum(n for key, n in owed.items() if key in keys)
        spent = sum(ils(r) or 0 for r in g['invoices'])
        rows.append((k, g, rate, since, debt, spent))
    table = ''.join(
        f'<tr><td dir="auto"><a href="/client?key={quote(k)}">{e(g["name"])}</a></td><td>{len(g["emails"])}</td>'
        f'<td>{"—" if rate is None else f"{rate}%"}</td>'
        f'<td{" style=color:var(--warn)" if since is not None and since > 30 else ""}>{"—" if since is None else "היום" if since == 0 else f"לפני {since} ימים"}</td>'
        f'<td>{f"<b style=color:var(--warn)>⏳ {g["waiting"]}</b>" if g["waiting"] else "✓"}</td>'
        f'<td>{f"<b style=color:var(--bad)>💰 {debt}</b>" if debt else ""}</td>'
        f'<td>{money(spent) if spent else ""}</td></tr>'
        for k, g, rate, since, debt, spent in rows)
    active = len([r for r in rows if r[3] is not None and r[3] <= 30])
    kpis = ''.join(f'<div class="kpi"><b>{v}</b><span>{label}</span></div>' for label, v in [
        ('לקוחות ואנשי קשר', len(rows)), ('פעילים בחודש האחרון', active),
        ('ממתינים לתשובה ממך', sum(g['waiting'] for _, g, *_ in rows)), ('חשבוניות פתוחות', sum(owed.values()))])
    return page('לקוחות', f'''{heading('👥', 'לקוחות ואנשי קשר')}
<p class="muted">מהתוויות שלך (הכללים) ומהאנשים שיש לך קשר איתם בפועל ב-90 הימים האחרונים. לקוח חדש: כלל ב<a href="/?s=auto#rules">⚙️ הגדרות ← כללים</a>.
מעקב תשלומים וימי הולדת: <a href="/?s=clients">⚙️ הגדרות ← לקוחות</a>.</p>
<div class="kpis">{kpis}</div>
{f'<div class="scroll"><table><thead><tr><th>לקוח</th><th>מיילים</th><th>ענית</th><th>קשר אחרון</th><th>ממתינים</th><th>לא שילמו</th><th>קבלות</th></tr></thead><tbody>{table}</tbody></table></div>' if table else
 '<p class="muted">עוד אין מספיק היסטוריה — אפשר לבנות אותה בדף „📈 במספרים”.</p>'}''')


def client_page(key):
    g = client_groups().get(key)
    if not g:
        return page('לקוח', '<h1>הלקוח לא נמצא</h1>', '/clients')
    icons = {c: CATS[c][0] for c in CATS}
    timeline = ''.join(
        f'<tr><td>{e(h["date"][8:10])}/{e(h["date"][5:7])}</td><td dir="auto">'
        + (f'<a href="{e(h["link"])}" target="_blank">{e(h.get("subject") or "—")}</a>' if h.get('link') else e(h.get('subject') or '—'))
        + f'</td><td>{"".join(icons.get(c, "") for c in h["cats"])}</td><td>'
        + ('✓ נענה' if h.get('answered') else '⏳ ממתין' if h.get('answered') is False else '') + '</td></tr>'
        for h in reversed(g['emails'][-60:]))
    invoices = ''.join(
        f'<tr><td>{e(r["date"])}</td><td dir="auto">{e(r["subject"][:60])}</td><td dir="ltr">{e(r["currency"])}{r["amount"] if r["amount"] is not None else "—"}</td>'
        f'<td>{"📎" if r.get("files") else ""}</td></tr>' for r in reversed(g['invoices']))
    kpis = ''.join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for k, v in [
        ('מיילים ב-90 יום', len(g['emails'])), ('ממתינים לתשובה', g['waiting']),
        ('קבלות', len(g['invoices'])), ('סה״כ ₪', money(sum(ils(r) or 0 for r in g['invoices'])))])
    return page(g['name'], f'''<p><a href="/clients">→ כל הלקוחות</a></p><h1 dir="auto"><span class="g">{e(g["name"])}</span></h1>
<div class="kpis">{kpis}</div>
<div style="display:flex;gap:8px;flex-wrap:wrap"><a href="/search?q={quote(g["query"])}"><button type="button">🔍 כל המיילים</button></a>
<form method="post" action="/search_download" style="margin:0"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="q" value="{e(g["query"])}">
<button>📥 הורדת כל הקבצים</button></form></div>
<h3>🧾 קבלות וחשבוניות</h3>{f'<div class="scroll"><table><tbody>{invoices}</tbody></table></div>' if invoices else '<p class="muted">אין</p>'}
<h3>📨 ציר זמן</h3><div class="scroll"><table><tbody>{timeline or '<tr><td class="muted">אין</td></tr>'}</tbody></table></div>''', '/clients')
