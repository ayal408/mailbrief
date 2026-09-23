"""The main settings page."""
import os
from urllib.parse import quote

from mailbrief import config
from mailbrief.features.calendar import holy_status, paused_until
from mailbrief.features.maintenance import schedule_status
from mailbrief.features.notify import telegram_cfg
from mailbrief.features.replies import reply_templates, vacation_active, VACATION_DEFAULT
from mailbrief.mail.classify import TAG_PREFIX
from mailbrief.mail.oauth import PROVIDERS
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import FONT, STYLE
from mailbrief.web.token import TOKEN


FIELD_NAMES = {'from': 'השולח', 'subject': 'הנושא', 'any': 'השולח, הנושא או התוכן'}


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

    unsubs = load_json(config.UNSUBS_FILE, {})
    news = ''.join(
        f'<tr><td dir="auto">{e(u.get("name") or u["sender"])}<div class="muted" dir="ltr" style="font-size:12px;text-align:right">{e(u["sender"])} → {e(u["account"])}</div></td>'
        f'<td>{u.get("count", 0)}</td><td>'
        + (f'<span style="color:var(--good)">✓ בוטל {e(u["done"])}</span>' if u.get('done') else
           f'<form method="post" action="/unsubscribe" style="margin:0"><input type="hidden" name="t" value="{TOKEN}">'
           f'<input type="hidden" name="id" value="{k}"><button style="margin:0">ביטול מנוי{" ⚡" if u.get("one_click") else ""}</button></form>')
        + '</td></tr>'
        for k, u in sorted(unsubs.items(), key=lambda kv: (bool(kv[1].get('done')), -kv[1].get('count', 0)))[:40]
    ) or '<tr><td colspan="3" class="muted">יופיעו כאן אחרי הריצה הראשונה</td></tr>'

    token, chat, mirror = telegram_cfg()
    tg_state = ('✓ מחובר' if token and chat else '⏳ הטוקן נשמר — עכשיו לשלוח הודעה כלשהי לבוט ואז „חיבור”' if token else 'לא מחובר')
    telegram_html = f'''
<h2 style="direction:rtl;text-align:right">📱 טלגרם בטלפון</h2>
<p class="muted">מצב: <b>{tg_state}</b>. כל התראה תגיע גם לטלפון, ואפשר להוסיף פעולת „📱 טלגרם” באוטומציות.</p>
<details {'' if token and chat else 'open'}><summary><b>איך מחברים (כ-2 דקות)</b></summary><ol style="font-size:14px;padding-inline-start:20px">
<li>בטלגרם לפתוח את <a href="https://t.me/BotFather" target="_blank">@BotFather</a>, לשלוח <code dir="ltr">/newbot</code>, לבחור שם — ולהעתיק את ה-token שהוא נותן</li>
<li>להדביק כאן ולשמור</li><li>לפתוח את הבוט החדש ולשלוח לו הודעה כלשהי (למשל „היי”)</li><li>ללחוץ „חיבור”</li></ol></details>
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap;align-items:end"><input type="hidden" name="t" value="{TOKEN}">
<div style="flex:1;min-width:220px"><label>Bot token</label><input type="password" name="token" dir="ltr" placeholder="{'••••••• (שמור)' if token else '123456:ABC...'}"></div>
<button formaction="/tg_save" style="margin:0">שמירה</button><button formaction="/tg_connect" style="margin:0">🔗 חיבור</button>
<button formaction="/tg_test" class="ghost" style="margin:0">הודעת ניסיון</button>
<button formaction="/tg_mirror" class="ghost" style="margin:0">{'🔕 בלי שכפול התראות' if mirror else '🔔 לשכפל התראות לטלפון'}</button></form>'''
    vac = load_json(config.SETTINGS_FILE, {}).get('vacation') or {}
    active = vacation_active()
    field = 'font:inherit;padding:8px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)'
    vacation_html = f'''
<h2 style="direction:rtl;text-align:right">🏖️ מצב חופשה</h2>
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
<h2 style="direction:rtl;text-align:right">📝 תבניות תשובה</h2>
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
    return telegram_html + projects_html + vacation_html + templates_html + f'''
<h2 style="direction:rtl;text-align:right">🏷️ הכללים שלי</h2>
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

<h2 style="direction:rtl;text-align:right">📰 ניוזלטרים</h2>
<p class="muted">ביטול דרך הקישור הרשמי של השולח. ⚡ = ביטול מיידי מכאן; בלי ⚡ נפתח דף הביטול של השולח לאישור.</p>
<div class="scroll"><table><thead><tr><th>שולח</th><th>הודעות</th><th></th></tr></thead><tbody>{news}</tbody></table></div>

<h2 style="direction:rtl;text-align:right">🔔 התראות Windows</h2>
<p class="muted">בדיקה קצרה כל שעה בין 7:00 ל-23:00 (לא בשבת ובחג). קופצת התראה רק על מייל דחוף, אירוע אבטחה חריג או כלל עם 🔔 — ורק פעם אחת לכל מייל.
<br>סטטוס: {e(schedule_status(config.ALERTS_TASK))}</p>
<form method="post"><input type="hidden" name="t" value="{TOKEN}">
<button formaction="/test_toast" class="ghost">הצגת התראת ניסיון</button> <button formaction="/check">בדיקה עכשיו</button></form>'''


def settings_page(msg=''):
    accounts = load_json(config.ACCOUNTS_FILE, [])
    oauth = load_json(config.SETTINGS_FILE, {})
    google_id = (oauth.get('google') or {}).get('client_id', '')
    ms_id = (oauth.get('microsoft') or {}).get('client_id', '')
    google_ready = bool(google_id and (oauth.get('google') or {}).get('client_secret'))
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
          <button formaction="/test">בדיקת חיבור</button> <button formaction="/remove" class="ghost">הסרה</button></form></div>''')
    reports = sorted((f for f in os.listdir(config.REPORTS) if f.endswith('.html')), reverse=True)[:8] if os.path.isdir(config.REPORTS) else []
    rep = ''.join(f'<li><a href="/reports/{quote(f)}" target="_blank">{e(f[6:-5])}</a></li>' for f in reports) or '<li class="muted">אין עדיין</li>'
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    return f'''<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MailBrief</title>{FONT}<style>{STYLE}
input[type=text],input[type=email],input[type=password],input[type=number]{{width:100%;font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}}
label{{display:block;margin:10px 0 4px;font-weight:500}} button{{font:inherit;border:0;background:var(--accent);color:#fff;padding:9px 16px;border-radius:10px;cursor:pointer;margin-top:8px}}
button.ghost{{background:transparent;color:var(--ink);border:1px solid var(--line)}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}} .box{{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px}}
</style></head><body><main>
<h1>📬 MailBrief</h1><p class="muted">תדריך מייל שבועי שרץ מקומית על המחשב שלך, לכל תיבת דואר, בלי AI. התדריך השבועי: {e(schedule_status())}<br>{e(holy_status())}</p>{note}
<form method="post" action="/pause" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:8px 0"><input type="hidden" name="t" value="{TOKEN}">
{f'<b style="color:var(--warn)">⏸️ מושהה עד {paused_until():%d/%m %H:%M}</b><button name="mode" value="off" style="margin:0">▶️ ביטול השהיה</button>' if paused_until() else
 '<span class="muted">⏸️ השהיית אוטומציות והתראות:</span><button name="mode" value="2h" class="ghost" style="margin:0">לשעתיים</button><button name="mode" value="tomorrow" class="ghost" style="margin:0">עד מחר בבוקר</button>'}</form>
<form method="get" action="/search" style="display:flex;gap:8px;margin:16px 0"><input type="text" name="q" placeholder="🔍 חיפוש בכל התיבות..." style="flex:1">
<button style="margin:0">חיפוש</button></form>
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px"><input type="hidden" name="t" value="{TOKEN}">
<a href="/today" style="text-decoration:none"><button type="button" style="margin:0">☀️ היום שלי</button></a>
<a href="/dashboard" style="text-decoration:none"><button type="button" style="margin:0">📊 לוח בקרה</button></a>
<a href="/stats" style="text-decoration:none"><button type="button" style="margin:0">📈 במספרים</button></a>
<a href="/automations" style="text-decoration:none"><button type="button" style="margin:0">⚡ אוטומציות</button></a>
<a href="/clients" style="text-decoration:none"><button type="button" style="margin:0">👥 לקוחות</button></a>
<a href="/help" style="text-decoration:none"><button type="button" style="margin:0">❓ מדריך</button></a>
<a href="/reading" style="text-decoration:none"><button type="button" style="margin:0">📚 רשימת קריאה</button></a>
<button formaction="/open_archive" class="ghost" style="margin:0">🗄️ ארכיון מקומי</button>
<button formaction="/archive_backfill" class="ghost" style="margin:0" title="שומר במחשב קבלות ומיילים אישיים מ-90 הימים האחרונים">🗄️ גיבוי 90 יום</button>
<button formaction="/open_receipts" class="ghost" style="margin:0">📂 תיקיית הקבלות והאקסל</button>
<button formaction="/import_receipts" class="ghost" style="margin:0" title="סורק 90 ימים אחורה, שומר קבלות ובונה את האקסל החודשי">⬇️ ייבוא קבלות מ-90 הימים האחרונים</button></form>
<div class="grid"><section>
<h3>התיבות שלי</h3>{"".join(cards) or '<p class="muted">עוד לא הוספת תיבה.</p>'}
<form method="post" action="/run"><input type="hidden" name="t" value="{TOKEN}"><button>▶ הרצה עכשיו</button></form>
<h3>דוחות אחרונים</h3><ul>{rep}</ul></section>
<section class="box"><h3 style="margin-top:0">➕ חיבור תיבה</h3>
<p class="muted" style="margin-top:0">כמו „התחברות עם Google” באתרים: נפתח חלון התחברות, מאשרים — וזהו. בלי סיסמאות.</p>
<form method="post" action="/connect"><input type="hidden" name="t" value="{TOKEN}">
<button name="provider" value="google" {'' if google_ready else 'disabled title="קודם הגדרה חד-פעמית"'}>🔵 חיבור עם Google</button>
<button name="provider" value="microsoft" {'' if ms_ready else 'disabled title="קודם הגדרה חד-פעמית"'}>🟦 חיבור עם Microsoft</button></form>
<details {'' if google_ready else 'open'} style="margin-top:16px"><summary><b>⚙️ הגדרה חד-פעמית של Google</b> {'✓' if google_ready else '(נדרש פעם אחת, כ-5 דקות)'}</summary>
<ol style="font-size:14px;padding-inline-start:20px">
<li>ליצור פרויקט: <a href="https://console.cloud.google.com/projectcreate" target="_blank">console.cloud.google.com/projectcreate</a> — שם: MailBrief</li>
<li>להיכנס ל-<a href="https://console.cloud.google.com/auth/overview" target="_blank">Google Auth Platform</a> ← Get started: שם האפליקציה MailBrief, המייל שלך, Audience = External</li>
<li>ב-<b>Audience</b> ללחוץ <b>Publish app</b> (אחרת ההתחברות פגה כל 7 ימים)</li>
<li>ב-<b>Clients</b> ← Create client ← סוג <b>Desktop app</b> ← להעתיק לכאן את ה-Client ID וה-Client secret</li>
<li>בהתחברות Google יראה „האפליקציה לא אומתה” — זה תקין כי את המפתחת: Advanced ← Go to MailBrief</li></ol>
<form method="post" action="/oauth_config"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="provider" value="google">
<label>Client ID</label><input type="text" name="client_id" dir="ltr" value="{e(google_id)}">
<label>Client secret</label><input type="password" name="client_secret" dir="ltr" placeholder="{'••••••• (שמור)' if google_ready else ''}">
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
</main></body></html>'''
