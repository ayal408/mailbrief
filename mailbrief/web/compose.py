"""Scheduled mail: write now, send later — never on Shabbat / Yom Tov."""
import datetime as dt
import json

from mailbrief import config
from mailbrief.features.calendar import holy_status
from mailbrief.features.outbox import outbox, when_for
from mailbrief.features.replies import reply_templates, template_files
from mailbrief.profile import profile
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def _preview(choice):
    try:
        when = when_for(choice)
        return f'{when:%d/%m %H:%M}'
    except Exception:
        return ''


def edit_form(m):
    """✏️ Change a mail that still waits — who, what and when."""
    field = 'font:inherit;font-size:14px;padding:7px 10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);width:100%'
    at = dt.datetime.fromisoformat(m['send_at']).strftime('%Y-%m-%dT%H:%M')
    return (f'<details style="margin-top:6px"><summary style="cursor:pointer;font-size:13px;color:var(--accent)">✏️ עריכה</summary>'
            f'<form method="post" action="/schedule_edit" style="display:grid;gap:6px;margin-top:6px;min-width:280px">'
            f'<input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="id" value="{e(m["id"])}">'
            f'<input type="text" name="to" dir="ltr" value="{e(", ".join(m["to"]))}" style="{field}" aria-label="אל">'
            f'<input type="text" name="subject" value="{e(m["subject"])}" style="{field}" aria-label="נושא">'
            f'<textarea name="body" rows="5" style="{field}" aria-label="תוכן">{e(m["body"])}</textarea>'
            f'<label style="margin:0;font-size:13px">מתי<input type="datetime-local" name="at" value="{at}" style="{field}"></label>'
            f'<div><button style="margin:0;padding:6px 16px">💾 שמירה</button></div></form></details>')


def follow_list():
    """⏰ The automatic follow-ups that wait for their day (a reply cancels them)."""
    from mailbrief.features.autofollow import items
    rows = ''.join(
        f'<tr><td dir="auto"><b>{e(r["subject"] or "(בלי נושא)")}</b><div class="muted" dir="ltr" style="font-size:12px;text-align:right">'
        f'{e(", ".join(r["to"]) if isinstance(r["to"], list) else r["to"])}</div></td>'
        f'<td>אם אין תשובה עד {dt.datetime.fromisoformat(r["due"]):%d/%m %H:%M}</td><td>'
        f'<form method="post" action="/follow_cancel" style="margin:0"><input type="hidden" name="t" value="{TOKEN}">'
        f'<input type="hidden" name="id" value="{e(r["id"])}"><button class="ghost" style="margin:0;padding:5px 12px">ביטול</button></form></td></tr>'
        for r in items() if r['status'] == 'waiting')
    return f'<h3>⏰ תזכורות אוטומטיות שמחכות</h3><div class="scroll"><table><tbody>{rows}</tbody></table></div>' if rows else ''


def compose_page(msg='', to='', subject='', body=''):
    accounts = load_json(config.ACCOUNTS_FILE, [])
    field = 'font:inherit;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink);width:100%'
    options = ''.join(f'<option>{e(a["email"])}</option>' for a in accounts)
    minimum = (dt.datetime.now() + dt.timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M')
    rows = ''.join(
        f'<tr><td dir="auto"><b>{e(m["subject"] or "(בלי נושא)")}</b><div class="muted" dir="ltr" style="font-size:12px;text-align:right">'
        f'{e(", ".join(m["to"]))}</div>' + (f'<div class="muted" style="font-size:12px">📎 {e(", ".join(m["files"]))}</div>' if m.get('files') else '')
        + ('<div style="font-size:12px;color:var(--warn)">📡 ממתין לחיבור לאינטרנט — יישלח לבד כשיחזור</div>' if m.get('retry') and m['status'] == 'waiting' else '')
        + (edit_form(m) if m['status'] == 'waiting' else '')
        + f'</td><td>{dt.datetime.fromisoformat(m["send_at"]):%d/%m %H:%M}</td><td style="white-space:nowrap">'
        + ({'waiting': f'<form method="post" action="/schedule_now" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                       f'<input type="hidden" name="id" value="{e(m["id"])}"><button class="ghost" style="margin:0;padding:5px 12px" title="לשלוח עכשיו במקום לחכות">📤 עכשיו</button></form> '
                       f'<form method="post" action="/schedule_cancel" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                       f'<input type="hidden" name="id" value="{e(m["id"])}"><button class="ghost" style="margin:0;padding:5px 12px">ביטול</button></form>',
            'sent': '<span style="color:var(--good)">✓ נשלח</span>', 'cancelled': '<span class="muted">בוטל</span>'}
           .get(m['status'], f'<span style="color:var(--bad)">⚠️ {e(m.get("error", ""))}</span>'))
        + '</td></tr>' for m in sorted(outbox(), key=lambda m: (m['status'] != 'waiting', m['send_at'])))
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    return page('מייל מתוזמן', f'''{heading('✉️', 'מייל מתוזמן')}{note}
<p class="muted">כותבים עכשיו — והמייל יוצא מהתיבה שלך בזמן שבחרת. אף פעם לא בשבת ובחג: זמן שנופל בתוכם עובר ל-20 דקות אחרי ההבדלה.
<br>{e(holy_status())}</p>
<form method="post" action="/schedule_mail" enctype="multipart/form-data" style="display:grid;gap:10px;max-width:720px"><input type="hidden" name="t" value="{TOKEN}">
<label style="margin:0">מהתיבה<select name="account" style="{field}">{options or '<option value="">(צריך לחבר תיבה)</option>'}</select></label>
<label style="margin:0">אל <span class="muted">(כמה כתובות — מופרדות בפסיק)</span><input type="text" name="to" dir="ltr" required value="{e(to)}" style="{field}"></label>
<label style="margin:0">נושא<input type="text" name="subject" maxlength="300" value="{e(subject)}" style="{field}"></label>
<label style="margin:0">תוכן <select id="c-tmpl" style="font:inherit;font-size:13px;padding:3px 6px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">
<option value="">📝 מתבנית…</option>{''.join(f'<option value="{e(t["text"])}" data-id="{e(t["id"])}">{e(t["name"])}{" 📎" if template_files(t["id"]) else ""}</option>' for t in reply_templates())}</select>
<input type="hidden" name="template" id="c-tid" value=""><span id="c-tfiles" class="muted" style="font-size:13px"></span>
<textarea name="body" id="c-body" rows="8" style="{field}">{e(body)}</textarea></label>
<script>(function(){{var s=document.getElementById('c-tmpl'),b=document.getElementById('c-body');if(!s)return;
s.onchange=function(){{if(!s.value)return;var me={json.dumps(profile().get('name', ''))},d=new Date().toLocaleDateString('he-IL');
var v=s.value;[['{{השם_שלי}}',me],['{{my_name}}',me],['{{היום}}',d],['{{today}}',d]].forEach(function(p){{v=v.split(p[0]).join(p[1]);}});
b.value=v;var o=s.options[s.selectedIndex];document.getElementById('c-tid').value=o.dataset.id||'';
document.getElementById('c-tfiles').textContent=o.textContent.indexOf('📎')>=0?'📎 הקבצים של התבנית יצורפו':'';s.value='';b.focus();}};}})();</script>
<div><button type="button" class="ghost" id="c-slots" style="margin:0;padding:6px 14px" title="זמנים פנויים מהיומן לשבוע הקרוב">📅 הוספת זמנים פנויים מהיומן</button>
<span id="c-slots-msg" class="muted" style="font-size:13px"></span></div>
<script>(function(){{var b=document.getElementById('c-slots');if(!b)return;b.onclick=function(){{var m=document.getElementById('c-slots-msg'),t=document.getElementById('c-body');
m.textContent='בודקת ביומן…';fetch('/free_slots',{{credentials:'same-origin'}}).then(function(r){{return r.json();}}).then(function(d){{
if(d.error){{m.textContent='⚠️ '+d.error;return;}}var s=t.selectionStart||t.value.length;t.value=t.value.slice(0,s)+(s?'\n':'')+d.text+t.value.slice(s);m.textContent='✓ נוסף';t.focus();}})
.catch(function(){{m.textContent='⚠️ לא הצלחתי לבדוק את היומן';}});}};}})();</script>
<label style="margin:0">📎 קבצים מצורפים <span class="muted">(לא חובה · עד 20MB ביחד)</span><input type="file" name="files" multiple style="{field}"></label>
<details class="box" style="padding:10px 14px"><summary style="cursor:pointer"><b>⏰ תזכורת אוטומטית אם לא עונים</b> <span class="muted" style="font-size:13px">(לא חובה)</span></summary>
<label style="margin:8px 0 0;display:flex;gap:8px;align-items:center;font-weight:400"><input type="checkbox" name="follow" value="1"> אם אין תשובה תוך
<select name="follow_days" style="font:inherit;padding:4px 8px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">
<option value="2">יומיים</option><option value="3" selected>3 ימים</option><option value="5">5 ימים</option><option value="7">שבוע</option></select>
— לשלוח תזכורת מנומסת באותה שיחה</label>
<textarea name="follow_text" rows="3" placeholder="שלום, רציתי לוודא שההודעה הקודמת שלי הגיעה — אשמח לתשובה כשיתאפשר. תודה!" style="{field};margin-top:6px"></textarea>
<div class="muted" style="font-size:12px">תשובה מהנמען מבטלת את התזכורת. אף פעם לא בשבת ובחג.</div></details>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="when" value="after_holy" checked> 🕯️ אחרי שבת/חג <span class="muted">({_preview('after_holy')})</span></label>
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="when" value="tomorrow8"> 🌅 מחר ב-8:00 <span class="muted">({_preview('tomorrow8')})</span></label>
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="when" value="sunday8"> 📅 יום ראשון 8:00 <span class="muted">({_preview('sunday8')})</span></label>
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="when" value="custom"> 🕘 בזמן אחר:
<input type="datetime-local" name="custom" min="{minimum}" style="font:inherit;padding:6px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)"></label>
</div>
<div><button>⏳ לתזמן</button> <a href="/greetings" style="margin-inline-start:12px">🗓️ ברכות חג ללקוחות ←</a></div></form>
<h3 id="queue">📤 המיילים המתוזמנים</h3>
{f'<div class="scroll"><table><tbody>{rows}</tbody></table></div>' if rows else '<p class="muted">עוד אין</p>'}
{follow_list()}
<p class="muted" style="font-size:13px">השליחה נעשית מהמחשב: כש-MailBrief פתוח (או ליד השעון) — תוך דקתיים מהזמן; אחרת בבדיקה השעתית הבאה.
<br><a href="/merge">📨 מייל אישי לרשימה שלמה ←</a></p>''')
