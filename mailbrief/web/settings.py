"""The settings — split into small sub-tabs (mailboxes, personal, money, clients, rules, tidy-up, backup, connections)
instead of one long page. Each sub-tab is its own address (/?s=money), so saving brings you back to the same place."""
import datetime as dt
import json
import os
from urllib.parse import quote

from mailbrief import config, view
from mailbrief.features import migrate
from mailbrief.features.calendar import holy_status, paused_until
from mailbrief.features.clientcare import DATE_KINDS, REMINDER_DEFAULT, client_dates, debts, next_reminder, suggestions, upcoming_dates
from mailbrief.features.cloud_backup import cloud_cfg, drive_account
from mailbrief.features.daily import daily_cfg
from mailbrief.features.google_apps import API_PAGES, gapps_account
from mailbrief.features.maintenance import schedule_status
from mailbrief.features.replies import reply_templates, vacation_active, VACATION_DEFAULT
from mailbrief.mail.classify import TAG_PREFIX
from mailbrief.mail.oauth import PROVIDERS, bundled_client
from mailbrief.money.accountant import accountant_cfg, previous_month
from mailbrief.money.books import BOOKS, VAT_RATE, export_cfg, missing_invoices, vat_summary, vendors
from mailbrief.money.budget import TAX_KINDS, budget_status, budgets, compare_suppliers, tax_documents
from mailbrief.features.clientcare import THANKS_DEFAULT
from mailbrief.features.security import hibp_key
from mailbrief.features.sharing import share_cfg
from mailbrief.profile import FORMS, g, GOALS, goals, profile
from mailbrief.storage import load_json
from mailbrief.util import e, money
from mailbrief.web import extras
from mailbrief.web.layout import FONT, STYLE, simple_mode, top_bar, undo_banner, update_banner
from mailbrief.web.token import TOKEN


FIELD_NAMES = {'from': 'השולח', 'subject': 'הנושא', 'any': 'השולח, הנושא או התוכן'}

SECTIONS = [('boxes', '📬', 'תיבות'), ('me', '👤', 'אישי והתראות'), ('money', '💰', 'כסף ורו״ח'), ('clients', '👥', 'לקוחות'),
            ('auto', '🏷️', 'כללים ותבניות'), ('tidy', '🧹', 'ניקיון'), ('data', '💾', 'גיבוי ונתונים'), ('connect', '🔌', 'חיבורים')]

# old links (#daily, #migrate ...) -> the sub-tab that holds them now
ANCHORS = {'profile': 'me', 'daily': 'me', 'quiet': 'me', 'notify': 'me', 'accountant': 'money', 'vendors': 'money', 'vat': 'money',
           'export': 'money', 'debts': 'clients', 'dates': 'clients', 'rules': 'auto', 'vacation': 'auto', 'templates': 'auto',
           'clean': 'tidy', 'unopened': 'tidy', 'cloud': 'data', 'migrate': 'data', 'gapps': 'connect', 'keys': 'connect',
           'simple': 'me', 'budget': 'money', 'compare': 'money', 'tax': 'money', 'share': 'clients', 'snippets': 'auto', 'leaks': 'me', 'missing': 'money'}

FIELD = 'font:inherit;padding:8px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)'


def _t():
    return f'<input type="hidden" name="t" value="{TOKEN}">'


def _h(anchor, title):
    return f'<h2 id="{anchor}" style="scroll-margin-top:80px">{title}</h2>'


def _account_options(chosen=''):
    return ''.join(f'<option{" selected" if a["email"] == chosen else ""}>{e(a["email"])}</option>'
                   for a in load_json(config.ACCOUNTS_FILE, [])) or '<option value="">(אין תיבה)</option>'


# ---- 📬 mailboxes -----------------------------------------------------------------------------------------------------

def boxes_section():
    accounts = load_json(config.ACCOUNTS_FILE, [])
    oauth = load_json(config.SETTINGS_FILE, {})
    google_id = (oauth.get('google') or {}).get('client_id', '')
    ms_ready = bool((oauth.get('microsoft') or {}).get('client_id'))
    built_in = bool(bundled_client('google')[0])
    google_ready = bool(google_id and (oauth.get('google') or {}).get('client_secret')) or built_in
    cards = []
    for a in accounts:
        last = a.get('last') or {}
        status = ('<span style="color:var(--bad)">⚠️ ' + e(last['error']) + '</span>') if last.get('error') else (
            f'✓ ריצה אחרונה {e(last["at"])} · {last["count"]} הודעות · {last["tagged"]} תיוגים' if last else 'עוד לא רץ')
        cards.append(f'''<div class="item"><div class="t" dir="ltr" style="text-align:right">{e(a["email"])}</div>
          <div class="m" dir="ltr" style="text-align:right">{e(PROVIDERS[a["auth"]]["name"] + " sign-in" if a.get("auth") in PROVIDERS else a["host"])} · {"תיוג פעיל" if a.get("tag", True) else "בלי תיוג"}</div>
          <div class="s">{status}</div>
          <form method="post" style="display:inline">{_t()}<input type="hidden" name="id" value="{e(a["id"])}">
          <button formaction="/test">בדיקת חיבור</button> <button formaction="/remove" class="ghost">הסרה</button></form>
          <form method="post" style="display:inline">{_t()}<input type="hidden" name="only" value="{e(a["email"])}">
          <button formaction="/check" class="ghost" title="בדיקה מהירה של היומיים האחרונים — רק לתיבה הזו">🔄 בדיקה</button>
          <button formaction="/run" class="ghost" title="תדריך מלא לשבוע — רק לתיבה הזו">▶ תדריך לתיבה הזו</button></form></div>''')
    reports = sorted((f for f in os.listdir(config.REPORTS) if f.endswith('.html')), reverse=True)[:6] if os.path.isdir(config.REPORTS) else []
    rep = ''.join(f'<li><a href="/reports/{quote(f)}" target="_blank">{e(f[6:-5])}</a></li>' for f in reports) or '<li class="muted">אין עדיין</li>'
    return f'''
<form method="post" action="/pause" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:8px 0">{_t()}
{f'<b style="color:var(--warn)">⏸️ מושהה עד {paused_until():%d/%m %H:%M}</b><button name="mode" value="off" style="margin:0">▶️ ביטול השהיה</button>' if paused_until() else
 '<span class="muted">⏸️ השהיית אוטומציות והתראות:</span><button name="mode" value="2h" class="ghost" style="margin:0">לשעתיים</button><button name="mode" value="tomorrow" class="ghost" style="margin:0">עד מחר בבוקר</button>'}</form>
<div class="grid"><section>
<h3>התיבות שלי</h3>{"".join(cards) or '<p class="muted">עוד לא הוספת תיבה — מתחילים בכפתור „🔵 חיבור עם Google”.</p>'}
<form method="post" action="/run">{_t()}<button>▶ הרצה עכשיו{' — ' + e(view.current_account()) if view.current_account() else (' — כל התיבות' if len(accounts) > 1 else '')}</button></form>
<h3>דוחות אחרונים</h3><ul>{rep}</ul></section>
<section class="box"><h3 style="margin-top:0">➕ חיבור תיבה</h3>
<p class="muted" style="margin-top:0">כמו „התחברות עם Google” באתרים: נפתח חלון התחברות, מאשרים — וזהו. בלי סיסמאות.</p>
<form method="post" action="/connect">{_t()}
<button name="provider" value="google" {'' if google_ready else 'disabled title="קודם הגדרה חד-פעמית (בלשונית 🔌 חיבורים)"'}>🔵 חיבור עם Google</button>
<button name="provider" value="microsoft" {'' if ms_ready else 'disabled title="קודם הגדרה חד-פעמית (בלשונית 🔌 חיבורים)"'}>🟦 חיבור עם Microsoft</button></form>
{'<p class="muted" style="font-size:13px">אם Google מציג „Google hasn’t verified this app” — לוחצים <b>Advanced</b> ← <b>Go to MailBrief</b>. הגישה נשארת רק במחשב שלך.</p>' if built_in and not google_id else ''}
{'' if ms_ready else '<p class="muted" style="font-size:13px">ל-Outlook / Hotmail: הגדרה חד-פעמית בלשונית <a href="/?s=connect#keys">🔌 חיבורים</a>.</p>'}
<details style="margin-top:12px"><summary><b>✉️ תיבה אחרת עם סיסמה</b> (מייל של עבודה, ספקים ישראליים ועוד)</summary>
<form method="post" action="/add">{_t()}
<label>כתובת מייל</label><input type="email" name="email" required dir="ltr">
<label>סיסמה</label><input type="password" name="password" required dir="ltr">
<label>שרת IMAP <span class="muted">(ריק = ניחוש אוטומטי)</span></label><input type="text" name="host" dir="ltr">
<label>פורט</label><input type="number" name="port" value="993" dir="ltr">
<label style="font-weight:400"><input type="checkbox" name="tag" checked> לתייק אוטומטית (העתק לתיקייה, המקור נשאר)</label>
<button>בדיקה ושמירה</button></form></details>
</section></div>'''


# ---- 👤 personal and notifications ------------------------------------------------------------------------------------

def me_section():
    me = profile()
    form_opts = ''.join(f'<option value="{k}"{" selected" if k == me.get("form") else ""}>{icon} {label}</option>' for k, (icon, label) in FORMS.items())
    daily = daily_cfg()
    hour_opts = ''.join(f'<option value="{h}"{" selected" if h == daily["hour"] else ""}>{h:02d}:00</option>' for h in range(5, 23))
    quiet = load_json(config.SETTINGS_FILE, {}).get('quiet') or {}
    leaks = load_json(config.CACHE_FILE, {}).get('leaks') or {}
    leak_rows = ''.join(f'<li><span dir="ltr">{e(a)}</span> — ' + (', '.join(f'<b>{e(b["name"])}</b> ({e(b["date"][:4])})' for b in found) if found else '✓ לא נמצא')
                        + '</li>' for a, found in (leaks.get('results') or {}).items())
    leaks_html = f'<p class="muted" style="margin-bottom:0">בדיקה אחרונה: {e(leaks.get("at", ""))}</p><ul>{leak_rows}</ul>' if leak_rows else ''
    hours = lambda chosen: ''.join(f'<option value="{h}"{" selected" if h == chosen else ""}>{h:02d}:00</option>' for h in range(24))
    return f'''
{_h('profile', '👤 הפרופיל שלי')}
<p class="muted">השם והלשון שבהם MailBrief פונה — בברכה, בהודעות ובטיפים.</p>
<form method="post" action="/profile" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<input type="text" name="name" value="{e(me.get('name', ''))}" maxlength="30" placeholder="השם שלך" style="flex:1;min-width:160px;{FIELD}">
<select name="form" style="{FIELD}">{form_opts}</select><button style="margin:0">שמירה</button>
<div style="flex-basis:100%;display:flex;gap:6px;flex-wrap:wrap;margin-top:4px"><span class="muted">מה מוצג ב„היום שלי”:</span>
{''.join(f'<label style="font-weight:400;margin:0;display:inline-flex;gap:4px;align-items:center;border:1px solid var(--line);border-radius:999px;padding:4px 10px">'
         f'<input type="checkbox" name="goal" value="{k}"{" checked" if k in goals() else ""}> {icon} {e(title)}</label>' for k, (icon, title, _) in GOALS.items())}
</div></form>

{_h('simple', '🌱 מצב פשוט')}
<p class="muted">רק מה שצריך: „היום שלי”, תיבות, חיפוש ומדריך. הכלים המתקדמים (תקציב, ייצוא לחשבשבת, אוטומציות, לקוחות ועוד)
מוסתרים מהתפריט — וזמינים תמיד דרך Ctrl+K. אפשר לחזור לתצוגה המלאה בכל רגע.</p>
<form method="post" action="/simple">{_t()}{'<button name="on" value="0" class="ghost" style="margin:0">להציג את הכול</button>' if simple_mode() else
 '<button name="on" value="1" style="margin:0">🌱 להפעיל מצב פשוט</button>'}</form>

{_h('daily', '✉️ סיכום יומי במייל')}
<p class="muted">{'<b style="color:var(--good)">פעיל</b> — ' if daily['on'] else ''}כל בוקר מגיע לתיבה שלך מייל קצר: מה דחוף, מה ביומן, מה לתשלום, חשבוניות שלא הגיעו ומי מחכה לתשובה.
ביום ראשון — גם „השבוע שלך במספרים”. נוח לקרוא בטלפון. לא נשלח בשבת ובחג.</p>
<form method="post" action="/daily" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<span>לשלוח ל</span><select name="account" style="{FIELD}">{_account_options(daily['account'])}</select>
<span>בשעה</span><select name="hour" style="{FIELD}">{hour_opts}</select>
<button name="action" value="on" style="margin:0">{'שמירה' if daily['on'] else '✅ הפעלה'}</button>
{'<button name="action" value="off" class="ghost" style="margin:0">כיבוי</button>' if daily['on'] else ''}
<button formaction="/daily_test" class="ghost" style="margin:0">📨 לשלוח עכשיו לניסיון</button></form>

{_h('quiet', '🔕 שעות שקטות')}
<p class="muted">{'<b style="color:var(--good)">פעיל</b> — ' if quiet.get('on') else ''}בשעות האלה לא קופצות התראות — חוץ מאנשים חשובים (VIP) שבוחרים כאן.
שום דבר לא הולך לאיבוד: הכול מחכה ב„היום שלי”. בשבת ובחג אין התראות בכלל.</p>
<form method="post" action="/quiet" style="display:grid;gap:8px">{_t()}
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><span>מ-</span><select name="from" style="{FIELD}">{hours(int(quiet.get('from', 22)))}</select>
<span>עד</span><select name="to" style="{FIELD}">{hours(int(quiet.get('to', 7)))}</select></div>
<label style="margin:0">⭐ VIP — כתובות או דומיינים שמותר להם להתריע גם בשעות השקטות <span class="muted">(אחד בכל שורה, למשל boss@company.co.il או client.co.il)</span>
<textarea name="vip" rows="3" dir="ltr" style="width:100%;{FIELD}">{e(chr(10).join(quiet.get('vip', [])))}</textarea></label>
<div><button name="action" value="on" style="margin:0">{'שמירה' if quiet.get('on') else '✅ הפעלה'}</button>
{'<button name="action" value="off" class="ghost" style="margin:0">כיבוי</button>' if quiet.get('on') else ''}</div></form>

{_h('leaks', '🔓 בדיקת דליפות סיסמה')}
<p class="muted">פעם בשבוע בודק אם הכתובות שלך הופיעו בדליפת מידע ידועה (Have I Been Pwned) — ואם כן, מתריע להחליף סיסמה.
נשלחת רק הכתובת. השירות דורש מפתח (בתשלום, כ-4$ לחודש) מ-<a href="https://haveibeenpwned.com/API/Key" target="_blank">haveibeenpwned.com/API/Key</a>.
בלי מפתח — אפשר לבדוק ידנית ב-<a href="https://haveibeenpwned.com/" target="_blank">haveibeenpwned.com</a>.</p>
<form method="post" action="/hibp" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<input type="password" name="key" placeholder="{'••••••• (שמור)' if hibp_key() else 'מפתח API'}" dir="ltr" style="min-width:220px;{FIELD}">
<button name="action" value="save" style="margin:0">שמירה</button>
{'<button name="action" value="check" class="ghost" style="margin:0">🔍 בדיקה עכשיו</button><button name="action" value="off" class="ghost" style="margin:0">הסרה</button>' if hibp_key() else ''}</form>
{leaks_html}

{_h('notify', '🔔 התראות Windows ותזמונים')}
<p class="muted">בדיקה קצרה כל שעה בין 7:00 ל-23:00 (לא בשבת ובחג). קופצת התראה על מייל דחוף, אירוע אבטחה חריג, כלל עם 🔔, או חשבונית שלא הגיעה — פעם אחת לכל דבר.
<br>סטטוס: {e(schedule_status(config.ALERTS_TASK))} · התדריך השבועי: {e(schedule_status())}</p>
<form method="post" style="display:flex;gap:6px;flex-wrap:wrap">{_t()}
<button formaction="/setup" name="action" value="install" class="ghost" style="margin:0">🔧 רישום / תיקון התזמונים</button>
<button formaction="/setup" name="action" value="remove" class="ghost" style="margin:0">הסרת התזמונים</button>
<button formaction="/test_toast" class="ghost" style="margin:0">הצגת התראת ניסיון</button>
<button formaction="/check" style="margin:0">בדיקה עכשיו</button></form>'''


# ---- 💰 money and the accountant --------------------------------------------------------------------------------------

def money_section(month=''):
    month = month or previous_month()
    acct = accountant_cfg()
    this_year = dt.date.today().year
    vat = vat_summary(month)
    gaps = missing_invoices()
    exp = export_cfg()
    book_opts = lambda chosen: ''.join(f'<option{" selected" if b == chosen else ""}>{e(b)}</option>' for b in BOOKS)
    vendor_rows = ''.join(
        f'<tr><td dir="auto"><b>{e(v["name"])}</b><div class="muted" style="font-size:12px" dir="ltr">{e(v["key"])}</div></td>'
        f'<td>{v["count"]}</td><td>{money(v["total"])}</td><td colspan="3"><form method="post" action="/vendor_set" style="display:flex;gap:6px;flex-wrap:wrap;margin:0;align-items:center">{_t()}'
        f'<input type="hidden" name="key" value="{e(v["key"])}"><select name="book" style="{FIELD}">{book_opts(v.get("book", "אחר"))}</select>'
        f'<label style="margin:0;font-weight:400;display:inline-flex;gap:4px;align-items:center"><input type="checkbox" name="no_vat"{" checked" if v["no_vat"] else ""}> בלי מע״מ</label>'
        f'<input type="text" name="account" value="{e(v["account"])}" placeholder="כרטיס ספק" dir="ltr" style="width:110px;{FIELD}">'
        f'<button class="ghost" style="margin:0">שמירה</button></form></td></tr>'
        for v in vendors()[:40]) or '<tr><td class="muted">עוד אין קבלות — „⬇️ ייבוא קבלות” למטה</td></tr>'
    vat_rows = ''.join(f'<tr><td>{e(b)}</td><td>{money(total)}</td><td>{money(v)}</td></tr>'
                       for b, (total, v) in sorted(vat['books'].items(), key=lambda kv: -kv[1][0]))
    gap_rows = ''.join(f'<div class="item"><div class="t">🧾 {e(m["vendor"])}</div><div class="m">מגיעה בדרך כלל עד ה-{m["day"]} לחודש · '
                       f'האחרונה {e(m["last"][8:10])}/{e(m["last"][5:7])}{" · " + e(m["currency"]) + str(m["amount"]) if m.get("amount") is not None else ""}</div></div>'
                       for m in gaps) or '<p class="muted">✓ כל החשבוניות הקבועות של החודש הגיעו (או שעוד לא הגיע זמנן)</p>'
    status = budget_status()
    budget_html = ''.join(
        f'<div class="item"><div class="t">{e(b["book"])} <span class="muted">— ₪{b["spent"]:,.0f} מתוך ₪{b["budget"]:,.0f}</span></div>'
        f'<div style="height:8px;border-radius:99px;background:var(--line);overflow:hidden;margin-top:6px"><div style="height:100%;width:{min(b["pct"], 100)}%;'
        f'background:{"var(--bad)" if b["over"] else "var(--warn)" if b["pct"] >= 80 else "var(--good)"}"></div></div></div>' for b in status) \
        or '<p class="muted">עוד לא הוגדרו תקציבים.</p>'
    current = budgets()
    budget_inputs = ''.join(f'<label style="margin:0;font-weight:400">{e(b)}<input type="number" min="0" step="10" name="b_{i}" '
                            f'value="{int(current[b]) if b in current else ""}" placeholder="₪" style="width:100%;{FIELD}"></label>'
                            for i, b in enumerate(BOOKS))
    compare_html = ''.join(
        f'<h3 style="margin:14px 0 4px">{e(book)}</h3><div class="scroll"><table><tbody>' + ''.join(
            f'<tr><td dir="auto">{"🏆 " if n == 0 else ""}{e(v["vendor"])}</td><td>₪{v["monthly"]:,.0f} לחודש</td><td class="muted">{v["months"]} חודשים</td></tr>'
            for n, v in enumerate(rows)) + '</tbody></table></div>' for book, rows in compare_suppliers().items())
    docs = tax_documents(this_year)
    tax_html = ''.join(f'<span class="pill">{TAX_KINDS[k][0]} {e(TAX_KINDS[k][1])}: {len(v)} קבלות · {money(sum((r.get("amount_ils") or r.get("amount") or 0) for r in v))}</span> '
                       for k, v in docs.items())
    tax_html = f'<p>השנה עד עכשיו: {tax_html}</p>' if tax_html else ''
    account_inputs = ''.join(f'<label style="margin:0;font-weight:400">{e(b)}<input type="text" name="acc_{i}" value="{e(exp["accounts"].get(b, ""))}" dir="ltr" style="width:100%;{FIELD}"></label>'
                             for i, b in enumerate(BOOKS))
    return f'''
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">{_t()}
<button formaction="/open_receipts" class="ghost" style="margin:0">📂 תיקיית הקבלות והאקסל</button>
<button formaction="/import_receipts" class="ghost" style="margin:0" title="סורק 90 ימים אחורה, שומר קבלות ובונה את האקסל החודשי">⬇️ ייבוא קבלות מ-90 הימים האחרונים</button></form>

{_h('missing', '🧾 חשבוניות שעוד לא הגיעו החודש')}
<p class="muted">ספקים ששולחים חשבונית כל חודש — ועבר המועד הרגיל שלהם בלי שהגיעה. מופיע גם בסיכום היומי ובהתראה.</p>
{gap_rows}

{_h('vat', '🧮 מע״מ תשומות לחודש')}
<form method="get" action="/" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><input type="hidden" name="s" value="money">
<input type="month" name="month" value="{e(month)}" style="{FIELD}"><button class="ghost" style="margin:0">הצגה</button></form>
<div class="kpis"><div class="kpi"><b>{money(vat['total'])}</b><span>סה״כ הוצאות ({vat['count']} קבלות)</span></div>
<div class="kpi"><b>{money(vat['vat'])}</b><span>מע״מ תשומות (לפי {VAT_RATE}%)</span></div>
<div class="kpi"><b>{money(vat['net'])}</b><span>לפני מע״מ</span></div>
{f'<div class="kpi"><b>{money(vat["foreign"])}</b><span>מחו״ל (בלי מע״מ)</span></div>' if vat['foreign'] else ''}</div>
{f'<div class="scroll"><table><thead><tr><th>סיווג</th><th>סה״כ</th><th>מע״מ</th></tr></thead><tbody>{vat_rows}</tbody></table></div>' if vat_rows else ''}
<p class="muted" style="font-size:13px">הערכה לפי קבלות בש״ח מספקים בארץ (סכום כולל מע״מ). ספק פטור / עוסק פטור — מסמנים אצלו „בלי מע״מ” בטבלת הספקים. הדיווח הרשמי — אצל הרו״ח.</p>

{_h('vendors', '🏷️ סיווג קבוע לכל ספק')}
<p class="muted">בוחרים פעם אחת את סוג ההוצאה של כל ספק — וכל קבלה ממנו (גם הישנות) מקבלת אותו באקסל, בחבילה לרו״ח ובייצוא.</p>
<div class="scroll"><table><thead><tr><th>ספק</th><th>קבלות</th><th>סה״כ</th><th colspan="3">סיווג · מע״מ · כרטיס בהנה״ח</th></tr></thead><tbody>{vendor_rows}</tbody></table></div>

{_h('budget', '📊 תקציב חודשי לפי סיווג')}
<p class="muted">מגדירים כמה מותר להוציא בחודש על כל סוג — ומקבלים התראה כשעוברים (ובסיכום היומי מ-80%).</p>
{budget_html}
<details style="margin-top:8px"><summary><b>⚙️ הגדרת תקציבים</b></summary>
<form method="post" action="/budgets" style="display:grid;gap:8px;margin-top:8px">{_t()}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px">{budget_inputs}</div>
<div><button style="margin:0">שמירה</button></div></form></details>

{_h('compare', '⚖️ מי זול יותר — ספקים מאותו סוג')}
<p class="muted">עלות חודשית ממוצעת בחצי השנה האחרונה, לכל ספק בסיווג שיש בו כמה ספקים. הזול — ראשון.</p>
{compare_html or '<p class="muted">עוד אין סיווג עם שני ספקים או יותר.</p>'}

{_h('tax', '🧾 מסמכים להחזר מס')}
<p class="muted">קבלות על הוצאות רפואיות, תרומות (סעיף 46) וביטוח חיים / פנסיה — נאספות לתיקייה אחת עם אקסל מסכם, מוכן להגשה או לרו״ח.</p>
<form method="post" action="/tax_collect" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<select name="year" style="{FIELD}">{''.join(f'<option>{y}</option>' for y in range(this_year, this_year - 4, -1))}</select>
<button style="margin:0">📁 איסוף המסמכים</button></form>
{tax_html}

{_h('accountant', '📦 לרואה החשבון')}
<p class="muted">{'<b style="color:var(--good)">פעיל</b> — ' if acct['on'] else ''}בכל חודש, ביום שבוחרים: ZIP עם האקסל של החודש הקודם
ועם כל הקבלות — נשלח לרו״ח מהתיבה שלך (לא בשבת ובחג). אפשר גם להכין ידנית.</p>
<form method="post" action="/accountant" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<input type="email" name="email" value="{e(acct['email'])}" placeholder="cpa@example.co.il" dir="ltr" style="flex:1;min-width:200px;{FIELD}">
<input type="text" name="name" value="{e(acct['name'])}" placeholder="שם הרו״ח (לפתיחת המייל)" style="min-width:160px;{FIELD}">
<span>ב-</span><input type="number" name="day" min="1" max="28" value="{acct['day']}" style="width:70px;{FIELD}"><span>לחודש, מ-</span>
<select name="account" style="{FIELD}">{_account_options(acct['account'])}</select>
<button name="action" value="on" style="margin:0">{'שמירה' if acct['on'] else '✅ הפעלה'}</button>
{'<button name="action" value="off" class="ghost" style="margin:0">כיבוי</button>' if acct['on'] else ''}</form>
<form method="post" action="/accountant_package" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px">{_t()}
<input type="month" name="month" value="{e(month)}" style="{FIELD}">
<button name="action" value="zip" class="ghost" style="margin:0">📦 להכין חבילה</button>
<button name="action" value="send" class="ghost" style="margin:0">📨 לשלוח עכשיו לרו״ח</button></form>
<form method="post" action="/yearly" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px">{_t()}
<span class="muted">סיכום שנתי לפי סיווג וספק:</span>
<select name="year" style="{FIELD}">{''.join(f'<option>{y}</option>' for y in range(this_year, this_year - 4, -1))}</select>
<button class="ghost" style="margin:0">📊 להכין סיכום שנתי</button></form>

{_h('export', '📤 ייצוא לחשבשבת / תוכנת הנהלת חשבונות')}
<p class="muted">קובץ CSV (בקידוד של חשבשבת ו-Excel) עם שורה לכל קבלה: תאריך, אסמכתא, ספק, סיווג, חשבון הוצאה, כרטיס ספק, מע״מ ולפני מע״מ.
מספרי החשבונות — מכרטסת הנהלת החשבונות שלך (אפשר להשאיר ריק ולמלא אצל הרו״ח).</p>
<form method="post" action="/export_month" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<input type="month" name="month" value="{e(month)}" style="{FIELD}"><button style="margin:0">📤 יצירת קובץ ייצוא</button></form>
<details style="margin-top:10px"><summary><b>⚙️ מספרי חשבונות</b></summary>
<form method="post" action="/export_cfg" style="display:grid;gap:8px;margin-top:8px">{_t()}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px">
<label style="margin:0;font-weight:400">חשבון מע״מ תשומות<input type="text" name="vat_account" value="{e(exp['vat_account'])}" dir="ltr" style="width:100%;{FIELD}"></label>
<label style="margin:0;font-weight:400">כרטיס ספקים כללי<input type="text" name="supplier_account" value="{e(exp['supplier_account'])}" dir="ltr" style="width:100%;{FIELD}"></label>
{account_inputs}</div><div><button style="margin:0">שמירה</button></div></form></details>'''


# ---- 👥 clients -------------------------------------------------------------------------------------------------------

def clients_section():
    today = dt.date.today().isoformat()
    debt_rows = ''.join(
        f'<tr><td dir="auto"><b>{e(d["name"])}</b><div class="muted" dir="ltr" style="font-size:12px;text-align:right">{e(d["email"])}</div></td>'
        f'<td>{e(d["amount"])}</td><td>{e(d["invoice"])}</td>'
        f'<td{" style=color:var(--bad)" if d["status"] == "open" and d["due"] < today else ""}>{e(d["due"][8:10])}/{e(d["due"][5:7])}</td>'
        f'<td>{"✓ שולם" if d["status"] == "paid" else "⏹ הופסק" if d["status"] == "stopped" else f"{len(d["reminders"])}/3" + (f" · הבאה {next_reminder(d):%d/%m}" if next_reminder(d) else "")}</td>'
        f'<td><form method="post" action="/debt_set" style="display:flex;gap:4px;margin:0">{_t()}<input type="hidden" name="id" value="{e(d["id"])}">'
        + ('<button name="status" value="stopped" class="ghost" style="margin:0">⏹ עצירה</button>' if d['status'] == 'open' else '')
        + '<button name="status" value="deleted" class="ghost" style="margin:0">🗑️</button></form>'
        + (f'<details style="margin-top:4px"><summary style="font-size:13px;cursor:pointer"><b>✓ שולם</b></summary>'
           f'<form method="post" action="/debt_set" enctype="multipart/form-data" style="display:grid;gap:6px;margin-top:6px;min-width:230px">{_t()}'
           f'<input type="hidden" name="id" value="{e(d["id"])}"><input type="hidden" name="status" value="paid">'
           f'<label style="margin:0;font-weight:400;display:flex;gap:6px;align-items:center"><input type="checkbox" name="thanks" checked> 💌 לשלוח תודה</label>'
           f'<input type="file" name="files" multiple accept=".pdf,image/*" style="font-size:13px" title="הקבלה (לא חובה)">'
           f'<button style="margin:0">✓ שולם</button></form></details>' if d['status'] == 'open' else '')
        + '</td></tr>'
        for d in sorted(debts(), key=lambda d: (d['status'] != 'open', d['due']))) or '<tr><td class="muted">אין חשבוניות פתוחות למעקב</td></tr>'
    sugg = ''.join(
        f'<form method="post" action="/debt_add" class="item" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 6px">{_t()}'
        f'<input type="hidden" name="account" value="{e(r.get("account", ""))}"><input type="hidden" name="email" value="{e(r.get("to_email", ""))}">'
        f'<input type="hidden" name="name" value="{e(r.get("to", ""))}"><input type="hidden" name="invoice" value="{e(r.get("subject", "")[:40])}">'
        f'<input type="hidden" name="sent" value="{(dt.date.today() - dt.timedelta(days=r.get("days", 0))).isoformat()}">'
        f'<span style="flex:1" dir="auto">📤 {e(r.get("subject", ""))} <span class="muted">— אל {e(r.get("to", ""))} · {r.get("days", 0)} ימים בלי תשובה</span></span>'
        f'<input type="text" name="amount" placeholder="סכום" style="width:100px;{FIELD}"><button class="ghost" style="margin:0">💰 למעקב תשלום</button></form>'
        for r in suggestions())
    date_rows = ''.join(
        f'<tr><td>{DATE_KINDS[d["kind"]][0]} {e(d["name"])}<div class="muted" dir="ltr" style="font-size:12px;text-align:right">{e(d["email"])}</div></td>'
        f'<td>{d["day"]:02d}/{d["month"]:02d}</td><td>{e(DATE_KINDS[d["kind"]][1])}</td>'
        f'<td><form method="post" action="/date_remove" style="margin:0">{_t()}<input type="hidden" name="id" value="{e(d["id"])}">'
        f'<button class="ghost" style="margin:0">🗑️</button></form></td></tr>' for d in client_dates()) or '<tr><td class="muted">עוד אין תאריכים</td></tr>'
    soon = ''.join(f'<span class="pill">{DATE_KINDS[d["kind"]][0]} {e(d["name"])} · {d["date"]:%d/%m}</span>' for d in upcoming_dates())
    kinds = ''.join(f'<option value="{k}">{icon} {title}</option>' for k, (icon, title, _) in DATE_KINDS.items())
    share = share_cfg()
    labels = sorted({r['label'] for r in load_json(config.RULES_FILE, []) if r.get('label')})
    label_boxes = ''.join(f'<label style="margin:0;font-weight:400;display:inline-flex;gap:4px;align-items:center;border:1px solid var(--line);'
                          f'border-radius:999px;padding:4px 10px"><input type="checkbox" name="label" value="{e(l)}"{" checked" if l in share["labels"] else ""}> 🏷️ {e(l)}</label>'
                          for l in labels)
    return f'''
<p class="muted">לוח הלקוחות המלא (מיילים, קבלות, זמני תגובה): <a href="/clients">👥 לשונית לקוחות ←</a> · ברכות חג לכולם: <a href="/greetings">🗓️ ברכות חג ←</a></p>

{_h('debts', '💰 מעקב תשלומים')}
<p class="muted">חשבונית ששלחת ללקוח ועוד לא שולמה: אחרי מועד התשלום יוצאת תזכורת מנומסת מהתיבה שלך (10:00, אף פעם לא בשבת ובחג),
ועוד אחת כל כמה ימים — עד 3 תזכורות, או עד שמסמנים „✓ שולם”.</p>
<div class="scroll"><table><thead><tr><th>לקוח</th><th>סכום</th><th>חשבונית</th><th>לתשלום עד</th><th>תזכורות</th><th></th></tr></thead><tbody>{debt_rows}</tbody></table></div>
{f'<h3>הצעות — חשבוניות ששלחת ולא נענו</h3>{sugg}' if sugg else ''}
<details style="margin-top:10px"><summary><b>➕ חשבונית חדשה למעקב</b></summary>
<form method="post" action="/debt_add" style="display:grid;gap:8px;margin-top:8px">{_t()}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px">
<label style="margin:0">מייל הלקוח<input type="email" name="email" required dir="ltr" style="width:100%;{FIELD}"></label>
<label style="margin:0">שם<input type="text" name="name" style="width:100%;{FIELD}"></label>
<label style="margin:0">סכום<input type="text" name="amount" placeholder="₪1,200" style="width:100%;{FIELD}"></label>
<label style="margin:0">מספר חשבונית<input type="text" name="invoice" style="width:100%;{FIELD}"></label>
<label style="margin:0">נשלחה ב-<input type="date" name="sent" value="{today}" style="width:100%;{FIELD}"></label>
<label style="margin:0">ימים לתשלום<input type="number" name="due_days" value="30" min="0" max="120" style="width:100%;{FIELD}"></label>
<label style="margin:0">תזכורת כל (ימים)<input type="number" name="every" value="7" min="3" max="30" style="width:100%;{FIELD}"></label>
<label style="margin:0">מהתיבה<select name="account" style="width:100%;{FIELD}">{_account_options()}</select></label></div>
<label style="margin:0">נוסח התזכורת <span class="muted">({{first_name}} {{invoice}} {{amount}} {{date}} {{my_name}})</span>
<textarea name="text" rows="5" style="width:100%;{FIELD}">{e(REMINDER_DEFAULT)}</textarea></label>
<div><button style="margin:0">💰 הוספה למעקב</button></div></form></details>

<p class="muted" style="font-size:13px">💌 „✓ שולם” עם תודה: יוצא ללקוח מייל תודה (עם הקבלה, אם צירפת) בנוסח:
<span style="white-space:pre-line">{e(THANKS_DEFAULT)}</span></p>

{_h('share', '📋 דוח שבועי לשותף / עובד')}
<p class="muted">{'<b style="color:var(--good)">פעיל</b> — ' if share['on'] else ''}כל יום ראשון בבוקר: מה קרה בשבוע עם התוויות שבוחרים (למשל הלקוחות שהם מטפלים בהם) —
מי כתב, על מה, ומה עוד ממתין. רק התוויות שנבחרו נשלחות, שום דבר אחר.</p>
<form method="post" action="/share" style="display:grid;gap:8px">{_t()}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px">
<label style="margin:0">למייל<input type="email" name="email" value="{e(share['email'])}" dir="ltr" style="width:100%;{FIELD}"></label>
<label style="margin:0">שם<input type="text" name="name" value="{e(share['name'])}" style="width:100%;{FIELD}"></label>
<label style="margin:0">מהתיבה<select name="account" style="width:100%;{FIELD}">{_account_options(share['account'])}</select></label></div>
<div style="display:flex;gap:6px;flex-wrap:wrap">{label_boxes or '<span class="muted">עוד אין תוויות — יוצרים כלל בלשונית 🏷️ כללים</span>'}</div>
<div><button name="action" value="on" style="margin:0">{'שמירה' if share['on'] else '✅ הפעלה'}</button>
{'<button name="action" value="off" class="ghost" style="margin:0">כיבוי</button>' if share['on'] else ''}
<button name="action" value="test" class="ghost" style="margin:0">📨 לשלוח עכשיו לניסיון</button></div></form>

{_h('dates', '🎂 ימי הולדת ותאריכים של לקוחות')}
<p class="muted">ביום עצמו, ב-9:00, יוצאת ברכה אישית מהתיבה שלך (תאריך שנופל בשבת או בחג — יוצא במוצאי שבת/חג). {('בקרוב: ' + soon) if soon else ''}</p>
<div class="scroll"><table><tbody>{date_rows}</tbody></table></div>
<details style="margin-top:10px"><summary><b>➕ תאריך חדש</b></summary>
<form method="post" action="/date_add" style="display:grid;gap:8px;margin-top:8px">{_t()}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px">
<label style="margin:0">מייל<input type="email" name="email" required dir="ltr" style="width:100%;{FIELD}"></label>
<label style="margin:0">שם<input type="text" name="name" style="width:100%;{FIELD}"></label>
<label style="margin:0">תאריך<input type="date" name="day" required style="width:100%;{FIELD}"></label>
<label style="margin:0">סוג<select name="kind" style="width:100%;{FIELD}">{kinds}</select></label>
<label style="margin:0">מהתיבה<select name="account" style="width:100%;{FIELD}">{_account_options()}</select></label></div>
<label style="margin:0">נוסח משלך <span class="muted">(ריק = נוסח מוכן · {{first_name}} {{my_name}})</span><textarea name="text" rows="3" style="width:100%;{FIELD}"></textarea></label>
<div><button style="margin:0">➕ הוספה</button></div></form></details>'''


# ---- 🏷️ rules, vacation, templates ------------------------------------------------------------------------------------

TEMPLATE_FIELDS = ['שם_פרטי', 'שם', 'נושא', 'מספר_חשבונית', 'מספר_הזמנה', 'סכום', 'תאריך', 'תאריך_תשלום', 'היום', 'השם_שלי']


def auto_section():
    rules = load_json(config.RULES_FILE, [])
    rows = ''.join(
        f'<tr><td>{FIELD_NAMES.get(r["field"], r["field"])} מכיל <b dir="auto">„{e(r["contains"])}”</b></td>'
        f'<td>🏷️ {e(r["label"])}{" 🔔" if r.get("notify") else ""}'
        + (f'<div style="font-size:13px">↪️ מועבר אל <span dir="ltr">{e(r["forward_to"])}</span></div>' if r.get('forward_to') else '') + '</td>'
        f'<td><form method="post" action="/rule_delete" style="margin:0">{_t()}'
        f'<input type="hidden" name="id" value="{e(r["id"])}"><button class="ghost" style="margin:0">מחיקה</button></form></td></tr>'
        for r in rules) or '<tr><td colspan="3" class="muted">עוד אין כללים</td></tr>'
    options = ''.join(f'<option value="{k}">{v}</option>' for k, v in FIELD_NAMES.items())
    forward_rows = ''.join(
        f'<tr><td>{e(f["at"])}</td><td dir="auto">{e(f["subject"][:60])}</td><td dir="ltr">→ {e(f["to"])}</td><td>'
        + ('<span style="color:var(--good)">✓ נשלח</span>' if f.get('ok') else f'<span style="color:var(--bad)">⚠️ {e(f.get("error", ""))}</span>')
        + '</td></tr>' for f in reversed(load_json(config.FORWARD_LOG, [])[-10:])) or '<tr><td class="muted">עוד לא הועבר כלום</td></tr>'
    vac = load_json(config.SETTINGS_FILE, {}).get('vacation') or {}
    tmpl_rows = ''.join(
        f'<tr><td><b>{e(t["name"])}</b><div class="muted" style="font-size:13px;white-space:pre-line">{e(t["text"])}</div></td>'
        f'<td><form method="post" action="/template_delete" style="margin:0">{_t()}'
        f'<input type="hidden" name="id" value="{e(t["id"])}"><button class="ghost" style="margin:0">מחיקה</button></form></td></tr>'
        for t in reply_templates())
    snippet_rows = ''.join(
        f'<tr><td dir="ltr" style="text-align:right;white-space:nowrap"><b>;{e(s["key"])}</b></td><td style="white-space:pre-line">{e(s["text"])}</td>'
        f'<td><form method="post" action="/snippet_delete" style="margin:0">{_t()}<input type="hidden" name="key" value="{e(s["key"])}">'
        f'<button class="ghost" style="margin:0">מחיקה</button></form></td></tr>'
        for s in load_json(config.SETTINGS_FILE, {}).get('snippets') or []) or '<tr><td class="muted">עוד אין קיצורים</td></tr>'
    chips = ''.join(f'<button type="button" class="ghost chip" data-field="{{{f}}}" style="margin:0;padding:3px 10px;font-size:13px">{{{f}}}</button>'
                    for f in TEMPLATE_FIELDS)
    return f'''
<p class="muted">אוטומציות מתקדמות (כש___ ← אם___ ← אז___): <a href="/automations">⚡ לשונית אוטומציות ←</a></p>
{_h('rules', '🏷️ הכללים שלי')}
<p class="muted">כל מייל שמתאים לכלל מקבל תווית משלו (תחת „{TAG_PREFIX}”) ומקבץ משלו בדוח. 🔔 = גם התראה ב-Windows.</p>
<div class="scroll"><table><tbody>{rows}</tbody></table></div>
<form method="post" action="/rule_add" class="box" style="margin-top:12px;display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;align-items:end">
{_t()}
<div><label>אם</label><select name="field" style="width:100%;{FIELD}">{options}</select></div>
<div><label>מכיל</label><input type="text" name="contains" required placeholder="למשל: @client.co.il"></div>
<div><label>תווית</label><input type="text" name="label" maxlength="40" placeholder="למשל: לקוח כהן"></div>
<div><label>↪️ העברה אל <span class="muted">(לא חובה)</span></label><input type="email" name="forward_to" dir="ltr" placeholder="accountant@example.com"></div>
<div><label style="font-weight:400"><input type="checkbox" name="notify"> 🔔 התראה</label><button>➕ הוספת כלל</button></div></form>
<p class="muted" style="font-size:13px">↪️ העברה: רק מיילים שמגיעים <b>אחרי</b> יצירת הכלל, כל מייל פעם אחת, עד {config.MAX_FORWARDS_PER_RUN} בריצה, עם כל הקבצים המצורפים.
הבדיקה רצה כל שעה בין 7:00 ל-23:00 (לא בשבת ובחג).</p>
<details><summary><b>↪️ העברות אחרונות</b></summary><div class="scroll"><table><tbody>{forward_rows}</tbody></table></div>
<form method="post" action="/test_send">{_t()}<button class="ghost">✉️ בדיקת שליחה (מייל ניסיון לעצמך)</button></form></details>

{_h('templates', '📝 תבניות תשובה עם שדות')}
<p class="muted">ב„היום שלי” ובמיון המהיר: בוחרים תבנית — והשדות מתמלאים לבד מהמייל: השם, מספר החשבונית או ההזמנה, הסכום, התאריך.
<br>למשל: „שלום {{שם_פרטי}}, קיבלנו את חשבונית {{מספר_חשבונית}} על סך {{סכום}}, תודה!”</p>
<div class="scroll"><table><tbody>{tmpl_rows}</tbody></table></div>
<form method="post" action="/template_add" class="box" style="display:grid;gap:8px;margin-top:10px">{_t()}
<input type="text" name="name" required maxlength="40" placeholder="שם התבנית" style="{FIELD}">
<textarea id="tmpl-text" name="text" rows="4" required placeholder="שלום {{שם_פרטי}}, ..." style="{FIELD}"></textarea>
<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="muted" style="font-size:13px">הוספת שדה:</span>{chips}</div>
<div><button style="margin:0">➕ הוספת תבנית</button></div></form>
<script>document.querySelectorAll('.chip').forEach(function(b){{b.onclick=function(){{var t=document.getElementById('tmpl-text'),s=t.selectionStart||t.value.length;
t.value=t.value.slice(0,s)+b.dataset.field+t.value.slice(t.selectionEnd||s);t.focus();t.selectionStart=t.selectionEnd=s+b.dataset.field.length;}};}});</script>

{_h('snippets', '⚡ קיצורי טקסט')}
<p class="muted">כותבים <b dir="ltr">;קיצור</b> ורווח בכל תיבת טקסט ב-MailBrief (תשובה במיון המהיר, מייל מתוזמן, ברכות) — והוא הופך לפסקה המלאה.</p>
<div class="scroll"><table><tbody>{snippet_rows}</tbody></table></div>
<form method="post" action="/snippet_add" class="box" style="display:grid;gap:8px;margin-top:10px">{_t()}
<input type="text" name="key" required maxlength="20" pattern="[^ ;]+" placeholder="קיצור (בלי רווחים), למשל: תודה" style="{FIELD}">
<textarea name="text" rows="3" required placeholder="תודה רבה על הפנייה! אחזור אליך עד סוף היום." style="{FIELD}"></textarea>
<div><button style="margin:0">➕ הוספת קיצור</button></div></form>

{_h('vacation', '🏖️ מצב חופשה')}
<p class="muted">{'<b style="color:var(--good)">פעיל עכשיו</b> — ' if vacation_active() else ''}בין התאריכים, מי שכותב לך אישית מקבל מענה אוטומטי — פעם אחת לכל אדם בכל החופשה.
לא לרשימות תפוצה, לא לשולחים אוטומטיים, ולא בשבת ובחג. המשתנה <span dir="ltr">{{to}}</span> = היום שחוזרים.</p>
<form method="post" action="/vacation" class="box" style="display:grid;gap:8px">{_t()}
<div style="display:flex;gap:10px;flex-wrap:wrap"><label style="margin:0">מתאריך <input type="date" name="from" value="{e(vac.get('from', ''))}" style="{FIELD}"></label>
<label style="margin:0">עד תאריך <input type="date" name="to" value="{e(vac.get('to', ''))}" style="{FIELD}"></label></div>
<textarea name="message" rows="4" style="{FIELD}">{e(vac.get('message') or VACATION_DEFAULT)}</textarea>
<div><button name="action" value="save" style="margin:0">שמירה</button> <button name="action" value="off" class="ghost" style="margin:0">כיבוי</button></div></form>'''


# ---- 🧹 tidy up -------------------------------------------------------------------------------------------------------

def tidy_section():
    cache = load_json(config.CACHE_FILE, {})
    preview = cache.get('clean_preview') or {}
    unopened = cache.get('never_opened') or {}
    days_opts = ''.join(f'<option value="{d}"{" selected" if d == preview.get("days", 30) else ""}>{label}</option>'
                        for d, label in ((14, 'שבועיים'), (30, 'חודש'), (60, 'חודשיים'), (90, '3 חודשים'), (180, 'חצי שנה')))
    counts = ''.join(f'<li><span dir="ltr">{e(a)}</span> — {"⚠️ " + e(err) if err else f"<b>{n}</b> מיילים"}</li>' for a, n, err in preview.get('rows', []))
    rows = ''.join(
        f'<label class="item" style="display:flex;gap:10px;align-items:center;margin:0 0 6px;font-weight:400">'
        f'<input type="checkbox" name="ids" value="{e(r["id"])}" checked><span style="flex:1" dir="auto"><b>{e(r["name"])}</b> '
        f'<span class="muted">— {r["count"]} גליונות, אף אחד לא נפתח · {e(r["account"])}</span></span>'
        f'{"<span class=pill>⚡ בלחיצה</span>" if r["one_click"] else "<span class=pill>↗ דרך האתר</span>"}</label>'
        for r in unopened.get('rows', []))
    return f'''
{_h('clean', '🧹 ניקוי תיבת הדואר הנכנס')}
<p class="muted">מעביר לארכיון את כל המיילים הישנים בדואר הנכנס — <b>לא מוחק כלום</b>. ב-Gmail המייל נשאר ב„כל הדואר” ובחיפוש;
בתיבות אחרות הוא עובר לתיקיית Archive. <b>נשארים</b>: מיילים מסומנים בכוכב ⭐, ומיילים שמחכים לתשובה ממך או דחופים.</p>
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<span>מיילים ישנים מ-</span><select name="days" style="{FIELD}">{days_opts}</select>
<button formaction="/clean_preview" class="ghost" style="margin:0">🔍 כמה זה?</button>
<button formaction="/clean_inbox" style="margin:0" onclick="return confirm('להעביר לארכיון את המיילים הישנים? (שום דבר לא נמחק)')">🧹 לנקות עכשיו</button></form>
{f'<p class="muted" style="margin-bottom:0">בדיקה אחרונה ({e(preview.get("at", ""))}, ישנים מ-{preview.get("days")} ימים):</p><ul>{counts}</ul>' if counts else ''}

{_h('unopened', '✂️ ניוזלטרים שאף פעם לא נפתחו')}
<p class="muted">מחפש ב-60 הימים האחרונים ניוזלטרים שהגיעו לפחות 3 פעמים — ואף גליון לא נפתח. מסמנים ומבטלים את כולם יחד.
⚡ = ביטול מיידי מכאן · ↗ = נפתח דף הביטול של השולח. מומלץ פעם בחודש.</p>
<form method="post" action="/never_opened">{_t()}<button class="ghost" style="margin:0">🔍 חיפוש ניוזלטרים שלא נפתחו{f' (אחרון: {e(unopened.get("at", ""))})' if unopened else ''}</button></form>
{f'<form method="post" action="/unsub_many" style="margin-top:10px">{_t()}{rows}<button style="margin-top:6px">✂️ ביטול כל המסומנים</button></form>' if rows else
 ('<p class="muted">✓ לא נמצאו — כל הניוזלטרים שלך נקראים לפעמים</p>' if unopened else '')}
<p class="muted" style="font-size:13px">רשימת הקריאה והארכוב האוטומטי: <a href="/reading">📰 לשונית ניוזלטרים ←</a></p>'''


# ---- 💾 backup and data -----------------------------------------------------------------------------------------------

def data_section():
    accounts = load_json(config.ACCOUNTS_FILE, [])
    google = [a for a in accounts if a.get('auth') == 'google']
    drive, cloud = drive_account(accounts), cloud_cfg()
    files = (load_json(config.CACHE_FILE, {}).get('cloud_files') or [])
    remote = ''.join(
        f'<tr><td dir="ltr">{e(f["name"][10:20])} {e(f["name"][21:23])}:{e(f["name"][23:25])}</td><td>{int(f.get("size", 0)) // 1024} KB</td>'
        f'<td><form method="post" action="/cloud_restore" style="display:flex;gap:6px;margin:0">{_t()}<input type="hidden" name="id" value="{e(f["id"])}">'
        f'<input type="password" name="password" required placeholder="סיסמת הגיבוי" style="width:140px;{FIELD}">'
        f'<button class="ghost" style="margin:0" onclick="return confirm(\'לשחזר את הגיבוי הזה? המצב הנוכחי יישמר קודם בגיבוי מקומי.\')">שחזור</button></form></td></tr>'
        for f in files)
    if drive:
        cloud_html = f'''<p><b style="color:var(--good)">✓ מחובר ל-Google Drive של <span dir="ltr">{e(drive["email"])}</span></b>
{f' · גיבוי אחרון: {e(cloud["last"])}' if cloud.get('last') else ''}</p>
<form method="post" action="/cloud_upload" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<input type="password" name="password" required minlength="8" placeholder="סיסמת הגיבוי (8+ תווים)" style="min-width:200px;{FIELD}">
<label style="margin:0;font-weight:400;display:inline-flex;gap:6px;align-items:center"><input type="checkbox" name="auto"{" checked" if cloud.get("auto") else ""}>
גם אוטומטית כל שבוע (הסיסמה נשמרת מוצפנת במחשב הזה)</label>
<button style="margin:0">⬆️ גיבוי מוצפן עכשיו</button></form>
<form method="post" action="/cloud_list" style="margin-top:8px">{_t()}<button class="ghost" style="margin:0">📋 הגיבויים שב-Drive</button></form>
{f'<div class="scroll" style="margin-top:8px"><table><tbody>{remote}</tbody></table></div>' if remote else ''}'''
    elif google:
        cloud_html = ''.join(f'<form method="post" action="/drive_connect" style="display:inline">{_t()}<input type="hidden" name="id" value="{e(a["id"])}">'
                             f'<button style="margin:0 0 6px">☁️ חיבור ל-Google Drive של <span dir="ltr">{e(a["email"])}</span></button></form> ' for a in google)
    else:
        cloud_html = '<p class="muted">קודם צריך לחבר תיבת Gmail בלשונית 📬 תיבות.</p>'
    prev = migrate.previous_copy()
    prev_info = migrate.summary(prev) if prev else None
    root = load_json(config.SETTINGS_FILE, {}).get('projects_root', '')
    return f'''
{_h('cloud', '☁️ גיבוי מוצפן ל-Google Drive')}
<p class="muted">למקרה שהמחשב מתקלקל או מוחלף: הכללים, ההגדרות, הקבלות וההיסטוריה — נעולים בסיסמה <b>שרק {g('את יודעת', 'אתה יודע', 'אתם יודעים')}</b>,
ונשמרים בתיקייה „MailBrief גיבויים” ב-Drive. Google רואה רק קובץ נעול. MailBrief מקבל גישה רק לקבצים שהוא עצמו יצר.
<b>בלי הסיסמה אי אפשר לשחזר</b> — כדאי לרשום אותה במקום בטוח. (אחרי שחזור במחשב חדש צריך להתחבר מחדש לתיבות.)</p>
{cloud_html}

<h2>💾 גיבויים מקומיים</h2>
<p class="muted">גיבוי אוטומטי בכל ריצה שבועית (10 אחרונים) — רשימה ושחזור ב<a href="/help">❓ מדריך</a>.</p>
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap">{_t()}
<button formaction="/backup_now" class="ghost" style="margin:0">💾 גיבוי עכשיו</button>
<button formaction="/open_archive" class="ghost" style="margin:0">🗄️ ארכיון מקומי</button>
<button formaction="/archive_backfill" class="ghost" style="margin:0" title="שומר במחשב קבלות ומיילים אישיים מ-90 הימים האחרונים">🗄️ שמירת 90 יום לארכיון</button></form>

{_h('migrate', '📦 העברת נתונים מעותק קודם')}
<p class="muted">עוברים למחשב חדש או לגרסה המותקנת? מעתיקים לכאן את התיבות, הקבלות, הארכיון, הכללים וההגדרות. מה שיש כאן עכשיו נשמר קודם בגיבוי.</p>
{f'<div class="item urgent">נמצא MailBrief קודם ב-<span dir="ltr">{e(prev)}</span> — {len(prev_info["accounts"])} תיבות, {prev_info["receipts"]} קבלות.</div>' if prev else ''}
<form method="post" action="/migrate" style="display:flex;gap:8px;flex-wrap:wrap">{_t()}
<input type="text" name="folder" dir="ltr" value="{e(prev)}" placeholder="C:\\MailBrief" style="flex:1;min-width:240px;{FIELD}">
<button style="margin:0">📦 להעביר לכאן</button></form>

<h2>💻 תיקיית פרויקטים</h2>
<p class="muted">„היום שלי” מציג פרויקטי git בתיקייה הזו שיש בהם שינויים שלא נשמרו. ריק = בלי כרטיס פרויקטים.</p>
<form method="post" action="/projects_root" style="display:flex;gap:8px;flex-wrap:wrap">{_t()}
<input type="text" name="root" dir="ltr" value="{e(root)}" placeholder="C:/projects" style="flex:1;min-width:220px;{FIELD}">
<button style="margin:0">שמירה</button></form>
<p class="muted" style="font-size:13px">הנתונים נשמרים ב: <span dir="ltr">{e(config.HERE)}</span></p>'''


# ---- 🔌 connections ---------------------------------------------------------------------------------------------------

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
                f'<form method="post" action="/gapps_choose" style="display:inline;margin:0">{_t()}'
                f'<input type="hidden" name="email" value="{e(a["email"])}"><button class="ghost" style="margin:0 6px">להציג את זה</button></form>'))
                if a.get('gapps') else '<span class="muted">לא מחובר</span>'))
            + f'</td><td><form method="post" style="margin:0">{_t()}<input type="hidden" name="id" value="{e(a["id"])}">'
            + ('<button formaction="/gapps_disconnect" class="ghost" style="margin:0">ניתוק</button>' if a.get('gapps') else
               '<button formaction="/gapps_connect" style="margin:0">📅 חיבור יומן ומשימות</button>')
            + '</form></td></tr>' for a in google)
        body = f'<div class="scroll"><table><tbody>{rows}</tbody></table></div>'
    own = bool((load_json(config.SETTINGS_FILE, {}).get('google') or {}).get('client_id'))
    return f'''
{_h('gapps', '📅 Google Calendar ו-Tasks')}
<p class="muted">האירועים של היום והמשימות הפתוחות מופיעים ב„היום שלי” — עם הוספה מהירה וסימון „בוצע”. בחלון של Google צריך <b>לסמן את שתי תיבות הסימון</b>.
ההרשאה היא רק לאירועים ולמשימות.</p>
{body}
{'' if not own else f"""<details><summary><b>⚙️ עם מפתח משלך: להפעיל את שני הממשקים בפרויקט</b></summary>
<ol style="font-size:14px;padding-inline-start:20px"><li><a href="{API_PAGES['calendar']}" target="_blank">Google Calendar API</a> ← <b>Enable</b></li>
<li><a href="{API_PAGES['tasks']}" target="_blank">Google Tasks API</a> ← <b>Enable</b></li></ol></details>"""}'''


def connect_section():
    oauth = load_json(config.SETTINGS_FILE, {})
    google_id = (oauth.get('google') or {}).get('client_id', '')
    ms_id = (oauth.get('microsoft') or {}).get('client_id', '')
    built_in = bool(bundled_client('google')[0])
    return f'''{gapps_section()}
{_h('keys', '🔑 מפתחות התחברות')}
<details {'' if built_in or google_id else 'open'} style="margin-top:8px"><summary><b>⚙️ {'מפתח Google משלך (לא חובה)' if built_in else 'הגדרה חד-פעמית של Google'}</b> {'✓' if google_id else ''}</summary>
{'<p class="muted" style="font-size:13px">ל-MailBrief יש מפתח מובנה, אז אין צורך בזה. רק למי שרוצה פרויקט Google Cloud משלו:</p>' if built_in else ''}
<ol style="font-size:14px;padding-inline-start:20px">
<li>ליצור פרויקט: <a href="https://console.cloud.google.com/projectcreate" target="_blank">console.cloud.google.com/projectcreate</a></li>
<li><a href="https://console.cloud.google.com/auth/overview" target="_blank">Google Auth Platform</a> ← Get started ← Audience = External ← <b>Publish app</b></li>
<li>Clients ← Create client ← סוג <b>Desktop app</b> ← להעתיק לכאן את ה-Client ID וה-secret</li></ol>
<form method="post" action="/oauth_config">{_t()}<input type="hidden" name="provider" value="google">
<label>Client ID</label><input type="text" name="client_id" dir="ltr" value="{e(google_id)}">
<label>Client secret</label><input type="password" name="client_secret" dir="ltr" placeholder="{'••••••• (שמור)' if (oauth.get('google') or {}).get('client_secret') else ''}">
<button>שמירה</button></form></details>
<details style="margin-top:12px"><summary><b>⚙️ הגדרה חד-פעמית של Microsoft</b> (Outlook / Hotmail / Office 365) {'✓' if ms_id else ''}</summary>
<ol style="font-size:14px;padding-inline-start:20px">
<li><a href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade" target="_blank">Azure ← App registrations</a> ← New registration: „Any organizational directory and personal Microsoft accounts”</li>
<li>Redirect URI: <b>Public client/native</b>, כתובת <code dir="ltr">http://localhost</code></li>
<li>API permissions ← Microsoft Graph ← Delegated ← <b>IMAP.AccessAsUser.All</b></li>
<li>להעתיק לכאן את ה-Application (client) ID</li></ol>
<form method="post" action="/oauth_config">{_t()}<input type="hidden" name="provider" value="microsoft">
<label>Application (client) ID</label><input type="text" name="client_id" dir="ltr" value="{e(ms_id)}">
<button>שמירה</button></form></details>
<p class="muted" style="font-size:13px;margin-top:16px">כל ההרשאות והסיסמאות נשמרות מוצפנות (Windows DPAPI) — רק המשתמש שלך במחשב הזה יכול לפענח אותן.
אפשר לבטל גישה בכל רגע ב-<a href="https://myaccount.google.com/connections" target="_blank">Google</a> או ב-<a href="https://account.live.com/consent/Manage" target="_blank">Microsoft</a>.</p>'''


# ---- the page ---------------------------------------------------------------------------------------------------------

SIMPLE_SECTIONS = ('boxes', 'me', 'auto', 'data')


def subnav(active):
    simple = simple_mode()
    shown = [s for s in SECTIONS if s[0] in SIMPLE_SECTIONS or s[0] == active] if simple else SECTIONS
    return ('<nav class="subtabs">' + ''.join(
        f'<a href="/?s={k}"{" aria-current=page" if k == active else ""}>{icon} {e(title)}</a>' for k, icon, title in shown)
        + (f'<form method="post" action="/simple" style="margin:0;display:inline"><input type="hidden" name="t" value="{TOKEN}">'
           '<button name="on" value="0" class="ghost" style="margin:0;padding:6px 12px;font-size:13px">🌱 מצב פשוט · להציג הכול</button></form>'
           if simple else '') + '</nav>')


def settings_page(msg='', sec='boxes', month=''):
    sec = sec if sec in {k for k, _, _ in SECTIONS} else 'boxes'
    body = {'boxes': boxes_section, 'me': me_section, 'money': lambda: money_section(month), 'clients': clients_section,
            'auto': auto_section, 'tidy': tidy_section, 'data': data_section, 'connect': connect_section}[sec]()
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    title = next(t for k, _, t in SECTIONS if k == sec)
    return f'''<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · הגדרות · MailBrief</title>{FONT}<style>{STYLE}
input[type=text],input[type=email],input[type=password],input[type=number]{{width:100%;font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}}
label{{display:block;margin:10px 0 4px;font-weight:500}} button{{font:inherit;font-weight:500;border:0;background:var(--accent);color:#fff;padding:9px 16px;border-radius:12px;cursor:pointer;margin-top:8px}}
button.ghost{{background:transparent;color:var(--ink);border:1px solid var(--line)}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}} .box{{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px}}
h2{{font-size:20px;margin:28px 0 6px}} h2:first-of-type{{margin-top:12px}}
nav.subtabs{{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 14px;padding-bottom:12px;border-bottom:1px solid var(--line)}}
nav.subtabs a{{text-decoration:none;color:var(--ink);font-size:14px;padding:6px 14px;border-radius:999px;border:1px solid var(--line);background:var(--bg);transition:background .15s}}
nav.subtabs a:hover{{border-color:var(--accent)}} nav.subtabs a[aria-current]{{background:var(--accent);border-color:var(--accent);color:#fff}}
</style></head><body>{top_bar('/')}<main>
<h1>⚙️ <span class="g">הגדרות</span></h1><p class="muted" style="margin-top:0">{e(holy_status())}</p>{note}{undo_banner()}
{update_banner()}
{'<div class="item urgent">📦 נמצאו נתונים של MailBrief קודם — <a href="/?s=data#migrate">להעביר אותם לכאן</a></div>' if migrate.previous_copy() and sec != 'data' else ''}
{subnav(sec)}
{body}
<form method="post" action="/quit" style="margin-top:40px">{_t()}
<button class="ghost">⏻ סגירת MailBrief</button> <span class="muted" style="font-size:13px">הריצות המתוזמנות ימשיכו לעבוד גם כשהוא סגור.</span></form>
<script>(function(){{var map={json.dumps(ANCHORS)},h=location.hash.slice(1);
if(h&&map[h]&&map[h]!=='{sec}')location.replace('/?s='+map[h]+'#'+h);}})();</script>
</main>{extras.HTML}</body></html>'''
