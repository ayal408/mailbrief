"""Client cards."""
from urllib.parse import quote

from mailbrief.features.history import client_groups
from mailbrief.mail.classify import CATS
from mailbrief.money.ledger import ils
from mailbrief.util import e, money
from mailbrief.web.layout import page
from mailbrief.web.token import TOKEN


def clients_page():
    groups = client_groups()
    cards = ''.join(
        f'<a href="/client?key={quote(k)}" style="text-decoration:none;color:inherit"><div class="item">'
        f'<div class="t" dir="auto">{e(g["name"])}</div>'
        f'<div class="m">{len(g["emails"])} מיילים ב-90 יום · קשר אחרון {e(g["last"][8:10])}/{e(g["last"][5:7])}'
        f'{f" · 🧾 {len(g["invoices"])} קבלות ({money(sum(ils(r) or 0 for r in g["invoices"]))})" if g["invoices"] else ""}'
        f'{f" · <b style=color:var(--warn)>⏳ {g["waiting"]} ממתינים</b>" if g["waiting"] else ""}</div></div></a>'
        for k, g in groups.items() if g['emails'] or g['invoices'])
    return page('לקוחות', f'''<h1>👥 לקוחות ואנשי קשר</h1>
<p class="muted">מהתוויות שלך (הכללים) ומהאנשים שאת בקשר איתם בפועל ב-90 הימים האחרונים. להוספת לקוח: כלל חדש בדף הראשי.</p>
{cards or '<p class="muted">עוד אין מספיק היסטוריה — אפשר לבנות אותה בדף „📈 במספרים”.</p>'}''')


def client_page(key):
    g = client_groups().get(key)
    if not g:
        return page('לקוח', '<h1>הלקוח לא נמצא</h1>')
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
    return page(g['name'], f'''<p><a href="/clients">→ כל הלקוחות</a></p><h1 dir="auto">{e(g["name"])}</h1>
<div class="kpis">{kpis}</div>
<div style="display:flex;gap:8px;flex-wrap:wrap"><a href="/search?q={quote(g["query"])}"><button type="button">🔍 כל המיילים</button></a>
<form method="post" action="/search_download" style="margin:0"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="q" value="{e(g["query"])}">
<button>📥 הורדת כל הקבצים</button></form></div>
<h3>🧾 קבלות וחשבוניות</h3>{f'<div class="scroll"><table><tbody>{invoices}</tbody></table></div>' if invoices else '<p class="muted">אין</p>'}
<h3>📨 ציר זמן</h3><div class="scroll"><table><tbody>{timeline or '<tr><td class="muted">אין</td></tr>'}</tbody></table></div>''')
