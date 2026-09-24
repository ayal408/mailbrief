"""The "My day" page."""
import datetime as dt

from mailbrief.features.clientcare import DATE_KINDS, debts, upcoming_dates
from mailbrief.money.books import missing_invoices
from mailbrief import config
from mailbrief import net
from mailbrief.features.alerts import upcoming_payments
from mailbrief.features.google_apps import today_overview
from mailbrief.features.invites import invite_key, upcoming, when_text
from mailbrief.features.calendar import CITIES, holy_status
from mailbrief.features.replies import reply_templates, vacation_active
from mailbrief.profile import g, goals
from mailbrief.features.triage import dismissed, queue, triage_key
from mailbrief.money.accountant import price_change_text, price_changes
from mailbrief.features.outbox import outbox
from mailbrief.features.snooze import snoozed
from mailbrief.view import current_account, dot, mine
from mailbrief.features.today import FORTUNES, project_pulse, projects_root, WEATHER
from mailbrief.money.ledger import find_subscriptions
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import page, update_banner
from mailbrief.web.token import TOKEN


SORTER = ('<select class="mb-sort" data-for="{list}" title="מיון" style="float:left;font:inherit;font-size:12px;padding:2px 4px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font-weight:400"><option value="old">⏳ הכי ותיק</option><option value="new">🆕 הכי חדש</option><option value="name">🔤 לפי שם</option><option value="account">📬 לפי תיבה</option></select>')


SMALL = ('font:inherit;font-size:12px;padding:1px 8px;margin:0 4px;border-radius:8px;border:1px solid var(--line);'
         'background:transparent;color:var(--ink);cursor:pointer')


FOCUS = """<div class="focus" id="mb-timer" data-mode="focus"><span id="focus"></span>
<div class="ring"><svg width="150" height="150" viewBox="0 0 150 150"><circle cx="75" cy="75" r="64" fill="none" stroke="var(--line)" stroke-width="10"/>
<circle class="bar2" cx="75" cy="75" r="64" fill="none" stroke="url(#mbg)" stroke-width="10" stroke-linecap="round" stroke-dasharray="402.1" stroke-dashoffset="0"/>
<defs><linearGradient id="mbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c3aed"/><stop offset="1" stop-color="#f97316"/></linearGradient></defs></svg>
<div class="t">25:00</div></div><div class="muted lbl" style="font-size:13px">ריכוז</div>
<div class="row"><button type="button" data-mode="focus" onclick="MBFocus.mode('focus')">🍅 25</button>
<button type="button" data-mode="short" onclick="MBFocus.mode('short')">☕ 5</button><button type="button" data-mode="long" onclick="MBFocus.mode('long')">🌿 15</button></div>
<div class="row"><button type="button" data-go onclick="MBFocus.go()">▶ התחלה</button><button type="button" onclick="MBFocus.reset()">↺ איפוס</button></div></div>"""


NOTES_JS = """<script>(function(){
  var box = document.getElementById('mb-notes'), ok = document.getElementById('mb-saved'), t = null;
  function save(){
    var body = new URLSearchParams({t: '__TOKEN__', text: box.value});
    fetch('/note_save', {method: 'POST', body: body, keepalive: true, redirect: 'manual'}).then(function(){
      ok.classList.add('on'); setTimeout(function(){ ok.classList.remove('on'); }, 1400);
    }).catch(function(){});
  }
  box.addEventListener('input', function(){ clearTimeout(t); t = setTimeout(save, 700); });
  window.addEventListener('pagehide', function(){ if (t) { clearTimeout(t); save(); } });
})();</script>"""


def today_page(msg='', show_all=False):
    now = dt.datetime.now()
    city = load_json(config.SETTINGS_FILE, {}).get('city', 'ירושלים')
    lat, lon = CITIES.get(city, CITIES['ירושלים'])
    days = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']
    heb = (net.cached_json('hebdate', f'https://www.hebcal.com/converter?cfg=json&date={now.date()}&g2h=1&strict=1', 360) or {}).get('hebrew', '')

    w = net.cached_json('weather', 'https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}&current=temperature_2m,weather_code'
                    '&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia/Jerusalem&forecast_days=1'
                    .format(lat, lon), 30)
    weather = '<span class="muted">אין חיבור לתחזית כרגע</span>'
    if w:
        code = w['current']['weather_code']
        icon, word = next(((i, t) for limit, i, t in WEATHER if code <= limit), ('🌡️', ''))
        rain = w['daily']['precipitation_probability_max'][0]
        weather = (f'<span style="font-size:44px">{icon}</span> <b style="font-size:32px">{round(w["current"]["temperature_2m"])}°</b> '
                   f'<span class="muted">{word} · {round(w["daily"]["temperature_2m_min"][0])}°–{round(w["daily"]["temperature_2m_max"][0])}°'
                   f'{f" · ☔ {rain}% גשם" if rain else ""}</span>')

    shabbat = net.cached_json('shabbat', f'https://www.hebcal.com/shabbat?cfg=json&geo=pos&latitude={lat}&longitude={lon}'
                          '&tzid=Asia/Jerusalem&M=on&lg=he', 360) or {'items': []}
    times = ''.join(f'<li>{"🕯️" if i["category"] == "candles" else "🍷"} {e(i.get("hebrew") or i["title"])} — '
                    f'{e(days[dt.datetime.fromisoformat(i["date"]).weekday()])} {e(i["date"][11:16])}</li>'
                    for i in shabbat['items'] if i['category'] in ('candles', 'havdalah'))
    parasha = next((i.get('hebrew') or i['title'] for i in shabbat['items'] if i['category'] == 'parashat'), '')
    end = now.date() + dt.timedelta(days=21)
    hol = net.cached_json('holidays', f'https://www.hebcal.com/hebcal?v=1&cfg=json&maj=on&min=on&mod=on&i=on&lg=he'
                      f'&start={now.date()}&end={end}', 360) or {'items': []}
    holidays = ''.join(f'<li>{e(i.get("hebrew") or i["title"])} — {e(dt.date.fromisoformat(i["date"][:10]).strftime("%d/%m"))}</li>'
                       for i in hol['items'][:6])

    wanted = set(goals())
    def want(*keys):
        return show_all or not keys or bool(wanted & set(keys))
    card = lambda title, body: f'<div class="box" style="background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:16px 18px"><h3 style="margin:0 0 8px">{title}</h3>{body}</div>'
    snap = load_json(config.SNAPSHOT_FILE, {})
    box = current_account()
    snap = {k: ([r for r in v if mine(r, current=box)] if isinstance(v, list) else v) for k, v in snap.items()}
    gapps = today_overview()
    calendar_card = tasks_card = ''
    if gapps:
        field = 'font:inherit;font-size:14px;padding:5px 8px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink)'
        events = ''.join(
            f'<li dir="auto"><b>{e(ev["time"])}{f"–{e(ev["end"])}" if ev["end"] else ""}</b> '
            + (f'<a href="{e(ev["link"])}" target="_blank">{e(ev["title"][:70])}</a>' if ev['link'] else e(ev['title'][:70]))
            + (f' <span class="muted">· 📍 {e(ev["where"][:40])}</span>' if ev['where'] else '') + '</li>'
            for ev in gapps.get('events', [])) or ('' if gapps.get('events_error') else '<li class="muted">אין אירועים היום</li>')
        calendar_card = card('📅 היום ביומן', (f'<div style="color:var(--bad);font-size:14px">⚠️ {e(gapps["events_error"])}</div>' if gapps.get('events_error') else '')
            + f'<ul style="margin:0;padding-inline-start:18px">{events}</ul>'
            f'<form method="post" action="/gevent_add" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px"><input type="hidden" name="t" value="{TOKEN}">'
            f'<input name="title" required maxlength="300" placeholder="אירוע חדש" style="flex:1;min-width:120px;{field}">'
            f'<input type="date" name="day" required value="{now.date()}" style="{field}"><input type="time" name="at" style="{field}" title="ריק = כל היום">'
            f'<button style="{SMALL}">➕</button></form>'
            f'<div class="muted" style="font-size:12px;margin-top:4px"><a href="https://calendar.google.com/calendar/r/day" target="_blank">פתיחת היומן</a> · {e(gapps["account"])}</div>')
        today_iso = now.date().isoformat()
        def task_when(due):
            if not due:
                return ''
            color = 'var(--bad)' if due < today_iso else 'var(--warn)' if due == today_iso else 'var(--muted)'
            return f' <span style="color:{color};font-size:13px">· {"היום" if due == today_iso else f"{due[8:10]}/{due[5:7]}"}</span>'
        tasks = ''.join(
            f'<li dir="auto" style="list-style:none;margin-inline-start:-18px"><form method="post" action="/gtask_done" style="display:inline;margin:0">'
            f'<input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="id" value="{e(t["id"])}">'
            f'<button title="בוצע" style="font:inherit;padding:0 4px;border:0;background:transparent;color:var(--ink);cursor:pointer">⬜</button></form> '
            + (f'<a href="{e(t["link"])}" target="_blank">{e(t["title"][:70])}</a>' if t['link'] else e(t['title'][:70])) + task_when(t['due']) + '</li>'
            for t in gapps.get('tasks', [])[:12]) or ('' if gapps.get('tasks_error') else '<li class="muted">אין משימות פתוחות 🎉</li>')
        more = len(gapps.get('tasks', [])) - 12
        tasks_card = card('✅ משימות', (f'<div style="color:var(--bad);font-size:14px">⚠️ {e(gapps["tasks_error"])}</div>' if gapps.get('tasks_error') else '')
            + f'<ul style="margin:0;padding-inline-start:18px">{tasks}</ul>' + (f'<div class="muted" style="font-size:13px">ועוד {more}…</div>' if more > 0 else '')
            + f'<form method="post" action="/gtask_add" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px"><input type="hidden" name="t" value="{TOKEN}">'
            f'<input name="title" required maxlength="300" placeholder="משימה חדשה" style="flex:1;min-width:120px;{field}">'
            f'<input type="date" name="due" style="{field}" title="תאריך יעד (לא חובה)"><button style="{SMALL}">➕</button></form>'
            '<div class="muted" style="font-size:12px;margin-top:4px"><a href="https://tasks.google.com/" target="_blank">פתיחת Google Tasks</a></div>')
    def mail_row(r, tail, remind=False):
        title = f'<a href="{e(r["link"])}" target="_blank">{e(r["subject"][:70])}</a>' if r.get('link') else e(r['subject'][:70])
        button = (f'<form method="post" action="/remind" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                  + ''.join(f'<input type="hidden" name="{k}" value="{e(str(r.get(v, "")))}">' for k, v in
                            (('subject', 'subject'), ('from', 'from'), ('link', 'link'), ('account', 'account')))
                  + '<input type="hidden" name="days" value="1"><button style="font:inherit;font-size:12px;padding:1px 8px;margin:0 4px;border-radius:8px;'
                    'border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer">⏰ מחר</button></form>') if remind else ''
        if remind and r.get('message_id'):
            button += (f'<form method="post" action="/draft" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                       f'<input type="hidden" name="account" value="{e(r["account"])}"><input type="hidden" name="message_id" value="{e(r["message_id"])}">'
                       f'<select name="template" style="font:inherit;font-size:12px;padding:1px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">'
                       + ''.join(f'<option value="{e(t["id"])}">{e(t["name"])}</option>' for t in reply_templates())
                       + '</select><button style="font:inherit;font-size:12px;padding:1px 8px;margin:0 4px;border-radius:8px;border:1px solid var(--line);'
                         'background:transparent;color:var(--ink);cursor:pointer">📝 טיוטה</button></form>')
        if remind and r.get('message_id'):
            button += (f'<form method="post" action="/snooze" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                       + ''.join(f'<input type="hidden" name="{k}" value="{e(str(r.get(k, "")))}">' for k in ('account', 'message_id', 'subject', 'link'))
                       + '<select name="when" onchange="this.form.submit()" title="נודניק — להחזיר לתיבה אחר כך" style="font:inherit;font-size:12px;padding:1px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink);margin:0 4px">'
                       '<option value="">💤</option><option value="tomorrow8">מחר 8:00</option><option value="sunday8">יום ראשון</option>'
                       '<option value="week">בעוד שבוע</option></select></form>')
        if remind and gapps:
            button += (f'<form method="post" action="/gtask_add" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                       f'<input type="hidden" name="title" value="{e("לענות ל-" + r["from"] + ": " + r["subject"][:120])}">'
                       f'<input type="hidden" name="from" value="{e(r["from"])}"><input type="hidden" name="link" value="{e(r.get("link", ""))}">'
                       f'<button style="{SMALL}" title="משימה ב-Google Tasks">✅ משימה</button></form>')
        return (f'<li dir="auto" data-days="{r.get("days", 0)}" data-name="{e(r["from"])}" data-account="{e(r.get("account", ""))}">'
                f'{dot(r.get("account", ""))}{title} <span class="muted">— {e(r["from"])} · {tail}</span>{button}</li>')
    to_sort = len(queue())
    scheduled = [m for m in outbox() if m['status'] == 'waiting']
    quick_bar = ('<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">'
                 + (f'<a href="/triage"><button type="button">⚡ מיון מהיר ({to_sort})</button></a>' if to_sort else '')
                 + '<a href="/compose"><button type="button" class="ghost">✉️ מייל מתוזמן'
                 + (f' ({len(scheduled)} ממתינים)' if scheduled else '') + '</button></a>'
                 + '<a href="/greetings"><button type="button" class="ghost">🗓️ ברכות חג</button></a></div>')
    sleeping = [s for s in snoozed() if mine(s, current=box)]
    snoozed_card = card('💤 בנודניק', '<ul style="margin:0;padding-inline-start:18px">' + ''.join(
        f'<li dir="auto">{dot(s["account"])}{e(s["subject"][:60])} <span class="muted">— חוזר {dt.datetime.fromisoformat(s["until"]):%d/%m %H:%M}</span>'
        f'<form method="post" action="/snooze_wake" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
        f'<input type="hidden" name="id" value="{e(s["id"])}"><button style="{SMALL}">להחזיר עכשיו</button></form></li>'
        for s in sorted(sleeping, key=lambda s: s['until'])[:8]) + '</ul>') if sleeping else ''
    handled = dismissed()
    waiting = ''.join(mail_row(r, f'⏳ {r["days"]} ימים', remind=True)
                      for r in [r for r in snap.get('waiting', []) if triage_key(r) not in handled][:20]) or '<li class="muted">אין — הכול נענה ✨</li>'
    def when(left):
        return 'היום!' if left == 0 else 'מחר' if left == 1 else f'בעוד {left} ימים' if left > 0 else f'עבר לפני {-left} ימים'
    payments = ''.join(
        f'<li dir="auto" style="{"color:var(--bad);font-weight:500" if p["left"] <= 2 else ""}">'
        + (f'<a href="{e(p["link"])}" target="_blank">{e(p["subject"][:55])}</a>' if p.get('link') else e(p['subject'][:55]))
        + f' <span class="muted">— {e(p["from"])}{f" · {e(p["amount"])}" if p.get("amount") else ""} · עד {p["due"][8:10]}/{p["due"][5:7]} ({when(p["left"])})</span></li>'
        for p in upcoming_payments() if mine(p, current=box)) or '<li class="muted">אין תשלומים עם תאריך יעד בשבועיים הקרובים</li>'
    vac = vacation_active()
    vacation_note = (f'<div class="item urgent">🏖️ מצב חופשה פעיל עד {vac["to"][8:10]}/{vac["to"][5:7]} — מי שכותב/ת מקבל/ת מענה אוטומטי.</div>'
                     if vac else '')
    reminders = ''.join(
        f'<li dir="auto">{e(r["subject"][:60])} <span class="muted">— {e(r["from"])} · {dt.datetime.fromisoformat(r["due"]):%d/%m %H:%M}</span>'
        f'<form method="post" action="/reminder_delete" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
        f'<input type="hidden" name="id" value="{e(r["id"])}"><button style="font:inherit;font-size:12px;padding:0 6px;margin:0 4px;border:0;background:transparent;color:var(--muted);cursor:pointer">✕</button></form></li>'
        for r in sorted((r for r in load_json(config.REMINDERS_FILE, []) if mine(r, current=box)), key=lambda r: r['due'])[:8]) or '<li class="muted">אין תזכורות</li>'
    urgent = ''.join(mail_row(r, e(r['why'])) for r in snap.get('urgent', [])[:6]) or '<li class="muted">אין משהו דחוף</li>'

    added = set(load_json(config.CACHE_FILE, {}).get('invites_added', []))
    def invite_row(i):
        title = f'<a href="{e(i["link"])}" target="_blank">{e(i["title"][:70])}</a>' if i.get('link') else e(i['title'][:70])
        if invite_key(i) in added:
            action = '<span style="color:var(--good);font-size:13px;margin:0 4px">✓ ביומן</span>'
        elif gapps:
            action = (f'<form method="post" action="/invite_add" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                      f'<input type="hidden" name="key" value="{e(invite_key(i))}"><button style="{SMALL}">📅 הוספה ליומן</button></form>')
        else:
            action = ''
        return (f'<li dir="auto">{title}{action}<div class="muted" style="font-size:13px">{e(when_text(i))}'
                + (f' · 📍 {e(i["where"][:50])}' if i.get('where') else '') + f' · מאת {e(i["from"])}</div></li>')
    invites = [i for i in snap.get('invites', []) if upcoming(i)]
    invites_card = card('📨 הזמנות לפגישות', f'<ul style="margin:0;padding-inline-start:18px">{"".join(invite_row(i) for i in invites[:6])}</ul>'
                        + ('' if gapps else '<div class="muted" style="font-size:12px;margin-top:6px">חיבור היומן בדף ההגדרות = הוספה בלחיצה</div>')) if invites else ''

    def awaiting_row(r):
        title = f'<a href="{e(r["link"])}" target="_blank">{e(r["subject"][:60])}</a>' if r.get('link') else e(r['subject'][:60])
        hidden = lambda k, v: f'<input type="hidden" name="{k}" value="{e(str(v))}">'
        remind = (f'<form method="post" action="/remind" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                  + hidden('subject', 'לבדוק מול ' + r['to'] + ': ' + r['subject'][:120]) + hidden('from', r['to'])
                  + hidden('link', r.get('link', '')) + hidden('account', r['account']) + hidden('days', 1)
                  + f'<button style="{SMALL}">⏰ מחר</button></form>')
        task = (f'<form method="post" action="/gtask_add" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                + hidden('title', 'להזכיר ל-' + r['to'] + ': ' + r['subject'][:120]) + hidden('from', r['to'])
                + hidden('link', r.get('link', '')) + f'<button style="{SMALL}">✅ משימה</button></form>') if gapps else ''
        return (f'<li dir="auto" data-days="{r["days"]}" data-name="{e(r["to"])}" data-account="{e(r.get("account", ""))}">'
                f'{dot(r.get("account", ""))}{title} <span class="muted">— אל {e(r["to"])} · 📤 {r["days"]} ימים</span>{remind}{task}</li>')
    awaiting = ''.join(awaiting_row(r) for r in [r for r in snap.get('awaiting', []) if triage_key(r) not in handled][:20]) \
        or '<li class="muted">כולם ענו לך ✨</li>'

    expected = [f'<li dir="auto" style="color:var(--bad)">📈 {e(price_change_text(c))}</li>' for c in price_changes(load_json(config.LEDGER_FILE, {}))[:3]]
    gaps = missing_invoices()
    owed = [d for d in debts() if d['status'] == 'open' and d['due'] <= dt.date.today().isoformat()]
    soon_dates = upcoming_dates(days=7)
    for s in find_subscriptions(load_json(config.LEDGER_FILE, {})):
        nxt = dt.date.fromisoformat(s['last']) + dt.timedelta(days=30)
        if -3 <= (nxt - now.date()).days <= 10:
            expected.append(f'<li dir="auto">{e(s["vendor"])} — בערך {nxt:%d/%m}'
                            f'{f" · {e(s["currency"])}{s["amount"]}" if s["amount"] is not None else ""}</li>')

    projects = project_pulse()
    dirty = ''.join(f'<li><span dir="ltr">{e(p["name"])}</span> — {p["dirty"]} קבצים לא שמורים <span class="muted">({e(p["branch"])})</span></li>'
                    for p in sorted(projects, key=lambda p: -p['dirty']) if p['dirty']) or ('<li class="muted">כל הפרויקטים נקיים ✓</li>' if projects_root() else
                                         '<li class="muted">לא הוגדרה תיקיית פרויקטים — אפשר להגדיר בדף ההגדרות</li>')
    recent = sorted((p for p in projects if p['last']), key=lambda p: p['last'], reverse=True)[:1]

    fortune = FORTUNES[now.timetuple().tm_yday % len(FORTUNES)]
    fortune = g(*fortune) if isinstance(fortune, tuple) else fortune
    notes = load_json(config.NOTES_FILE, {}).get('text', '')
    options = ''.join(f'<option{" selected" if c == city else ""}>{e(c)}</option>' for c in CITIES)

    return page('היום שלי', f'''
<h1>היום שלי <span class="floaty">☀️</span></h1>
<p style="font-size:19px;margin:4px 0">יום {days[now.weekday()]}, {now:%d/%m/%Y}{f" · {e(heb)}" if heb else ""}{f" · פרשת {e(parasha.replace('פרשת ', ''))}" if parasha else ""}</p>
<p class="muted" style="font-style:italic">🥠 {e(fortune)}</p>{update_banner()}{vacation_note}{f'<div class="item urgent">{e(msg)}</div>' if msg else ''}
{quick_bar}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:18px">
{card(f"🌤️ מזג האוויר ב{e(city)}", f'<div>{weather}</div><form method="post" action="/set_city" style="margin-top:8px"><input type="hidden" name="t" value="{TOKEN}"><select name="city" onchange="this.form.submit()" style="font:inherit;padding:6px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">{options}</select></form>')}
{card("🕯️ שבת וחג", f'<ul style="margin:0;padding-inline-start:18px">{times or "<li class=muted>—</li>"}</ul><div style="font-size:13px;margin-top:6px">{e(holy_status())}</div><div class="muted" style="margin-top:8px;font-size:14px">בקרוב:</div><ul style="margin:0;padding-inline-start:18px;font-size:14px">{holidays or "<li class=muted>אין חגים בשלושת השבועות הקרובים</li>"}</ul>')}
{calendar_card if want('calendar') else ''}{tasks_card if want('calendar') else ''}
{card("🔥 דחוף במייל", f'<ul style="margin:0;padding-inline-start:18px">{urgent}</ul>')}
{card("⏳ מחכים לתשובה ממך" + SORTER.format(list='list-waiting'), f'<ul id="list-waiting" class="sortable">{waiting}</ul>') if want('replies') else ''}
{snoozed_card}
{card("📤 מחכה לתשובה מהם" + SORTER.format(list='list-awaiting'), f'<ul id="list-awaiting" class="sortable">{awaiting}</ul>') if want('replies') else ''}{invites_card if want('calendar') else ''}
{card("💸 תשלומים קרובים", f'<ul style="margin:0;padding-inline-start:18px">{payments}</ul>') if want('money') else ''}
{card("⏰ תזכורות", f'<ul style="margin:0;padding-inline-start:18px">{reminders}</ul>') if want('focus', 'replies') else ''}
{card("🧾 חשבוניות שלא הגיעו", '<ul style="margin:0;padding-inline-start:18px">' + ''.join(f'<li dir="auto">{e(m["vendor"])} <span class="muted">— בדרך כלל עד ה-{m["day"]}</span></li>' for m in gaps[:4]) + '</ul><a href="/?s=money#missing" style="font-size:13px">הכול ←</a>') if want('money') and gaps else ''}
{card("💰 לקוחות שלא שילמו", '<ul style="margin:0;padding-inline-start:18px">' + ''.join(f'<li dir="auto">{e(d["name"])} {e(d["amount"])} <span class="muted">— מ-{e(d["due"][8:10])}/{e(d["due"][5:7])}, {len(d["reminders"])} תזכורות</span></li>' for d in owed[:4]) + '</ul><a href="/?s=clients#debts" style="font-size:13px">מעקב תשלומים ←</a>') if want('money') and owed else ''}
{card("🎂 ימים מיוחדים של לקוחות", '<ul style="margin:0;padding-inline-start:18px">' + ''.join(f'<li dir="auto">{DATE_KINDS[d["kind"]][0]} {e(d["name"])} <span class="muted">— {"היום! הברכה יוצאת לבד" if d["date"] == dt.date.today() else f"{d["date"]:%d/%m}"}</span></li>' for d in soon_dates[:4]) + '</ul>') if soon_dates else ''}
{card("💳 חיובים צפויים", f'<ul style="margin:0;padding-inline-start:18px">{"".join(expected) or "<li class=muted>אין חיובים קבועים בעשרת הימים הקרובים</li>"}</ul>') if want('money') else ''}
{card("⏱️ טיימר ריכוז", FOCUS) if want('focus') else ''}
{card("🗒️ פתקים", f'<textarea class="notes" id="mb-notes" placeholder="מה צריך לזכור היום? נשמר לבד…">{e(notes)}</textarea>'
      f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px"><span class="muted" style="font-size:12px">נשמר במחשב שלך</span>'
      f'<span class="saved" id="mb-saved">✓ נשמר</span></div>' + NOTES_JS.replace('__TOKEN__', TOKEN)) if want('focus') or notes else ''}
{card("💻 פרויקטים", f'<ul style="margin:0;padding-inline-start:18px">{dirty}</ul>' + (f'<div class="muted" style="font-size:13px;margin-top:6px">הכי פעיל: <span dir="ltr">{e(recent[0]["name"])}</span> ({e(recent[0]["last"])})</div>' if recent else ''))}
</div>
<p style="text-align:center;margin-top:18px">{'<a href="/today">🎯 רק מה שחשוב לי</a>' if show_all else
 '<a href="/today?all=1">✨ להציג הכול</a> <span class="muted" style="font-size:13px">· מה מוצג — בהגדרות ← 👤 הפרופיל שלי</span>'}</p>
<p class="muted" style="margin-top:24px;font-size:13px">נתוני המייל מהבדיקה האחרונה ({e(snap.get("at", "עוד לא רצה"))}) ·
<a href="/insights">🔎 30 הימים שלך</a> · <a href="/search">🔍 חיפוש</a> · <a href="/dashboard">📊 לוח בקרה</a> · <a href="/">⚙️ הגדרות</a></p>''')
