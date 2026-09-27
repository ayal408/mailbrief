"""📨 Mass mailing page: pick people from the address book or load an Excel / CSV list, write once with {שם_פרטי}."""
import datetime as dt
import os

from mailbrief import config
from mailbrief.features.mailmerge import MAX_RECIPIENTS
from mailbrief.features.outbox import when_for
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


FIELD = 'font:inherit;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink);width:100%'


def draft_path():
    return os.path.join(config.DATA, 'merge-list.json')


def _preview(choice):
    try:
        return f'{when_for(choice):%d/%m %H:%M}'
    except Exception:
        return ''


def merge_page(msg=''):
    from mailbrief.web.contacts import people
    loaded = load_json(draft_path(), {}).get('rows', [])
    book = [(p['email'], p['name']) for p in people()]
    rows = loaded or book
    source = f'מהקובץ „{e(load_json(draft_path(), {}).get("name", ""))}”' if loaded else 'מאנשי הקשר'
    accounts = ''.join(f'<option>{e(a["email"])}</option>' for a in load_json(config.ACCOUNTS_FILE, []))
    checks = ''.join(f'<label class="m-row" data-text="{e((n + " " + a).lower())}" style="display:flex;gap:8px;align-items:center;margin:0;font-weight:400;padding:4px 0">'
                     f'<input type="checkbox" name="to" value="{e(a)}"{" checked" if loaded else ""}> <b dir="auto">{e(n)}</b> '
                     f'<span class="muted" dir="ltr" style="font-size:13px">{e(a)}</span></label>' for a, n in rows[:MAX_RECIPIENTS])
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    minimum = (dt.datetime.now() + dt.timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M')
    radio = lambda value, label, checked='': (f'<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400">'
                                             f'<input type="radio" name="when" value="{value}"{checked}> {label}</label>')
    return page('מייל אישי לרשימה', f'''{heading('📨', 'מייל אישי לרשימה')}{note}
<p class="muted">כותבים פעם אחת — וכל אחד מקבל מייל נפרד עם השם שלו ({{שם_פרטי}}, {{שם}}). יוצא מהתיבה שלך בסבבים קטנים
(עד 25 בכל סבב), אף פעם לא בשבת ובחג. עד {MAX_RECIPIENTS} נמענים בפעם אחת. אף נמען לא רואה את האחרים.</p>
<form method="post" action="/merge_load" enctype="multipart/form-data" class="box" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:12px;margin-bottom:12px">
<input type="hidden" name="t" value="{TOKEN}"><span>📥 רשימה מ-Excel או CSV <span class="muted">(עמודת מייל, ועמודת שם אם יש)</span>:</span>
<input type="file" name="table" accept=".xlsx,.csv" required><button style="margin:0;padding:8px 16px">טעינה</button>
{'<button formaction="/merge_clear" formnovalidate class="ghost" style="margin:0">↩️ חזרה לאנשי הקשר</button>' if loaded else ''}</form>
<form method="post" action="/merge_send" enctype="multipart/form-data" style="display:grid;gap:10px">
<input type="hidden" name="t" value="{TOKEN}">
<div class="box" style="padding:12px"><div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px">
<b>נמענים {source}</b> · <span id="m-count">0</span> נבחרו
<input type="search" id="m-q" placeholder="🔍 סינון…" style="flex:1;min-width:160px;font:inherit;padding:6px 10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">
<button type="button" class="ghost" id="m-all" style="margin:0;padding:5px 12px">בחירת כל המוצגים</button>
<button type="button" class="ghost" id="m-none" style="margin:0;padding:5px 12px">ניקוי</button></div>
<div style="max-height:280px;overflow:auto">{checks or '<p class="muted">אין עדיין אנשי קשר — אפשר לטעון רשימה מקובץ.</p>'}</div></div>
<label style="margin:0">מהתיבה<select name="account" style="{FIELD}">{accounts}</select></label>
<label style="margin:0">נושא<input type="text" name="subject" required maxlength="300" placeholder="למשל: {{שם_פרטי}}, עדכון מחירים לשנה החדשה" style="{FIELD}"></label>
<label style="margin:0">תוכן<textarea name="body" rows="8" required placeholder="שלום {{שם_פרטי}},&#10;..." style="{FIELD}"></textarea></label>
<label style="margin:0">📎 קבצים מצורפים <span class="muted">(לא חובה — יצורפו לכל המיילים)</span><input type="file" name="files" multiple style="{FIELD}"></label>
<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">{radio('now', '📤 עכשיו', ' checked')}
{radio('after_holy', f'🕯️ אחרי שבת/חג <span class="muted">({_preview("after_holy")})</span>')}
{radio('tomorrow8', f'🌅 מחר 8:00 <span class="muted">({_preview("tomorrow8")})</span>')}
{radio('custom', '🕘 בזמן אחר:')}<input type="datetime-local" name="custom" min="{minimum}" style="font:inherit;padding:6px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)"></div>
<div><button>📨 לשלוח לכולם</button> <span class="muted" style="font-size:13px">אפשר לראות ולבטל כל מייל ב-<a href="/compose#queue">המיילים המתוזמנים</a>.</span></div></form>
<script>(function(){{var q=document.getElementById('m-q'),c=document.getElementById('m-count');
function rows(){{return Array.prototype.slice.call(document.querySelectorAll('.m-row'));}}
function count(){{c.textContent=document.querySelectorAll('.m-row input:checked').length;}}
q.oninput=function(){{var t=q.value.trim().toLowerCase();rows().forEach(function(r){{r.style.display=!t||r.dataset.text.indexOf(t)>=0?'':'none';}});}};
document.getElementById('m-all').onclick=function(){{rows().forEach(function(r){{if(r.style.display!=='none')r.querySelector('input').checked=true;}});count();}};
document.getElementById('m-none').onclick=function(){{rows().forEach(function(r){{r.querySelector('input').checked=false;}});count();}};
document.addEventListener('change',function(ev){{if(ev.target.closest&&ev.target.closest('.m-row'))count();}});count();}})();</script>''', '/today')
