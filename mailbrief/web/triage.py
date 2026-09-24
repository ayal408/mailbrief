"""The quick sorting page: one email at a time, one key per action."""
import json

from mailbrief.features.google_apps import gapps_account
from mailbrief.features.replies import reply_templates
from mailbrief.features.triage import queue, triage_key
from mailbrief.profile import g
from mailbrief.util import e
from mailbrief.view import color, emails
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def triage_page():
    items = [{'key': triage_key(r), 'kind': r['kind'], 'from': r.get('from', ''), 'subject': r.get('subject', ''),
              'days': r.get('days', 0), 'link': r.get('link', ''), 'account': r.get('account', ''),
              'message_id': r.get('message_id', '')} for r in queue()]
    templates = ''.join(f'<option value="{e(t["id"])}">{e(t["name"])}</option>' for t in reply_templates())
    task_button = '<button type="button" data-act="task"><kbd>4</kbd> ✅ משימה</button>' if gapps_account() else ''
    data = json.dumps(items, ensure_ascii=False).replace('</', '<\\/')
    colors = json.dumps({m: color(m) for m in emails()})
    return page('מיון מהיר', f'''{heading('⚡', 'מיון מהיר')}
<p class="muted">מייל אחד בכל פעם — מחליטים ועוברים הלאה. מקשים: <kbd>1</kbd> טופל · <kbd>2</kbd> תזכורת מחר · <kbd>3</kbd> טיוטת תשובה
{'· <kbd>4</kbd> משימה ' if task_button else ''}· <kbd>5</kbd> נודניק לשבוע · <kbd>R</kbd> תשובה · <kbd>O</kbd> פתיחה ב-Gmail · <kbd>←</kbd> דילוג · <kbd>Z</kbd> ביטול אחרון</p>
<style>
.tri{{max-width:640px;margin:18px auto;text-align:center}}
.tri .bar{{height:8px;border-radius:99px;background:var(--line);overflow:hidden;margin-bottom:14px}}
.tri .bar i{{display:block;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent-2));transition:width .35s}}
.tri .card{{background:var(--bg);border:1px solid var(--line);border-radius:20px;padding:26px 22px;min-height:190px;transition:transform .28s,opacity .28s}}
.tri .card.out{{transform:translateX(-40px) rotate(-3deg);opacity:0}}
.tri .kind{{font-size:13px;color:var(--muted)}}.tri .who{{font-size:20px;font-weight:700;margin:6px 0}}
.tri .subj{{font-size:18px;margin:4px 0 10px}}.tri .days{{display:inline-block;border-radius:99px;padding:2px 12px;font-size:13px;
background:color-mix(in srgb,var(--warn) 15%,transparent);color:var(--warn)}}
.tri .acts{{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-top:16px}}
.tri .acts button{{font:inherit;border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:10px 16px;border-radius:14px;cursor:pointer}}
.tri .acts button:hover{{border-color:var(--accent)}}.tri .acts button.main{{background:var(--accent);color:#fff;border-color:var(--accent)}}
kbd{{display:inline-block;font:12px ui-monospace,monospace;border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;padding:0 5px;background:var(--surface)}}
.tri .acts button kbd{{margin-inline-end:4px}}.tri .acts button.main kbd{{background:rgba(255,255,255,.22);color:#fff;border-color:rgba(255,255,255,.5)}}
.tri .note{{min-height:22px;margin-top:10px;color:var(--good)}}.tri .note.bad{{color:var(--bad)}}
.tri .reply{{display:none;text-align:start;margin-top:12px;background:var(--bg);border:1px solid var(--line);border-radius:16px;padding:12px}}
.tri .reply.on{{display:grid;gap:8px;animation:mbpop .3s ease}}
.tri .reply textarea,.tri .reply select,.tri .reply input{{font:inherit;padding:8px 10px;border-radius:10px;border:1px solid var(--line);background:var(--surface);color:var(--ink)}}
</style>
<div class="tri">
<div class="bar"><i id="tri-bar" style="width:0"></i></div><div class="muted" id="tri-count"></div>
<div class="card" id="tri-card"></div>
<div class="acts" id="tri-acts">
<button type="button" class="main" data-act="done"><kbd>1</kbd> ✓ טופל</button>
<button type="button" data-act="remind"><kbd>2</kbd> ⏰ מחר</button>
<span style="display:inline-flex;gap:4px"><select id="tri-tpl" style="font:inherit;border-radius:12px;border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:0 8px">{templates}</select>
<button type="button" data-act="draft"><kbd>3</kbd> 📝 טיוטה</button></span>
{task_button}
<button type="button" data-act="snooze"><kbd>5</kbd> 💤 שבוע</button>
<button type="button" data-act="reply"><kbd>R</kbd> ✍️ תשובה</button>
<button type="button" data-act="open"><kbd>O</kbd> ↗ Gmail</button>
<button type="button" data-act="skip"><kbd>←</kbd> דילוג</button>
</div>
<form class="reply" id="tri-reply" onsubmit="return false">
<textarea id="tri-text" rows="5" placeholder="התשובה שלך… ({{from_name}} = שם השולח)" dir="auto"></textarea>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<input type="file" id="tri-files" multiple style="flex:1;min-width:180px">
<select id="tri-when"><option value="now">לשלוח עכשיו</option><option value="after_holy">🕯️ אחרי שבת/חג</option>
<option value="tomorrow8">🌅 מחר ב-8:00</option><option value="sunday8">📅 יום ראשון 8:00</option></select>
<button type="button" id="tri-send" class="main" style="background:var(--accent);color:#fff;border-color:var(--accent)">✉️ שליחה</button>
<button type="button" id="tri-cancel">ביטול</button></div></form>
<div class="note" id="tri-note"></div></div>
<script>(function(){{
  var items = {data}, i = 0, total = items.length, last = null, T = '{TOKEN}', COLORS = {colors};
  var card = document.getElementById('tri-card'), note = document.getElementById('tri-note');
  function esc(s){{ var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }}
  function post(path, fields){{
    var body = new URLSearchParams(Object.assign({{t: T}}, fields));
    return fetch(path, {{method: 'POST', body: body, redirect: 'manual'}});
  }}
  function draw(){{
    document.getElementById('tri-bar').style.width = total ? ((total - items.length) / total * 100) + '%' : '100%';
    var it = items[i];
    document.getElementById('tri-acts').style.display = it ? '' : 'none';
    if (!it) {{
      document.getElementById('tri-count').textContent = '';
      card.innerHTML = '<div style="font-size:56px">🎉</div><div class="who">' + (total ? '{g("סיימת", "סיימת", "סיימנו")}! הכול מטופל' : 'אין מה למיין — הכול נענה ✨') + '</div>' +
        '<p class="muted">נתונים מהבדיקה האחרונה. <a href="/today">☀️ ל„היום שלי”</a></p>';
      if (total && window.MB && MB.confetti) MB.confetti(160);
      return;
    }}
    document.getElementById('tri-count').textContent = (i + 1) + ' מתוך ' + items.length;
    card.innerHTML = '<div class="kind">' + (it.kind === 'mine' ? '⏳ מחכה לתשובה ממך' : '📤 שלחת — ועוד לא ענו') + ' · ' +
      '<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:' + (COLORS[it.account] || '#999') + ';margin-inline-end:4px"></span>' + esc(it.account) + '</div>' +
      '<div class="who" dir="auto">' + (it.kind === 'mine' ? '' : 'אל ') + esc(it.from) + '</div>' +
      '<div class="subj" dir="auto">' + esc(it.subject) + '</div><span class="days">' + it.days + ' ימים</span>';
  }}
  function next(msg){{
    note.classList.remove('bad');
    document.getElementById('tri-reply').classList.remove('on');
    note.textContent = msg || '';
    card.classList.add('out');
    setTimeout(function(){{ card.classList.remove('out'); draw(); }}, 260);
  }}
  function act(kind){{
    var it = items[i]; if (!it) return;
    if (kind === 'open') {{ if (it.link) window.open(it.link, '_blank'); return; }}
    if (kind === 'reply') {{
      if (!it.message_id || it.kind !== 'mine') {{ note.textContent = 'תשובה אפשרית רק למייל שמחכה לתשובה ממך'; return; }}
      var box = document.getElementById('tri-reply'); box.classList.toggle('on');
      if (box.classList.contains('on')) document.getElementById('tri-text').focus();
      return;
    }}
    if (kind === 'snooze') {{
      if (!it.message_id || it.kind !== 'mine') {{ note.textContent = 'נודניק אפשרי רק למייל שמחכה לתשובה ממך'; return; }}
      note.textContent = '💤 …';
      post('/snooze', {{account: it.account, message_id: it.message_id, subject: it.subject, link: it.link, when: 'week', ajax: '1'}})
        .then(function(r){{ return r.text().then(function(t){{ return [r.ok, t]; }}); }})
        .then(function(res){{
          if (!res[0]) {{ note.classList.add('bad'); note.textContent = '⚠️ ' + res[1]; return; }}
          last = null; items.splice(i, 1); if (i >= items.length) i = 0;
          next('💤 יחזור לתיבה ב-' + res[1] + ' — ' + it.from);
        }});
      return;
    }}
    if (kind === 'skip') {{ i = (i + 1) % Math.max(items.length, 1); if (i === 0 && items.length) note.textContent = 'חזרה להתחלה'; next(note.textContent); return; }}
    var who = it.kind === 'mine' ? it.from : 'אל ' + it.from;
    if (kind === 'remind') post('/remind', {{subject: (it.kind === 'mine' ? '' : 'לבדוק מול ' + it.from + ': ') + it.subject, from: it.from, link: it.link, account: it.account, days: '1'}});
    if (kind === 'task') post('/gtask_add', {{title: (it.kind === 'mine' ? 'לענות ל-' : 'להזכיר ל-') + it.from + ': ' + it.subject, from: it.from, link: it.link}});
    if (kind === 'draft') {{
      if (!it.message_id || it.kind !== 'mine') {{ note.textContent = 'טיוטה אפשרית רק למייל שמחכה לתשובה ממך'; return; }}
      post('/draft', {{account: it.account, message_id: it.message_id, template: document.getElementById('tri-tpl').value}});
    }}
    post('/triage_done', {{key: it.key}});
    last = {{item: it, index: i}};
    items.splice(i, 1);
    if (i >= items.length) i = 0;
    next({{done: '✓ טופל', remind: '⏰ תזכורת למחר', task: '✅ נוספה משימה', draft: '📝 טיוטה נוצרת ב-Gmail'}}[kind] + ' — ' + who);
  }}
  function undo(){{
    if (!last) return;
    post('/triage_undo', {{key: last.item.key}});
    items.splice(last.index, 0, last.item); i = last.index; last = null; next('↶ הוחזר');
  }}
  document.getElementById('tri-cancel').onclick = function(){{ document.getElementById('tri-reply').classList.remove('on'); }};
  document.getElementById('tri-send').onclick = function(){{
    var it = items[i], text = document.getElementById('tri-text').value, btn = this;
    if (!it || !text.trim()) {{ note.classList.add('bad'); note.textContent = 'צריך לכתוב תשובה'; return; }}
    var form = new FormData();
    form.append('t', T); form.append('account', it.account); form.append('message_id', it.message_id);
    form.append('text', text); form.append('when', document.getElementById('tri-when').value);
    Array.prototype.forEach.call(document.getElementById('tri-files').files, function(f){{ form.append('files', f, f.name); }});
    btn.classList.add('busy');
    fetch('/reply_now', {{method: 'POST', body: form}}).then(function(r){{ return r.text().then(function(t){{ return [r.ok, t]; }}); }})
      .then(function(res){{
        btn.classList.remove('busy');
        if (!res[0]) {{ note.classList.add('bad'); note.textContent = '⚠️ ' + res[1]; return; }}
        document.getElementById('tri-text').value = ''; document.getElementById('tri-files').value = '';
        last = null; items.splice(i, 1); if (i >= items.length) i = 0;
        next(res[1] + ' — ' + it.from);
      }}).catch(function(){{ btn.classList.remove('busy'); note.classList.add('bad'); note.textContent = '⚠️ לא הצלחתי לשלוח'; }});
  }};
  document.getElementById('tri-acts').addEventListener('click', function(ev){{
    var b = ev.target.closest('button[data-act]'); if (b) act(b.dataset.act);
  }});
  if (window.__triKeys) window.removeEventListener('keydown', window.__triKeys);   // opened again after a tab switch
  window.__triKeys = function(ev){{
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || ev.ctrlKey || ev.metaKey || document.getElementById('tri-card') === null) return;
    var k = ev.key.toLowerCase();
    var map = {{'1': 'done', '2': 'remind', '3': 'draft', '4': 'task', '5': 'snooze', 'r': 'reply', 'o': 'open', 'arrowleft': 'skip'}};
    if (map[k]) {{ ev.preventDefault(); if (map[k] !== 'task' || document.querySelector('[data-act=task]')) act(map[k]); }}
    else if (k === 'z') {{ ev.preventDefault(); undo(); }}
  }};
  window.addEventListener('keydown', window.__triKeys);
  draw();
}})();</script>''')
