"""Scheduled mail: write now, send later — never on Shabbat / Yom Tov."""
import datetime as dt

from mailbrief import config
from mailbrief.features.calendar import holy_status
from mailbrief.features.outbox import outbox, when_for
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


def compose_page(msg=''):
    accounts = load_json(config.ACCOUNTS_FILE, [])
    field = 'font:inherit;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink);width:100%'
    options = ''.join(f'<option>{e(a["email"])}</option>' for a in accounts)
    minimum = (dt.datetime.now() + dt.timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M')
    rows = ''.join(
        f'<tr><td dir="auto"><b>{e(m["subject"] or "(בלי נושא)")}</b><div class="muted" dir="ltr" style="font-size:12px;text-align:right">'
        f'{e(", ".join(m["to"]))}</div>' + (f'<div class="muted" style="font-size:12px">📎 {e(", ".join(m["files"]))}</div>' if m.get('files') else '')
        + f'</td><td>{dt.datetime.fromisoformat(m["send_at"]):%d/%m %H:%M}</td><td>'
        + ({'waiting': f'<form method="post" action="/schedule_cancel" style="margin:0"><input type="hidden" name="t" value="{TOKEN}">'
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
<label style="margin:0">אל <span class="muted">(כמה כתובות — מופרדות בפסיק)</span><input type="text" name="to" dir="ltr" required style="{field}"></label>
<label style="margin:0">נושא<input type="text" name="subject" maxlength="300" style="{field}"></label>
<label style="margin:0">תוכן<textarea name="body" rows="8" style="{field}"></textarea></label>
<label style="margin:0">📎 קבצים מצורפים <span class="muted">(לא חובה · עד 20MB ביחד)</span><input type="file" name="files" multiple style="{field}"></label>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="when" value="after_holy" checked> 🕯️ אחרי שבת/חג <span class="muted">({_preview('after_holy')})</span></label>
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="when" value="tomorrow8"> 🌅 מחר ב-8:00 <span class="muted">({_preview('tomorrow8')})</span></label>
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="when" value="sunday8"> 📅 יום ראשון 8:00 <span class="muted">({_preview('sunday8')})</span></label>
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="when" value="custom"> 🕘 בזמן אחר:
<input type="datetime-local" name="custom" min="{minimum}" style="font:inherit;padding:6px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)"></label>
</div>
<div><button>⏳ לתזמן</button> <a href="/greetings" style="margin-inline-start:12px">🗓️ ברכות חג ללקוחות ←</a></div></form>
<h3>המיילים המתוזמנים</h3>
{f'<div class="scroll"><table><tbody>{rows}</tbody></table></div>' if rows else '<p class="muted">עוד אין</p>'}
<p class="muted" style="font-size:13px">השליחה נעשית מהמחשב: כש-MailBrief פתוח (או ליד השעון) — תוך דקתיים מהזמן; אחרת בבדיקה השעתית הבאה.</p>''')
