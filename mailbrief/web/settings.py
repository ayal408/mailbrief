"""The main settings page."""
import os
from urllib.parse import quote

from mailbrief import config
from mailbrief.features.calendar import holy_status, paused_until
from mailbrief.features.google_apps import API_PAGES, gapps_account
from mailbrief.features.maintenance import schedule_status
from mailbrief.features.replies import reply_templates, vacation_active, VACATION_DEFAULT
from mailbrief.mail.classify import TAG_PREFIX
from mailbrief.mail.oauth import PROVIDERS, bundled_client
from mailbrief.profile import FORMS, g, GOALS, goals, profile
from mailbrief.features.daily import daily_cfg
from mailbrief.features import migrate
from mailbrief import view
from mailbrief.money.accountant import accountant_cfg, previous_month
import datetime as dt
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web import extras
from mailbrief.web.layout import FONT, STYLE, top_bar, update_banner
from mailbrief.web.token import TOKEN


FIELD_NAMES = {'from': 'השולח', 'subject': 'הנושא', 'any': 'השולח, הנושא או התוכן'}


def gapps_section():
    accounts = load_json(config.ACCOUNTS_FILE, [])
    google = [a for a in accounts if a.get('auth') == 'google']
    current = gapps_account(accounts)
    if not google:
        body = '<p class="muted">קודם צריך לחבר תיבת Gmail עם „🔵 חיבור עם Google” — ואז לחזור לכאן.</p>'
    else:
        rows = ''.join(
            f'<tr><td dir="ltr" style="text-align:right">{e(a["email"])}</td><td>'
            + ((('<b style="color:var(--good)">✓ מחובר</b>' + (' · מוצג ב„היום שלי”' if current and current['id'] == a['id'] else
                f'<form method="post" action="/gapps_choose" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                f'<input type="hidden" name="email" value="{e(a["email"])}"><button class="ghost" style="margin:0 6px">להציג את זה</button></form>'))
                if a.get('gapps') else '<span class="muted">לא מחובר</span>'))
            + f'</td><td><form method="post" style="margin:0"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="id" value="{e(a["id"])}">'
            + ('<button formaction="/gapps_disconnect" class="ghost" style="margin:0">ניתוק</button>' if a.get('gapps') else
               '<button formaction="/gapps_connect" style="margin:0">📅 חיבור יומן ומשימות</button>')
            + '</form></td></tr>' for a in google)
        body = f'<div class="scroll"><table><tbody>{rows}</tbody></table></div>'
    return f'''
<h2 id="gapps" style="direction:rtl;text-align:right;scroll-margin-top:80px">📅 Google Calendar ו-Tasks</h2>
<p class="muted">האירועים של היום והמשימות הפתוחות מופיעים ב„היום שלי” — עם הוספה מהירה וסימון „בוצע”.
ליד כל מייל שמחכה לתשובה יש „✅ משימה”, ובאוטומציות יש שתי פעולות חדשות: „✅ משימה ב-Google Tasks” ו„📅 אירוע ב-Google Calendar”
(אם במייל יש תאריך תשלום — זה התאריך). כמו כל האוטומציות, לא רץ בשבת ובחג.</p>
{body}
<details {'' if current else 'open'}><summary><b>⚙️ פעם אחת לפני החיבור: להפעיל שני ממשקים בפרויקט (כדקה)</b></summary>
<ol style="font-size:14px;padding-inline-start:20px">
<li>לפתוח את <a href="{API_PAGES['calendar']}" target="_blank">Google Calendar API</a> ← לוודא שלמעלה נבחר הפרויקט MailBrief ← <b>Enable</b></li>
<li>לפתוח את <a href="{API_PAGES['tasks']}" target="_blank">Google Tasks API</a> ← <b>Enable</b></li>
<li>ללחוץ כאן „📅 חיבור יומן ומשימות”, לבחור את החשבון, ו<b>לסמן את שתי תיבות הסימון</b> (יומן ומשימות) בחלון של Google</li></ol>
<p class="muted" style="font-size:13px">ההרשאה היא רק לאירועים ולמשימות — לא להגדרות היומן ולא לשיתופים. הכול נשמר מוצפן במחשב שלך כמו הרשאת המייל.</p></details>'''


def extra_sections():
    rules = load_json(config.RULES_FILE, [])
    rows = ''.join(
        f'<tr><td>{FIELD_NAMES.get(r["field"], r["field"])} מכיל <b dir="auto">„{e(r["contains"])}”</b></td>'
        f'<td>🏷️ {e(r["label"])}{" 🔔" if r.get("notify") else ""}'
        + (f'<div style="font-size:13px">↪️ מועבר אל <span dir="ltr">{e(r["forward_to"])}</span></div>' if r.get('forward_to') else '') + '</td>'
        f'<td><form method="post" action="/rule_delete" style="margin:0"><input type="hidden" name="t" value="{TOKEN}">'
        f'<input type="hidden" name="id" value="{e(r["id"])}"><button class="ghost" style="margin:0">מחיקה</button></form></td></tr>'
        for r in rules) or '<tr><td colspan="3" class="muted">עוד אין כללים</td></tr>'
    options = ''.join(f'<option value="{k}">{v}</option>' for k, v in FIELD_NAMES.items())
    forward_rows = ''.join(
        f'<tr><td>{e(f["at"])}</td><td dir="auto">{e(f["subject"][:60])}</td><td dir="ltr">→ {e(f["to"])}</td><td>'
        + ('<span style="color:var(--good)">✓ נשלח</span>' if f.get('ok') else f'<span style="color:var(--bad)">⚠️ {e(f.get("error", ""))}</span>')
        + '</td></tr>' for f in reversed(load_json(config.FORWARD_LOG, [])[-10:])) or '<tr><td class="muted">עוד לא הועבר כלום</td></tr>'

    vac = load_json(config.SETTINGS_FILE, {}).get('vacation') or {}
    active = vacation_active()
    field = 'font:inherit;padding:8px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)'
    vacation_html = f'''
<h2 id="vacation" style="direction:rtl;text-align:right;scroll-margin-top:80px">🏖️ מצב חופשה</h2>
<p class="muted">{'<b style="color:var(--good)">פעיל עכשיו</b> — ' if active else ''}בין התאריכים, מי שכותב לך אישית מקבל מענה אוטומטי — פעם אחת לכל אדם בכל החופשה.
לא לרשימות תפוצה, לא לשולחים אוטומטיים, ולא בשבת ובחג. המשתנה <span dir="ltr">{{to}}</span> = היום שחוזרים.</p>
<form method="post" action="/vacation" class="box" style="display:grid;gap:8px"><input type="hidden" name="t" value="{TOKEN}">
<div style="display:flex;gap:10px;flex-wrap:wrap"><label style="margin:0">מתאריך <input type="date" name="from" value="{e(vac.get('from', ''))}" style="{field}"></label>
<label style="margin:0">עד תאריך <input type="date" name="to" value="{e(vac.get('to', ''))}" style="{field}"></label></div>
<textarea name="message" rows="4" style="{field}">{e(vac.get('message') or VACATION_DEFAULT)}</textarea>
<div><button name="action" value="save" style="margin:0">שמירה</button> <button name="action" value="off" class="ghost" style="margin:0">כיבוי</button></div></form>'''
    tmpl_rows = ''.join(
        f'<tr><td><b>{e(t["name"])}</b><div class="muted" style="font-size:13px;white-space:pre-line">{e(t["text"])}</div></td>'
        f'<td><form method="post" action="/template_delete" style="margin:0"><input type="hidden" name="t" value="{TOKEN}">'
        f'<input type="hidden" name="id" value="{e(t["id"])}"><button class="ghost" style="margin:0">מחיקה</button></form></td></tr>'
        for t in reply_templates())
    templates_html = f'''
<h2 id="templates" style="direction:rtl;text-align:right;scroll-margin-top:80px">📝 תבניות תשובה</h2>
<p class="muted">ב„היום שלי”, ליד כל מייל שמחכה לתשובה: בוחרים תבנית ← „📝 טיוטה” — ונוצרת טיוטה מוכנה ב-Gmail לעריכה ושליחה.</p>
<div class="scroll"><table><tbody>{tmpl_rows}</tbody></table></div>
<form method="post" action="/template_add" class="box" style="display:grid;gap:8px;margin-top:10px"><input type="hidden" name="t" value="{TOKEN}">
<input type="text" name="name" required maxlength="40" placeholder="שם התבנית" style="{field}">
<textarea name="text" rows="3" required placeholder="שלום {{from_name}}, ..." style="{field}"></textarea>
<div><button style="margin:0">➕ הוספת תבנית</button></div></form>'''
    root = load_json(config.SETTINGS_FILE, {}).get('projects_root', '')
    projects_html = f'''
<h2 style="direction:rtl;text-align:right">💻 תיקיית פרויקטים</h2>
<p class="muted">„היום שלי” מציג פרויקטי git בתיקייה הזו שיש בהם שינויים שלא נשמרו. ריק = בלי כרטיס פרויקטים.</p>
<form method="post" action="/projects_root" style="display:flex;gap:8px;flex-wrap:wrap"><input type="hidden" name="t" value="{TOKEN}">
<input type="text" name="root" dir="ltr" value="{e(root)}" placeholder="C:/projects" style="flex:1;min-width:220px;{field}">
<button style="margin:0">שמירה</button></form>'''
    me = profile()
    form_opts = ''.join(f'<option value="{k}"{" selected" if k == me.get("form") else ""}>{icon} {label}</option>' for k, (icon, label) in FORMS.items())
    profile_html = f'''
<h2 id="profile" style="direction:rtl;text-align:right;scroll-margin-top:80px">👤 הפרופיל שלי</h2>
<p class="muted">השם והלשון שבהם MailBrief פונה — בברכה, בהודעות ובטיפים.</p>
<form method="post" action="/profile" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><input type="hidden" name="t" value="{TOKEN}">
<input type="text" name="name" value="{e(me.get('name', ''))}" maxlength="30" placeholder="השם שלך" style="flex:1;min-width:160px;{field}">
<select name="form" style="{field}">{form_opts}</select><button style="margin:0">שמירה</button>
<div style="flex-basis:100%;display:flex;gap:6px;flex-wrap:wrap;margin-top:4px"><span class="muted">מה מוצג ב„היום שלי”:</span>
{''.join(f'<label style="font-weight:400;margin:0;display:inline-flex;gap:4px;align-items:center;border:1px solid var(--line);border-radius:999px;padding:4px 10px">'
         f'<input type="checkbox" name="goal" value="{k}"{" checked" if k in goals() else ""}> {icon} {e(title)}</label>' for k, (icon, title, _) in GOALS.items())}
</div></form>'''
    daily = daily_cfg()
    accounts = load_json(config.ACCOUNTS_FILE, [])
    acc_opts = ''.join(f'<option{" selected" if a["email"] == daily["account"] else ""}>{e(a["email"])}</option>' for a in accounts)
    hour_opts = ''.join(f'<option value="{h}"{" selected" if h == daily["hour"] else ""}>{h:02d}:00</option>' for h in range(5, 23))
    daily_html = f'''
<h2 id="daily" style="direction:rtl;text-align:right;scroll-margin-top:80px">✉️ סיכום יומי במייל</h2>
<p class="muted">{'<b style="color:var(--good)">פעיל</b> — ' if daily['on'] else ''}כל בוקר מגיע לתיבה שלך מייל קצר: מה דחוף, מה ביומן, מה לתשלום ומי מחכה לתשובה.
נוח לקרוא בטלפון — גם בלי שהמחשב מולך. לא נשלח בשבת ובחג.</p>
<form method="post" action="/daily" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><input type="hidden" name="t" value="{TOKEN}">
<span>לשלוח ל</span><select name="account" style="{field}">{acc_opts or '<option value="">(אין תיבה)</option>'}</select>
<span>בשעה</span><select name="hour" style="{field}">{hour_opts}</select>
<button name="action" value="on" style="margin:0">{'שמירה' if daily['on'] else '✅ הפעלה'}</button>
{'<button name="action" value="off" class="ghost" style="margin:0">כיבוי</button>' if daily['on'] else ''}
<button formaction="/daily_test" class="ghost" style="margin:0">📨 לשלוח עכשיו לניסיון</button></form>'''
    acct = accountant_cfg()
    acct_accounts = ''.join(f'<option{" selected" if a["email"] == acct["account"] else ""}>{e(a["email"])}</option>' for a in accounts)
    this_year = dt.date.today().year
    accountant_html = f'''
<h2 id="accountant" style="direction:rtl;text-align:right;scroll-margin-top:80px">🧾 לרואה החשבון</h2>
<p class="muted">{'<b style="color:var(--good)">פעיל</b> — ' if acct['on'] else ''}בכל חודש, ביום שבוחרים: קובץ ZIP עם האקסל של החודש הקודם
ועם כל הקבלות והחשבוניות — נשלח לרו״ח מהתיבה שלך (לא בשבת ובחג). אפשר גם להכין ידנית.</p>
<form method="post" action="/accountant" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><input type="hidden" name="t" value="{TOKEN}">
<input type="email" name="email" value="{e(acct['email'])}" placeholder="cpa@example.co.il" dir="ltr" style="flex:1;min-width:200px;{field}">
<input type="text" name="name" value="{e(acct['name'])}" placeholder="שם הרו״ח (לפתיחת המייל)" style="min-width:160px;{field}">
<span>ב-</span><input type="number" name="day" min="1" max="28" value="{acct['day']}" style="width:70px;{field}"><span>לחודש, מ-</span>
<select name="account" style="{field}">{acct_accounts or '<option value="">(אין תיבה)</option>'}</select>
<button name="action" value="on" style="margin:0">{'שמירה' if acct['on'] else '✅ הפעלה'}</button>
{'<button name="action" value="off" class="ghost" style="margin:0">כיבוי</button>' if acct['on'] else ''}</form>
<form method="post" action="/accountant_package" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px"><input type="hidden" name="t" value="{TOKEN}">
<input type="month" name="month" value="{previous_month()}" style="{field}">
<button name="action" value="zip" class="ghost" style="margin:0">📦 להכין חבילה</button>
<button name="action" value="send" class="ghost" style="margin:0">📨 לשלוח עכשיו לרו״ח</button></form>
<form method="post" action="/yearly" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px"><input type="hidden" name="t" value="{TOKEN}">
<span class="muted">סיכום שנתי לפי סיווג וספק (לדוח השנתי):</span>
<select name="year" style="{field}">{''.join(f'<option>{y}</option>' for y in range(this_year, this_year - 4, -1))}</select>
<button class="ghost" style="margin:0">📊 להכין סיכום שנתי</button></form>'''
    quiet = load_json(config.SETTINGS_FILE, {}).get('quiet') or {}
    hours = lambda chosen: ''.join(f'<option value="{h}"{" selected" if h == chosen else ""}>{h:02d}:00</option>' for h in range(24))
    quiet_html = f'''
<h2 id="quiet" style="direction:rtl;text-align:right;scroll-margin-top:80px">🔕 שעות שקטות</h2>
<p class="muted">{'<b style="color:var(--good)">פעיל</b> — ' if quiet.get('on') else ''}בשעות האלה לא קופצות התראות. שום דבר לא הולך לאיבוד — הכול מחכה ב„היום שלי”.</p>
<form method="post" action="/quiet" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><input type="hidden" name="t" value="{TOKEN}">
<span>מ-</span><select name="from" style="{field}">{hours(int(quiet.get('from', 22)))}</select>
<span>עד</span><select name="to" style="{field}">{hours(int(quiet.get('to', 7)))}</select>
<button name="action" value="on" style="margin:0">{'שמירה' if quiet.get('on') else '✅ הפעלה'}</button>
{'<button name="action" value="off" class="ghost" style="margin:0">כיבוי</button>' if quiet.get('on') else ''}</form>'''
    prev = migrate.previous_copy()
    prev_info = migrate.summary(prev) if prev else None
    migrate_html = f'''
<h2 id="migrate" style="direction:rtl;text-align:right;scroll-margin-top:80px">📦 העברת נתונים מעותק קודם</h2>
<p class="muted">עוברים למחשב חדש או לגרסה המותקנת? מעתיקים לכאן את התיבות, הקבלות, הארכיון, הכללים וההגדרות. מה שיש כאן עכשיו נשמר קודם בגיבוי.</p>
{f'<div class="item urgent">נמצא MailBrief קודם ב-<span dir="ltr">{e(prev)}</span> — {len(prev_info["accounts"])} תיבות, {prev_info["receipts"]} קבלות.</div>' if prev else ''}
<form method="post" action="/migrate" style="display:flex;gap:8px;flex-wrap:wrap"><input type="hidden" name="t" value="{TOKEN}">
<input type="text" name="folder" dir="ltr" value="{e(prev)}" placeholder="C:\\MailBrief" style="flex:1;min-width:240px;{field}">
<button style="margin:0">📦 להעביר לכאן</button></form>'''
    return profile_html + daily_html + accountant_html + quiet_html + gapps_section() + projects_html + vacation_html + templates_html + migrate_html + f'''
<h2 id="rules" style="direction:rtl;text-align:right;scroll-margin-top:80px">🏷️ הכללים שלי</h2>
<p class="muted">כל מייל שמתאים לכלל מקבל תווית משלו (תחת „{TAG_PREFIX}”) ומקבץ משלו בדוח. 🔔 = גם התראה ב-Windows.</p>
<div class="scroll"><table><tbody>{rows}</tbody></table></div>
<form method="post" action="/rule_add" class="box" style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;align-items:end">
<input type="hidden" name="t" value="{TOKEN}">
<div><label>אם</label><select name="field" style="width:100%;font:inherit;padding:10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">{options}</select></div>
<div><label>מכיל</label><input type="text" name="contains" required placeholder="למשל: @client.co.il"></div>
<div><label>תווית</label><input type="text" name="label" maxlength="40" placeholder="למשל: לקוח כהן"></div>
<div><label>↪️ העברה אל <span class="muted">(לא חובה)</span></label><input type="email" name="forward_to" dir="ltr" placeholder="accountant@example.com"></div>
<div><label style="font-weight:400"><input type="checkbox" name="notify"> 🔔 התראה</label><button>➕ הוספת כלל</button></div></form>
<p class="muted" style="font-size:13px">↪️ העברה: רק מיילים שמגיעים <b>אחרי</b> יצירת הכלל, כל מייל פעם אחת, עד {config.MAX_FORWARDS_PER_RUN} בריצה, עם כל הקבצים המצורפים.
הבדיקה רצה כל שעה בין 7:00 ל-23:00 (לא בשבת ובחג), כך שההעברה יוצאת תוך שעה בערך.</p>
<h3>↪️ העברות אחרונות</h3>
<div class="scroll"><table><tbody>{forward_rows}</tbody></table></div>
<form method="post" action="/test_send"><input type="hidden" name="t" value="{TOKEN}">
<button class="ghost">✉️ בדיקת שליחה (מייל ניסיון לעצמך)</button></form>

<h2 id="news" style="direction:rtl;text-align:right;scroll-margin-top:80px">📰 ניוזלטרים</h2>
<p class="muted">ביטול מנויים, רשימת קריאה וארכוב — עברו ללשונית משלהם: <a href="/reading">📰 ניוזלטרים ←</a></p>

<h2 style="direction:rtl;text-align:right">🔔 התראות Windows</h2>
<p class="muted">בדיקה קצרה כל שעה בין 7:00 ל-23:00 (לא בשבת ובחג). קופצת התראה רק על מייל דחוף, אירוע אבטחה חריג או כלל עם 🔔 — ורק פעם אחת לכל מייל.
<br>סטטוס: {e(schedule_status(config.ALERTS_TASK))}</p>
<form method="post" action="/setup" style="display:flex;gap:6px;flex-wrap:wrap"><input type="hidden" name="t" value="{TOKEN}">
<button name="action" value="install" class="ghost" style="margin:0">🔧 רישום / תיקון התזמונים</button>
<button name="action" value="remove" class="ghost" style="margin:0">הסרת התזמונים</button></form>
<p class="muted" style="font-size:13px">הנתונים נשמרים ב: <span dir="ltr">{e(config.HERE)}</span></p>
<form method="post"><input type="hidden" name="t" value="{TOKEN}">
<button formaction="/test_toast" class="ghost">הצגת התראת ניסיון</button> <button formaction="/check">בדיקה עכשיו</button></form>'''


def settings_page(msg=''):
    accounts = load_json(config.ACCOUNTS_FILE, [])
    oauth = load_json(config.SETTINGS_FILE, {})
    google_id = (oauth.get('google') or {}).get('client_id', '')
    ms_id = (oauth.get('microsoft') or {}).get('client_id', '')
    built_in = bool(bundled_client('google')[0])
    google_ready = bool(google_id and (oauth.get('google') or {}).get('client_secret')) or built_in
    ms_ready = bool(ms_id)
    cards = []
    for a in accounts:
        last = a.get('last') or {}
        status = ('<span style="color:var(--bad)">⚠️ ' + e(last['error']) + '</span>') if last.get('error') else (
            f'✓ ריצה אחרונה {e(last["at"])} · {last["count"]} הודעות · {last["tagged"]} תיוגים' if last else 'עוד לא רץ')
        cards.append(f'''<div class="item"><div class="t" dir="ltr" style="text-align:right">{e(a["email"])}</div>
          <div class="m" dir="ltr" style="text-align:right">{e(PROVIDERS[a["auth"]]["name"] + " sign-in" if a.get("auth") in PROVIDERS else a["host"])} · {"תיוג פעיל" if a.get("tag", True) else "בלי תיוג"}</div>
          <div class="s">{status}</div>
          <form method="post" style="display:inline"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="id" value="{e(a["id"])}">
          <button formaction="/test">בדיקת חיבור</button> <button formaction="/remove" class="ghost">הסרה</button></form>
          <form method="post" style="display:inline"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="only" value="{e(a["email"])}">
          <button formaction="/check" class="ghost" title="בדיקה מהירה של היומיים האחרונים — רק לתיבה הזו">🔄 בדיקה</button>
          <button formaction="/run" class="ghost" title="תדריך מלא לשבוע — רק לתיבה הזו">▶ תדריך לתיבה הזו</button></form></div>''')
    reports = sorted((f for f in os.listdir(config.REPORTS) if f.endswith('.html')), reverse=True)[:8] if os.path.isdir(config.REPORTS) else []
    rep = ''.join(f'<li><a href="/reports/{quote(f)}" target="_blank">{e(f[6:-5])}</a></li>' for f in reports) or '<li class="muted">אין עדיין</li>'
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    return f'''<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>תיבות והגדרות · MailBrief</title>{FONT}<style>{STYLE}
input[type=text],input[type=email],input[type=password],input[type=number]{{width:100%;font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}}
label{{display:block;margin:10px 0 4px;font-weight:500}} button{{font:inherit;font-weight:500;border:0;background:var(--accent);color:#fff;padding:9px 16px;border-radius:12px;cursor:pointer;margin-top:8px}}
button.ghost{{background:transparent;color:var(--ink);border:1px solid var(--line)}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}} .box{{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px}}
</style></head><body>{top_bar('/')}<main>
<h1>📬 <span class="g">תיבות והגדרות</span></h1><p class="muted">תדריך מייל שבועי שרץ מקומית על המחשב שלך, לכל תיבת דואר, בלי AI. התדריך השבועי: {e(schedule_status())}<br>{e(holy_status())}</p>{note}
{update_banner()}
{'<div class="item urgent">📦 נמצאו נתונים של MailBrief קודם — <a href="#migrate">להעביר אותם לכאן</a></div>' if migrate.previous_copy() else ''}
<form method="post" action="/pause" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:8px 0"><input type="hidden" name="t" value="{TOKEN}">
{f'<b style="color:var(--warn)">⏸️ מושהה עד {paused_until():%d/%m %H:%M}</b><button name="mode" value="off" style="margin:0">▶️ ביטול השהיה</button>' if paused_until() else
 '<span class="muted">⏸️ השהיית אוטומציות והתראות:</span><button name="mode" value="2h" class="ghost" style="margin:0">לשעתיים</button><button name="mode" value="tomorrow" class="ghost" style="margin:0">עד מחר בבוקר</button>'}</form>
<form method="get" action="/search" style="display:flex;gap:8px;margin:16px 0"><input type="text" name="q" placeholder="🔍 חיפוש בכל התיבות..." style="flex:1">
<button style="margin:0">חיפוש</button></form>
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px"><input type="hidden" name="t" value="{TOKEN}">
<button formaction="/open_archive" class="ghost" style="margin:0">🗄️ ארכיון מקומי</button>
<button formaction="/archive_backfill" class="ghost" style="margin:0" title="שומר במחשב קבלות ומיילים אישיים מ-90 הימים האחרונים">🗄️ גיבוי 90 יום</button>
<button formaction="/open_receipts" class="ghost" style="margin:0">📂 תיקיית הקבלות והאקסל</button>
<button formaction="/import_receipts" class="ghost" style="margin:0" title="סורק 90 ימים אחורה, שומר קבלות ובונה את האקסל החודשי">⬇️ ייבוא קבלות מ-90 הימים האחרונים</button></form>
<div class="grid"><section>
<h3>התיבות שלי</h3>{"".join(cards) or '<p class="muted">עוד לא הוספת תיבה.</p>'}
<form method="post" action="/run"><input type="hidden" name="t" value="{TOKEN}"><button>▶ הרצה עכשיו{' — ' + e(view.current_account()) if view.current_account() else (' — כל התיבות' if len(accounts) > 1 else '')}</button></form>
<h3>דוחות אחרונים</h3><ul>{rep}</ul></section>
<section class="box"><h3 style="margin-top:0">➕ חיבור תיבה</h3>
<p class="muted" style="margin-top:0">כמו „התחברות עם Google” באתרים: נפתח חלון התחברות, מאשרים — וזהו. בלי סיסמאות.</p>
<form method="post" action="/connect"><input type="hidden" name="t" value="{TOKEN}">
<button name="provider" value="google" {'' if google_ready else 'disabled title="קודם הגדרה חד-פעמית"'}>🔵 חיבור עם Google</button>
<button name="provider" value="microsoft" {'' if ms_ready else 'disabled title="קודם הגדרה חד-פעמית"'}>🟦 חיבור עם Microsoft</button></form>
{'<p class="muted" style="font-size:13px">אם Google מציג „Google hasn’t verified this app” — לוחצים <b>Advanced</b> ← <b>Go to MailBrief</b>. הגישה נשארת רק במחשב שלך: MailBrief לא שולח את המייל לשום שרת.</p>' if built_in and not google_id else ''}
<details {'' if google_ready else 'open'} style="margin-top:16px"><summary><b>⚙️ {'מפתח Google משלך (לא חובה)' if built_in else 'הגדרה חד-פעמית של Google'}</b> {'' if built_in else '✓' if google_ready else '(נדרש פעם אחת, כ-5 דקות)'}</summary>
{'<p class="muted" style="font-size:13px">ל-MailBrief יש מפתח מובנה, אז אין צורך בזה. רק למי שרוצה להשתמש בפרויקט Google Cloud משלו:</p>' if built_in else ''}
<ol style="font-size:14px;padding-inline-start:20px">
<li>ליצור פרויקט: <a href="https://console.cloud.google.com/projectcreate" target="_blank">console.cloud.google.com/projectcreate</a> — שם: MailBrief</li>
<li>להיכנס ל-<a href="https://console.cloud.google.com/auth/overview" target="_blank">Google Auth Platform</a> ← Get started: שם האפליקציה MailBrief, המייל שלך, Audience = External</li>
<li>ב-<b>Audience</b> ללחוץ <b>Publish app</b> (אחרת ההתחברות פגה כל 7 ימים)</li>
<li>ב-<b>Clients</b> ← Create client ← סוג <b>Desktop app</b> ← להעתיק לכאן את ה-Client ID וה-Client secret</li>
<li>בהתחברות Google יראה „האפליקציה לא אומתה” — זה תקין כי {g('את המפתחת', 'אתה המפתח', 'זו האפליקציה שלך')}: Advanced ← Go to MailBrief</li></ol>
<form method="post" action="/oauth_config"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="provider" value="google">
<label>Client ID</label><input type="text" name="client_id" dir="ltr" value="{e(google_id)}">
<label>Client secret</label><input type="password" name="client_secret" dir="ltr" placeholder="{'••••••• (שמור)' if (oauth.get('google') or {}).get('client_secret') else ''}">
<button>שמירה</button></form></details>
<details style="margin-top:12px"><summary><b>⚙️ הגדרה חד-פעמית של Microsoft</b> (Outlook / Hotmail / Office 365) {'✓' if ms_ready else ''}</summary>
<ol style="font-size:14px;padding-inline-start:20px">
<li><a href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade" target="_blank">Azure ← App registrations</a> ← New registration: שם MailBrief, סוג חשבונות „Any organizational directory and personal Microsoft accounts”</li>
<li>Redirect URI: פלטפורמה <b>Public client/native (mobile &amp; desktop)</b>, כתובת <code dir="ltr">http://localhost</code></li>
<li>API permissions ← Add ← Microsoft Graph ← Delegated ← <b>IMAP.AccessAsUser.All</b></li>
<li>להעתיק לכאן את ה-Application (client) ID</li></ol>
<form method="post" action="/oauth_config"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="provider" value="microsoft">
<label>Application (client) ID</label><input type="text" name="client_id" dir="ltr" value="{e(ms_id)}">
<button>שמירה</button></form></details>
<details style="margin-top:12px"><summary><b>✉️ תיבה אחרת עם סיסמה</b> (מייל של עבודה, ספקים ישראליים ועוד)</summary>
<form method="post" action="/add"><input type="hidden" name="t" value="{TOKEN}">
<label>כתובת מייל</label><input type="email" name="email" required dir="ltr">
<label>סיסמה</label><input type="password" name="password" required dir="ltr">
<label>שרת IMAP <span class="muted">(ריק = ניחוש אוטומטי)</span></label><input type="text" name="host" dir="ltr">
<label>פורט</label><input type="number" name="port" value="993" dir="ltr">
<label style="font-weight:400"><input type="checkbox" name="tag" checked> לתייק אוטומטית (העתק לתיקייה, המקור נשאר)</label>
<button>בדיקה ושמירה</button></form></details>
<p class="muted" style="font-size:13px;margin-top:16px">כל ההרשאות והסיסמאות נשמרות מוצפנות (Windows DPAPI) — רק המשתמש שלך במחשב הזה יכול לפענח אותן.
אפשר לבטל גישה בכל רגע ב-<a href="https://myaccount.google.com/connections" target="_blank">Google</a> או ב-<a href="https://account.live.com/consent/Manage" target="_blank">Microsoft</a>.</p>
</section></div>{extra_sections()}
<form method="post" action="/quit" style="margin-top:40px"><input type="hidden" name="t" value="{TOKEN}">
<button class="ghost">⏻ סגירת MailBrief</button> <span class="muted" style="font-size:13px">הריצות המתוזמנות ימשיכו לעבוד גם כשהוא סגור.</span></form>
</main>{extras.HTML}</body></html>'''
