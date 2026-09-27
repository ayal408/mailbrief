"""📇 Address book: everyone you correspond with — name, address, phone from their signature, when you last talked."""
import csv
import datetime as dt
import os

from mailbrief import config
from mailbrief.features.contacts import phone_of, pretty, whatsapp
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.view import dot
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def people():
    """[{'name', 'email', 'phone', 'count', 'last', 'account'}] — people (not newsletters or systems), newest first."""
    own = {a['email'].lower() for a in load_json(config.ACCOUNTS_FILE, [])}
    book = {}
    for h in load_json(config.HISTORY_FILE, {}).values():
        address = (h.get('sender') or '').lower()
        if not address or address in own or 'people' not in h.get('cats', []):
            continue
        p = book.setdefault(address, {'name': '', 'email': address, 'count': 0, 'last': '', 'account': h.get('account', '')})
        p['count'] += 1
        if h.get('date', '') >= p['last']:
            p['last'], p['account'] = h.get('date', ''), h.get('account', p['account'])
            p['name'] = h.get('name') or p['name']
    for address, c in load_json(config.CONTACTS_FILE, {}).items():       # typed by hand, even without mail in the history
        book.setdefault(address, {'name': '', 'email': address, 'count': 0, 'last': c.get('at', ''), 'account': ''})
    for p in book.values():
        p['phone'] = phone_of(p['email'])
        p['name'] = p['name'] or p['email'].split('@')[0]
    return sorted(book.values(), key=lambda p: p['last'], reverse=True)


def contacts_page(msg=''):
    rows = people()
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    body = ''.join(
        f'<tr data-text="{e((p["name"] + " " + p["email"] + " " + p["phone"]).lower())}"><td dir="auto">{dot(p["account"])}<b>{e(p["name"])}</b></td>'
        f'<td dir="ltr" style="text-align:right"><a href="/search?q={e("from:" + p["email"])}">{e(p["email"])}</a></td>'
        f'<td style="white-space:nowrap">' + (f'<a href="tel:{p["phone"]}" dir="ltr">{pretty(p["phone"])}</a>'
                                              + (f' <a href="{whatsapp(p["phone"])}" target="_blank" title="WhatsApp">💬</a>' if whatsapp(p["phone"]) else '')
                                              if p['phone'] else '') + '</td>'
        f'<td style="white-space:nowrap">{p["last"][8:10]}/{p["last"][5:7]}/{p["last"][2:4] if p["last"] else ""}</td><td>{p["count"] or ""}</td></tr>'
        for p in rows)
    with_phone = sum(1 for p in rows if p['phone'])
    return page('אנשי קשר', f'''{heading('📇', 'אנשי קשר')}{note}
<p class="muted">כל מי שהתכתבת איתו ב-90 הימים האחרונים ({len(rows)} אנשים, {with_phone} עם טלפון מהחתימה). הכול נשאר במחשב.</p>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
<input type="search" id="c-q" placeholder="🔍 חיפוש לפי שם, כתובת או טלפון…" style="flex:1;min-width:220px;font:inherit;padding:8px 12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">
<form method="post" action="/contacts_export" style="margin:0"><input type="hidden" name="t" value="{TOKEN}"><button style="margin:0;padding:8px 16px">📥 ייצוא ל-Excel</button></form></div>
{f'<div class="scroll"><table id="c-table"><thead><tr><th>שם</th><th>כתובת</th><th>טלפון</th><th>אחרון</th><th>מיילים</th></tr></thead><tbody>{body}</tbody></table></div>' if rows else '<p class="muted">עוד אין — הרשימה נבנית מההיסטוריה (אפשר „בניית היסטוריה” במדריך).</p>'}
<script>(function(){{var q=document.getElementById('c-q');if(!q)return;q.oninput=function(){{var t=q.value.trim().toLowerCase();
document.querySelectorAll('#c-table tbody tr').forEach(function(tr){{tr.style.display=!t||tr.dataset.text.indexOf(t)>=0?'':'none';}});}};}})();</script>''', '/clients')


def export_csv():
    """הורדות\\אנשי קשר YYYY-MM-DD.csv — opens in Excel with Hebrew intact."""
    os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
    path = os.path.join(config.DOWNLOADS_DIR, f'אנשי קשר {dt.date.today():%Y-%m-%d}.csv')
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['שם', 'כתובת', 'טלפון', 'מייל אחרון', 'מספר מיילים'])
        for p in people():
            w.writerow([p['name'], p['email'], pretty(p['phone']) if p['phone'] else '', p['last'], p['count']])
    return path
