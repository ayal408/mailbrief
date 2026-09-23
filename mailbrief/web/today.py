"""The "My day" page."""
import datetime as dt

from mailbrief import config
from mailbrief import net
from mailbrief.features.alerts import upcoming_payments
from mailbrief.features.calendar import CITIES, holy_status
from mailbrief.features.replies import reply_templates, vacation_active
from mailbrief.features.today import FORTUNES, project_pulse, projects_root, WEATHER
from mailbrief.money.ledger import find_subscriptions
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import page
from mailbrief.web.token import TOKEN


def today_page():
    now = dt.datetime.now()
    city = load_json(config.SETTINGS_FILE, {}).get('city', 'ירושלים')
    lat, lon = CITIES.get(city, CITIES['ירושלים'])
    hour = now.hour
    greet = 'לילה טוב' if hour < 5 else 'בוקר טוב' if hour < 12 else 'צהריים טובים' if hour < 17 else 'ערב טוב' if hour < 21 else 'לילה טוב'
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

    snap = load_json(config.SNAPSHOT_FILE, {})
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
        return f'<li dir="auto">{title} <span class="muted">— {e(r["from"])} · {tail}</span>{button}</li>'
    waiting = ''.join(mail_row(r, f'⏳ {r["days"]} ימים', remind=True) for r in snap.get('waiting', [])[:8]) or '<li class="muted">אין — הכול נענה ✨</li>'
    def when(left):
        return 'היום!' if left == 0 else 'מחר' if left == 1 else f'בעוד {left} ימים' if left > 0 else f'עבר לפני {-left} ימים'
    payments = ''.join(
        f'<li dir="auto" style="{"color:var(--bad);font-weight:500" if p["left"] <= 2 else ""}">'
        + (f'<a href="{e(p["link"])}" target="_blank">{e(p["subject"][:55])}</a>' if p.get('link') else e(p['subject'][:55]))
        + f' <span class="muted">— {e(p["from"])}{f" · {e(p["amount"])}" if p.get("amount") else ""} · עד {p["due"][8:10]}/{p["due"][5:7]} ({when(p["left"])})</span></li>'
        for p in upcoming_payments()) or '<li class="muted">אין תשלומים עם תאריך יעד בשבועיים הקרובים</li>'
    vac = vacation_active()
    vacation_note = (f'<div class="item urgent">🏖️ מצב חופשה פעיל עד {vac["to"][8:10]}/{vac["to"][5:7]} — מי שכותב/ת מקבל/ת מענה אוטומטי.</div>'
                     if vac else '')
    reminders = ''.join(
        f'<li dir="auto">{e(r["subject"][:60])} <span class="muted">— {e(r["from"])} · {dt.datetime.fromisoformat(r["due"]):%d/%m %H:%M}</span>'
        f'<form method="post" action="/reminder_delete" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
        f'<input type="hidden" name="id" value="{e(r["id"])}"><button style="font:inherit;font-size:12px;padding:0 6px;margin:0 4px;border:0;background:transparent;color:var(--muted);cursor:pointer">✕</button></form></li>'
        for r in sorted(load_json(config.REMINDERS_FILE, []), key=lambda r: r['due'])[:8]) or '<li class="muted">אין תזכורות</li>'
    urgent = ''.join(mail_row(r, e(r['why'])) for r in snap.get('urgent', [])[:6]) or '<li class="muted">אין משהו דחוף</li>'

    upcoming = []
    for s in find_subscriptions(load_json(config.LEDGER_FILE, {})):
        nxt = dt.date.fromisoformat(s['last']) + dt.timedelta(days=30)
        if -3 <= (nxt - now.date()).days <= 10:
            upcoming.append(f'<li dir="auto">{e(s["vendor"])} — בערך {nxt:%d/%m}'
                            f'{f" · {e(s["currency"])}{s["amount"]}" if s["amount"] is not None else ""}</li>')

    projects = project_pulse()
    dirty = ''.join(f'<li><span dir="ltr">{e(p["name"])}</span> — {p["dirty"]} קבצים לא שמורים <span class="muted">({e(p["branch"])})</span></li>'
                    for p in sorted(projects, key=lambda p: -p['dirty']) if p['dirty']) or ('<li class="muted">כל הפרויקטים נקיים ✓</li>' if projects_root() else
                                         '<li class="muted">לא הוגדרה תיקיית פרויקטים — אפשר להגדיר בדף ההגדרות</li>')
    recent = sorted((p for p in projects if p['last']), key=lambda p: p['last'], reverse=True)[:1]

    fortune = FORTUNES[now.timetuple().tm_yday % len(FORTUNES)]
    options = ''.join(f'<option{" selected" if c == city else ""}>{e(c)}</option>' for c in CITIES)
    card = lambda title, body: f'<div class="box" style="background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:16px 18px"><h3 style="margin:0 0 8px">{title}</h3>{body}</div>'

    return page('היום שלי', f'''
<h1>{greet} ☀️</h1>
<p style="font-size:19px;margin:4px 0">יום {days[now.weekday()]}, {now:%d/%m/%Y}{f" · {e(heb)}" if heb else ""}{f" · פרשת {e(parasha.replace('פרשת ', ''))}" if parasha else ""}</p>
<p class="muted" style="font-style:italic">🥠 {e(fortune)}</p>{vacation_note}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:18px">
{card(f"🌤️ מזג האוויר ב{e(city)}", f'<div>{weather}</div><form method="post" action="/set_city" style="margin-top:8px"><input type="hidden" name="t" value="{TOKEN}"><select name="city" onchange="this.form.submit()" style="font:inherit;padding:6px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">{options}</select></form>')}
{card("🕯️ שבת וחג", f'<ul style="margin:0;padding-inline-start:18px">{times or "<li class=muted>—</li>"}</ul><div style="font-size:13px;margin-top:6px">{e(holy_status())}</div><div class="muted" style="margin-top:8px;font-size:14px">בקרוב:</div><ul style="margin:0;padding-inline-start:18px;font-size:14px">{holidays or "<li class=muted>אין חגים בשלושת השבועות הקרובים</li>"}</ul>')}
{card("🔥 דחוף במייל", f'<ul style="margin:0;padding-inline-start:18px">{urgent}</ul>')}
{card("⏳ מחכים לתשובה ממך", f'<ul style="margin:0;padding-inline-start:18px">{waiting}</ul>')}
{card("💸 תשלומים קרובים", f'<ul style="margin:0;padding-inline-start:18px">{payments}</ul>')}
{card("⏰ תזכורות", f'<ul style="margin:0;padding-inline-start:18px">{reminders}</ul>')}
{card("💳 חיובים צפויים", f'<ul style="margin:0;padding-inline-start:18px">{"".join(upcoming) or "<li class=muted>אין חיובים קבועים בעשרת הימים הקרובים</li>"}</ul>')}
{card("💻 פרויקטים", f'<ul style="margin:0;padding-inline-start:18px">{dirty}</ul>' + (f'<div class="muted" style="font-size:13px;margin-top:6px">הכי פעיל: <span dir="ltr">{e(recent[0]["name"])}</span> ({e(recent[0]["last"])})</div>' if recent else ''))}
</div>
<p class="muted" style="margin-top:24px;font-size:13px">נתוני המייל מהבדיקה האחרונה ({e(snap.get("at", "עוד לא רצה"))}) ·
<a href="/search">🔍 חיפוש</a> · <a href="/dashboard">📊 לוח בקרה</a> · <a href="/">⚙️ הגדרות</a></p>''')
