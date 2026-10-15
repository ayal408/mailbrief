"""📇 Address book: everyone you correspond with — name, address, phone from their signature, when you last talked."""
import csv
import datetime as dt
import os
import json
import sqlite3
from contextlib import closing
from urllib.parse import quote

from mailbrief import config
from mailbrief.features.contacts import pretty, whatsapp
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
    # The inbox cache exists even before the first classification/history scan.
    cache = os.path.join(config.DATA, 'mailbox.db')
    if os.path.isfile(cache):
        with closing(sqlite3.connect(cache, timeout=2)) as db:
            for acc, raw in db.execute('SELECT acc, data FROM heads ORDER BY at DESC'):
                try:
                    row = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                sender = row.get('from') or {}
                candidates = row.get('to', []) + row.get('cc', []) if sender.get('email', '').lower() in own else ([] if row.get('news') else [sender])
                for person in candidates:
                    address = (person.get('email') or '').strip().lower()
                    if not address or '@' not in address or address in own:
                        continue
                    entry = book.setdefault(address, {'name': '', 'email': address, 'count': 0, 'last': '', 'account': acc})
                    if row.get('at', '') >= entry['last']:
                        entry.update(last=row.get('at', ''), account=acc)
                    entry['name'] = entry['name'] or person.get('name', '')
    phones = load_json(config.CONTACTS_FILE, {})
    for address, c in phones.items():       # typed by hand, even without mail in the history
        book.setdefault(address, {'name': '', 'email': address, 'count': 0, 'last': c.get('at', ''), 'account': ''})
    for p in book.values():
        p['phone'] = (phones.get(p['email']) or {}).get('phone', '')
        p['name'] = p['name'] or p['email'].split('@')[0]
    return sorted(book.values(), key=lambda p: p['last'], reverse=True)


def contacts_page(msg=''):
    rows = people()
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    body = ''.join(
        f'<tr data-text="{e((p["name"] + " " + p["email"] + " " + p["phone"]).lower())}"><td dir="auto">{dot(p["account"])}<b>{e(p["name"])}</b></td>'
        f'<td dir="ltr" style="text-align:right"><a href="/inbox?compose=1&amp;to={quote(p["email"])}" title="מייל חדש">✉️</a> '
        f'<a href="/search?q={e("from:" + p["email"])}" title="כל המיילים">{e(p["email"])}</a></td>'
        f'<td style="white-space:nowrap">' + (f'<a href="tel:{p["phone"]}" dir="ltr">{pretty(p["phone"])}</a>'
                                              + (f' <a href="{whatsapp(p["phone"])}" target="_blank" title="WhatsApp">💬</a>' if whatsapp(p["phone"]) else '')
                                              if p['phone'] else '') + '</td>'
        f'<td style="white-space:nowrap">{p["last"][8:10]}/{p["last"][5:7]}/{p["last"][2:4] if p["last"] else ""}</td><td>{p["count"] or ""}</td></tr>'
        for p in rows)
    with_phone = sum(1 for p in rows if p['phone'])
    return page('אנשי קשר', f'''{heading('📇', 'אנשי קשר')}{note}
<p class="muted">אנשים מהדואר השמור במחשב ומהיסטוריית ההתכתבויות ({len(rows)} אנשים, {with_phone} עם טלפון מהחתימה). הכול נשאר במחשב.</p>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
<input type="search" id="c-q" placeholder="🔍 חיפוש לפי שם, כתובת או טלפון…" style="flex:1;min-width:220px;font:inherit;padding:8px 12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">
<form method="post" action="/contacts_export" style="margin:0"><input type="hidden" name="t" value="{TOKEN}"><button style="margin:0;padding:8px 16px">📥 ייצוא ל-Excel</button></form>
<form method="post" action="/contacts_vcf" style="margin:0"><input type="hidden" name="t" value="{TOKEN}"><button class="ghost" style="margin:0;padding:8px 16px" title="קובץ vCard — לייבוא לטלפון או ל-Google Contacts">📱 לטלפון</button></form></div>
{f'<div class="scroll"><table id="c-table"><thead><tr><th>שם</th><th>כתובת</th><th>טלפון</th><th>אחרון</th><th>מיילים</th></tr></thead><tbody>{body}</tbody></table></div>' if rows else '<p class="muted">עוד אין — פתחו את הדואר הנכנס כדי לטעון הודעות; אנשי הקשר יופיעו מהדואר השמור במחשב.</p>'}
<script>(function(){{var q=document.getElementById('c-q');if(!q)return;q.oninput=function(){{var t=q.value.trim().toLowerCase();
document.querySelectorAll('#c-table tbody tr').forEach(function(tr){{tr.style.display=!t||tr.dataset.text.indexOf(t)>=0?'':'none';}});}};}})();</script>''', '/clients')


def export_vcf():
    """📱 הורדות\\אנשי קשר YYYY-MM-DD.vcf — one file the phone or Google Contacts imports in one go."""
    esc = lambda s: (s or '').replace('\\', '\\\\').replace(',', '\\,').replace(';', '\\;').replace('\n', ' ')
    os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
    path = os.path.join(config.DOWNLOADS_DIR, f'אנשי קשר {dt.date.today():%Y-%m-%d}.vcf')
    cards = []
    for p in people():
        lines = ['BEGIN:VCARD', 'VERSION:3.0', f'FN:{esc(p["name"])}', f'N:{esc(p["name"])};;;;', f'EMAIL;TYPE=INTERNET:{esc(p["email"])}']
        if p['phone']:
            kind = 'CELL' if p['phone'].startswith('05') else 'WORK'
            lines.append(f'TEL;TYPE={kind}:+972{p["phone"][1:]}')
        lines += ['NOTE:MailBrief', 'END:VCARD']
        cards.append('\r\n'.join(lines))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\r\n'.join(cards) + '\r\n')
    return path, len(cards)


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
