"""The first-run welcome: name and form of address, before anything else."""
from mailbrief.profile import DEFAULT_GOALS, FORMS, GOALS, profile, welcome_back
from mailbrief.util import e
from mailbrief.web.layout import page
from mailbrief.web.token import TOKEN


def welcome_page():
    me = profile()
    chosen = me.get('form', '')
    choices = ''.join(
        f'<label class="pick"><input type="radio" name="form" value="{k}" required{" checked" if k == chosen else ""} '
        f'data-hello="{e(welcome_back(k))}"><span><b>{icon}</b>{label}</span></label>'
        for k, (icon, label) in FORMS.items())
    picked = me.get('goals', DEFAULT_GOALS)
    goal_boxes = ''.join(
        f'<label class="goal"><input type="checkbox" name="goal" value="{k}"{" checked" if k in picked else ""}>'
        f'<span><b>{icon}</b><i>{e(title)}</i><small>{e(sub)}</small></span></label>' for k, (icon, title, sub) in GOALS.items())
    return page('ברוכים הבאים', f'''
<style>
.welcome{{max-width:560px;margin:0 auto;text-align:center}}
.welcome input[type=text]{{width:100%;font:inherit;font-size:18px;padding:14px 16px;border:1px solid var(--line);border-radius:14px;
background:var(--bg);color:var(--ink);text-align:center}}
.picks{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0 6px}}
.pick input{{position:absolute;opacity:0;pointer-events:none}}
.pick span{{display:grid;gap:4px;place-items:center;padding:16px 8px;border:1px solid var(--line);border-radius:16px;background:var(--bg);cursor:pointer;
transition:.15s;font-size:15px}}
.pick span b{{font-size:34px;font-weight:400;transition:transform .2s}}
.pick span:hover{{border-color:var(--accent)}}
.pick input:checked + span{{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,var(--bg));box-shadow:0 6px 18px color-mix(in srgb,var(--accent) 25%,transparent)}}
.pick input:checked + span b{{transform:scale(1.15) rotate(-6deg)}}
.pick input:focus-visible + span{{outline:2px solid var(--accent);outline-offset:2px}}
#preview{{font-size:20px;font-weight:700;min-height:32px;margin:14px 0}}
.goals{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:12px 0}}
.goal input{{position:absolute;opacity:0;pointer-events:none}}
.goal span{{display:grid;gap:2px;padding:12px 10px;border:1px solid var(--line);border-radius:14px;background:var(--bg);cursor:pointer;transition:.15s;text-align:center}}
.goal span b{{font-size:26px;font-weight:400}}.goal span i{{font-style:normal;font-weight:500}}.goal span small{{color:var(--muted);font-size:12px}}
.goal input:checked + span{{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 12%,var(--bg))}}
.goal input:focus-visible + span{{outline:2px solid var(--accent);outline-offset:2px}}
@media(max-width:480px){{.picks{{grid-template-columns:1fr}}}}
</style>
<div class="welcome">
<h1>נעים להכיר 👋</h1>
<p class="muted">שתי שאלות קצרות, פעם אחת — כדי ש-MailBrief ידבר בדיוק בלשון שמתאימה לך. אפשר לשנות בכל רגע בהגדרות.</p>
<form method="post" action="/welcome"><input type="hidden" name="t" value="{TOKEN}">
<label for="nm" style="display:block;font-weight:500;margin:18px 0 6px">איך קוראים לך? <span class="muted" style="font-weight:400">(לא חובה)</span></label>
<input type="text" id="nm" name="name" maxlength="30" value="{e(me.get("name", ""))}" placeholder="השם שלך" autocomplete="given-name">
<div style="font-weight:500;margin:20px 0 0">באיזו לשון לפנות?</div>
<div class="picks">{choices}</div>
<div id="preview" class="g"></div>
<div style="font-weight:500;margin:22px 0 0">מה הכי חשוב לך? <span class="muted" style="font-weight:400">(בערך 3 — השאר נשאר זמין בלחיצה)</span></div>
<div class="goals">{goal_boxes}</div>
<button style="font-size:17px;padding:13px 30px">יאללה, מתחילים ✨</button>
</form></div>
<script>(function(){{
  var nm = document.getElementById('nm'), out = document.getElementById('preview');
  function show(){{
    var pick = document.querySelector('.pick input:checked'), name = nm.value.trim();
    out.textContent = pick ? 'שלום' + (name ? ' ' + name : '') + ', ' + pick.dataset.hello + '!' : '';
  }}
  nm.addEventListener('input', show);
  Array.prototype.forEach.call(document.querySelectorAll('.pick input'), function(r){{ r.addEventListener('change', function(){{ show(); if (window.MB && MB.confetti) MB.confetti(40); }}); }});
  show();
}})();</script>''')
