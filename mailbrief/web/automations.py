"""Automations page."""
import json

from mailbrief import config
from mailbrief.features.automations import ACTIONS, COND_FIELDS, COND_OPS, describe, RECIPES, TRIGGERS, VARIABLES, WEEKDAYS, workflows
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import page
from mailbrief.web.token import TOKEN


def automations_page(msg='', test=None):
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    cards = []
    for wf in workflows():
        trig, conds, acts = describe(wf)
        on = wf.get('enabled', True)
        cards.append(f'''<div class="item" style="{'' if on else 'opacity:.55'}">
<div class="t">⚡ {e(wf["name"])} {'' if on else '<span class="pill">מושבת</span>'}</div>
<div class="s"><b>כש</b>{e(trig)}{f' · <b>אם</b> {e(conds)}' if conds else ''}<br><b>אז</b> {e(acts)}</div>
<div class="m">רץ {wf.get("runs", 0)} פעמים{f' · אחרון: {e(wf["last"])}' if wf.get('last') else ''}</div>
<form method="post" style="display:flex;gap:6px;flex-wrap:wrap"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="id" value="{e(wf["id"])}">
<button formaction="/wf_test" class="ghost">🧪 בדיקה (מה היה תופס)</button>
<button formaction="/wf_toggle" class="ghost">{'השבתה' if on else 'הפעלה'}</button>
<button formaction="/wf_delete" class="ghost">מחיקה</button></form></div>''')
    recipes = ''.join(f'<button name="recipe" value="{i}" class="ghost" style="margin:4px">{e(r["name"])}</button>'
                      for i, r in enumerate(RECIPES))
    trig_opts = ''.join(f'<option value="{k}">{v}</option>' for k, v in TRIGGERS.items())
    field_opts = ''.join(f'<option value="{k}">{v}</option>' for k, v in COND_FIELDS.items())
    op_opts = ''.join(f'<option value="{k}">{v}</option>' for k, v in COND_OPS.items())
    act_opts = '<option value="">—</option>' + ''.join(f'<option value="{k}">{v[0]}</option>' for k, v in ACTIONS.items())
    hints = json.dumps({k: v[1] for k, v in ACTIONS.items()}, ensure_ascii=False)
    sel = 'style="font:inherit;padding:8px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)"'
    cond_rows = ''.join(f'<div style="display:flex;gap:6px;margin:6px 0;flex-wrap:wrap"><select name="cf{i}" {sel}>{field_opts}</select>'
                        f'<select name="co{i}" {sel}>{op_opts}</select><input type="text" name="cv{i}" placeholder="ערך (ריק = בלי תנאי)" style="flex:1;min-width:140px"></div>'
                        for i in range(3))
    act_rows = ''.join(f'<div style="display:flex;gap:6px;margin:6px 0;flex-wrap:wrap"><select name="at{i}" class="act" {sel}>{act_opts}</select>'
                       f'<textarea name="ap{i}" rows="1" style="flex:1;min-width:180px;font:inherit;padding:8px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)"></textarea></div>'
                       for i in range(3))
    days = ''.join(f'<label style="display:inline;font-weight:400;margin-inline-end:10px"><input type="checkbox" name="day" value="{d}"> {n}</label>'
                   for n, d in WEEKDAYS)
    log = ''.join(f'<tr><td>{e(r["at"])}</td><td>{e(r["workflow"])}</td><td dir="auto">{e(r["subject"][:50])}</td>'
                  f'<td style="font-size:13px">{"<br>".join(e(x) for x in r["results"])}</td></tr>'
                  for r in reversed(load_json(config.WF_LOG, [])[-30:])) or '<tr><td class="muted">עוד לא רצה אף אוטומציה</td></tr>'
    test_html = ''
    if test is not None:
        wf, found, errors = test
        rows = ''.join(f'<li dir="auto">{e(it["subject"][:80])} <span class="muted">— {e(it["sender_name"])} · {e(it["date"])} · {e(addr)}</span></li>'
                       for addr, it in found[:30])
        test_html = (f'<div class="item" style="border-color:var(--accent)"><b>🧪 בדיקה: {e(wf["name"])}</b> — '
                     f'{len(found)} מיילים מ-7 הימים האחרונים היו מפעילים אותה (בפועל היא פועלת רק על מיילים חדשים).'
                     + ''.join(f'<div class="err">{e(x)}</div>' for x in errors)
                     + (f'<ul>{rows}</ul>' if rows else '') + '</div>')
    return page('אוטומציות', f'''<h1>⚡ אוטומציות</h1>
<p class="muted">טריגר ← תנאים ← פעולות. נבדק כל שעה בין 7:00 ל-23:00 (לא בשבת ובחג). כל מייל מפעיל כל אוטומציה פעם אחת לכל היותר.</p>
{note}{test_html}
<h3>האוטומציות שלי</h3>{"".join(cards) or '<p class="muted">עוד אין. אפשר להתחיל ממתכון 👇</p>'}
<h3>🍳 מתכונים מוכנים</h3><form method="post" action="/wf_recipe"><input type="hidden" name="t" value="{TOKEN}">{recipes}</form>
<h3>➕ אוטומציה חדשה</h3>
<form method="post" action="/wf_add" class="item" style="padding:18px"><input type="hidden" name="t" value="{TOKEN}">
<label>שם</label><input type="text" name="name" required maxlength="60" style="width:100%" placeholder="למשל: חשבוניות של לקוח כהן">
<label>כש... (טריגר)</label><select name="trigger" id="trig" {sel}>{trig_opts}</select>
<div id="wait" style="display:none"><label>אחרי כמה ימים</label><input type="number" name="wait_days" value="3" min="1" max="30"></div>
<div id="sched" style="display:none"><label>באילו ימים</label>{days}<label>באיזו שעה</label><input type="number" name="hour" value="9" min="7" max="23"></div>
<label>אם... (תנאים — כולם צריכים להתקיים)</label>{cond_rows}
<label>אז... (פעולות, לפי הסדר)</label>{act_rows}
<p class="muted" style="font-size:13px" id="hint">משתנים לשימוש בטקסט: <span dir="ltr">{VARIABLES}</span> · בתזמון: <span dir="ltr">{{waiting_list}} {{urgent_list}} {{month_total}}</span></p>
<button>שמירה</button></form>
<h3>📜 יומן ריצות</h3><div class="scroll"><table><tbody>{log}</tbody></table></div>
<script>
const hints = {hints};
const trig = document.getElementById('trig');
function sync() {{ document.getElementById('wait').style.display = trig.value === 'waiting' ? '' : 'none';
                   document.getElementById('sched').style.display = trig.value === 'schedule' ? '' : 'none'; }}
trig.onchange = sync; sync();
document.querySelectorAll('select.act').forEach(s => s.onchange = () => {{ s.nextElementSibling.placeholder = hints[s.value] || ''; }});
</script>''')
