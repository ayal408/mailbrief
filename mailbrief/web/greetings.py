"""Holiday greetings page."""
import datetime as dt
import json

from mailbrief import config
from mailbrief.features.greetings import MAX_RECIPIENTS, next_date, OCCASIONS, recipients
from mailbrief.profile import profile
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def greetings_page(msg=''):
    accounts = load_json(config.ACCOUNTS_FILE, [])
    people = recipients()
    field = 'font:inherit;padding:10px 12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink);width:100%'
    presets = {k: {'subject': s, 'text': t, 'date': (next_date(k) - dt.timedelta(days=1)).isoformat() if next_date(k) else ''}
               for k, (_, s, t) in OCCASIONS.items()}
    first = next((k for k in ('rosh', 'sukkot', 'chanukah', 'purim', 'pesach', 'shavuot') if presets[k]['date']), 'rosh')
    default_day = presets[first]['date'] or (dt.date.today() + dt.timedelta(days=1)).isoformat()
    occasion_opts = ''.join(f'<option value="{k}"{" selected" if k == first else ""}>{label}'
                            + (f' — {presets[k]["date"][8:10]}/{presets[k]["date"][5:7]}' if presets[k]['date'] else '') + '</option>'
                            for k, (label, _, _) in OCCASIONS.items())
    rows = ''.join(
        f'<label class="who"><input type="checkbox" name="to" value="{e(p["email"])}"{" checked" if p["suggested"] else ""}>'
        f'<span><b dir="auto">{e(p["name"] or p["email"])}</b> <span class="muted" dir="ltr">{e(p["email"])}</span>'
        + ''.join(f' <span class="pill">{e(label)}</span>' for label in p['labels'])
        + f'<span class="muted" style="font-size:12px"> · {p["count"]} מיילים</span></span></label>' for p in people)
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    return page('ברכות חג', f'''{heading('🗓️', 'ברכות חג ללקוחות')}{note}
<p class="muted">מייל אישי לכל אחד — עם השם שלו — מהתיבה שלך. נשלח בזמן שבוחרים, בקבוצות קטנות, ואף פעם לא בשבת ובחג.
הרשימה: אנשים שבאמת התכתבת איתם בשנה האחרונה (בלי ניוזלטרים, חנויות ורובוטים). מסומנים מראש: לקוחות עם תווית, מי שעניתם לו, ומי שכתב 3+ פעמים.</p>
<style>.who{{display:flex;gap:8px;align-items:flex-start;padding:7px 10px;border-radius:10px;margin:0;font-weight:400;cursor:pointer}}
.who:hover{{background:var(--bg)}}.people{{max-height:360px;overflow:auto;border:1px solid var(--line);border-radius:14px;padding:6px}}</style>
<form method="post" action="/greetings" style="display:grid;gap:10px;max-width:760px"><input type="hidden" name="t" value="{TOKEN}">
<label style="margin:0">לאיזה חג<select name="occasion" id="gr-occ" style="{field}">{occasion_opts}</select></label>
<label style="margin:0">נושא<input type="text" name="subject" id="gr-subj" value="{e(presets[first]['subject'])}" style="{field}"></label>
<label style="margin:0">נוסח <span class="muted">({{first_name}} = השם הפרטי, {{my_name}} = השם שלך)</span>
<textarea name="text" id="gr-text" rows="8" style="{field}">{e(presets[first]['text'])}</textarea></label>
<label style="margin:0">החתימה שלך<input type="text" name="my_name" value="{e(profile().get('name', ''))}" style="{field}"></label>
<div style="display:flex;gap:10px;flex-wrap:wrap">
<label style="margin:0;flex:1;min-width:200px">מהתיבה<select name="account" style="{field}">{''.join(f'<option>{e(a["email"])}</option>' for a in accounts)}</select></label>
<label style="margin:0">ביום<input type="date" name="day" id="gr-day" value="{default_day}" style="{field}"></label>
<label style="margin:0">בשעה<input type="time" name="at" value="10:00" style="{field}"></label></div>
<div class="muted" style="font-size:13px">ברירת המחדל: ערב החג ב-10:00. זמן שנופל בשבת או בחג עובר ל-20 דקות אחרי ההבדלה.</div>
<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
<b>נמענים (<span id="gr-count">0</span>)</b>
<span><input type="search" id="gr-find" placeholder="חיפוש…" style="font:inherit;padding:6px 10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);width:180px">
<button type="button" class="ghost" id="gr-all" style="margin:0;padding:6px 12px">הכול</button>
<button type="button" class="ghost" id="gr-none" style="margin:0;padding:6px 12px">אף אחד</button></span></div>
<div class="people">{rows or '<p class="muted">עוד אין מספיק היסטוריה — אפשר לבנות אותה ב„מדריך ← בניית היסטוריה”.</p>'}</div>
<div class="item" id="gr-preview" style="white-space:pre-wrap" dir="auto"></div>
<div><button>🗓️ לתזמן את הברכות</button> <span class="muted" style="font-size:13px">עד {MAX_RECIPIENTS} בפעם אחת · אפשר לבטל כל אחת ב„מייל מתוזמן”</span></div>
</form>
<script>(function(){{
  var P = {json.dumps(presets, ensure_ascii=False)}, people = {json.dumps({p['email']: p for p in people}, ensure_ascii=False)};
  var occ = document.getElementById('gr-occ'), text = document.getElementById('gr-text'), subj = document.getElementById('gr-subj');
  function boxes(){{ return Array.prototype.slice.call(document.querySelectorAll('.who input')); }}
  function preview(){{
    var chosen = boxes().filter(function(b){{ return b.checked; }});
    document.getElementById('gr-count').textContent = chosen.length;
    var p = chosen.length ? people[chosen[0].value] : {{first_name: 'דנה', name: 'דנה'}};
    var me = document.querySelector('[name=my_name]').value;
    document.getElementById('gr-preview').textContent = '👀 תצוגה מקדימה' + (chosen.length ? ' (ל' + (p.name || p.email) + ')' : '') + ':\\n\\n' +
      text.value.split('{{first_name}}').join(p.first_name || '').split('{{name}}').join(p.name || '').split('{{my_name}}').join(me).replace('שלום ,', 'שלום,');
  }}
  occ.addEventListener('change', function(){{
    var x = P[occ.value]; subj.value = x.subject; text.value = x.text;
    if (x.date) document.getElementById('gr-day').value = x.date;
    preview();
  }});
  document.getElementById('gr-all').onclick = function(){{ boxes().forEach(function(b){{ if (b.closest('.who').style.display !== 'none') b.checked = true; }}); preview(); }};
  document.getElementById('gr-none').onclick = function(){{ boxes().forEach(function(b){{ b.checked = false; }}); preview(); }};
  document.getElementById('gr-find').addEventListener('input', function(){{
    var q = this.value.trim().toLowerCase();
    document.querySelectorAll('.who').forEach(function(l){{ l.style.display = !q || l.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none'; }});
  }});
  document.addEventListener('input', function(ev){{ if (ev.target === text || ev.target.name === 'my_name') preview(); }});
  document.addEventListener('change', function(ev){{ if (ev.target.closest && ev.target.closest('.who')) preview(); }});
  preview();
}})();</script>''')
