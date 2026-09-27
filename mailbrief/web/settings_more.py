"""Settings blocks: 💚 income · 🔁 recurring emails · 🔒 PIN · 🧪 backup check."""
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.token import TOKEN


FIELD = 'font:inherit;padding:8px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)'


def _t():
    return f'<input type="hidden" name="t" value="{TOKEN}">'


def _h(anchor, title):
    return f'<h2 id="{anchor}" style="scroll-margin-top:80px">{title}</h2>'


def _account_options():
    return ''.join(f'<option>{e(a["email"])}</option>' for a in load_json(config.ACCOUNTS_FILE, [])) or '<option value="">(אין תיבה)</option>'


def income_block():
    from mailbrief.features import income
    from mailbrief.money.books import vat_summary
    month = dt.date.today().strftime('%Y-%m')
    total, by = income.month_total(month)
    spent = vat_summary(month)['total']
    rows = ''.join(
        f'<tr><td style="white-space:nowrap">{r["date"][8:10]}/{r["date"][5:7]}</td><td>{e(r["service"])}</td><td dir="auto">{e(r.get("payer") or "—")}</td>'
        f'<td dir="ltr" style="text-align:right;white-space:nowrap">{e(r["currency"])}{r["amount"]:,g}</td>'
        f'<td>{"✓ חשבונית סומנה כשולמה" if r.get("debt") else ""}</td>'
        f'<td><form method="post" action="/income_remove" style="margin:0">{_t()}<input type="hidden" name="key" value="{e(k)}">'
        f'<button class="ghost" style="margin:0;padding:3px 10px" title="זה לא תשלום אליי">✕</button></form></td></tr>'
        for k, r in income.month_rows(month)[:30])
    services = ' · '.join(f'{e(s)} ₪{v:,.0f}' for s, v in sorted(by.items(), key=lambda kv: -kv[1]))
    left = total - spent
    return f'''{_h('income', '💚 הכנסות החודש')}
<p class="muted">הודעות תשלום מ-Bit, PayBox, PayPal והבנקים („העביר/ה לך ₪350”) נאספות לבד בבדיקה השעתית. כשהסכום והשם מתאימים
לחשבונית פתוחה במעקב התשלומים — היא מסומנת כשולמה (אפשר לבטל ב-↩️).</p>
<div class="kpis"><div class="kpi"><b style="color:var(--good)">₪{total:,.0f}</b><span>נכנס החודש</span></div>
<div class="kpi"><b>₪{spent:,.0f}</b><span>יצא החודש (קבלות)</span></div>
<div class="kpi"><b style="color:{'var(--good)' if left >= 0 else 'var(--bad)'}">₪{left:,.0f}</b><span>נשאר</span></div></div>
{f'<p class="muted" style="font-size:13px">{services}</p>' if services else ''}
{f'<div class="scroll"><table><tbody>{rows}</tbody></table></div>' if rows else '<p class="muted">עוד לא זוהו תשלומים החודש.</p>'}'''


def recurring_block():
    from mailbrief.features import recurring
    rows = ''.join(
        f'<tr><td><b dir="auto">{e(r["subject"])}</b><div class="muted" dir="ltr" style="font-size:12px;text-align:right">{e(r["to"])}</div></td>'
        f'<td>{e(recurring.when_text(r))}{"" if r.get("on") else " · ⏸️ מושהה"}</td><td style="white-space:nowrap">'
        f'<form method="post" action="/recurring_set" style="display:inline;margin:0">{_t()}<input type="hidden" name="id" value="{e(r["id"])}">'
        f'<button name="action" value="{"off" if r.get("on") else "on"}" class="ghost" style="margin:0;padding:4px 10px">{"⏸️ השהיה" if r.get("on") else "▶️ הפעלה"}</button> '
        f'<button name="action" value="delete" class="ghost" style="margin:0;padding:4px 10px">מחיקה</button></form></td></tr>'
        for r in recurring.items())
    days = ''.join(f'<option value="{i}">יום {d}</option>' for i, d in enumerate(recurring.DAYS[:6]))
    dates = ''.join(f'<option value="{i}">ב-{i} לחודש</option>' for i in range(1, 29))
    return f'''{_h('recurring', '🔁 מיילים חוזרים')}
<p class="muted">מגדירים פעם אחת — וכל חודש או כל שבוע נשלח עותק מהתיבה שלך. אף פעם לא בשבת ובחג (מחכה למוצאי).
אפשר לכתוב בנושא ובתוכן {{חודש}}, {{היום}}, {{שנה}}.</p>
{f'<div class="scroll"><table><tbody>{rows}</tbody></table></div>' if rows else ''}
<form method="post" action="/recurring_add" class="box" style="display:grid;gap:8px;margin-top:10px">{_t()}
<div style="display:flex;gap:8px;flex-wrap:wrap"><select name="account" style="{FIELD}">{_account_options()}</select>
<input type="text" name="to" dir="ltr" required placeholder="אל: client@example.com" style="flex:1;min-width:200px;{FIELD}"></div>
<input type="text" name="subject" required maxlength="300" placeholder="נושא — למשל: תזכורת תשלום לחודש {{חודש}}" style="{FIELD}">
<textarea name="body" rows="4" placeholder="התוכן" style="{FIELD}"></textarea>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="freq" value="monthly" checked> כל חודש</label>
<select name="mday" style="{FIELD}">{dates}</select>
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="radio" name="freq" value="weekly"> כל שבוע</label>
<select name="wday" style="{FIELD}">{days}</select>
<span>בשעה</span><input type="time" name="at" value="09:00" style="{FIELD}"></div>
<div><button style="margin:0">➕ הוספה</button></div></form>'''


def pin_block():
    from mailbrief.features import lock
    on = lock.enabled()
    off_button = '<button name="action" value="off" class="ghost" style="margin:0">ביטול הקוד</button>' if on else ''
    lock_now = f'<form method="post" action="/lock" style="margin-top:6px">{_t()}<button class="ghost" style="margin:0">🔒 לנעול עכשיו</button></form>' if on else ''
    return f'''{_h('pin', '🔒 קוד לפתיחת MailBrief')}
<p class="muted">מסך פרטיות: מי שיושב ליד המחשב לא יראה את המיילים שלך בלי הקוד. ננעל שוב אחרי זמן בלי שימוש.
(זו לא הצפנה — מי שמחובר למשתמש שלך ב-Windows עדיין יכול להגיע לתיקיית הנתונים.) שכחת את הקוד?
הפעלה של <code dir="ltr">MailBrief.exe --reset-pin</code> מבטלת אותו.</p>
<form method="post" action="/pin_set" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">{_t()}
<input type="password" name="pin" inputmode="numeric" maxlength="8" placeholder="{'קוד חדש' if on else '4–8 ספרות'}" autocomplete="new-password" style="width:140px;{FIELD}">
<span>נעילה אחרי</span><input type="number" name="idle" min="1" max="240" value="{lock.idle_minutes()}" style="width:80px;{FIELD}"><span>דקות בלי שימוש</span>
<button style="margin:0">{'🔒 החלפת קוד' if on else '🔒 הפעלה'}</button>{off_button}</form>{lock_now}'''


def backup_check_block():
    check = load_json(config.SETTINGS_FILE, {}).get('backup_check') or {}
    lines = ''.join(f'<li>{e(x)}</li>' for x in check.get('lines', []))
    color = 'var(--good)' if check.get('ok') else 'var(--bad)'
    state = (f'<p><b style="color:{color}">{"✓ תקין" if check.get("ok") else "⚠️ יש בעיה"}</b> · נבדק {e(check.get("at", ""))}</p><ul>{lines}</ul>'
             if check else '<p class="muted">עוד לא נבדק.</p>')
    return f'''{_h('backupcheck', '🧪 בדיקת גיבוי')}
<p class="muted">פעם בחודש MailBrief פותח את הגיבוי האחרון כמו בשחזור (בלי לשחזר כלום) ובודק שכל קובץ תקין — וגם את הגיבוי ב-Drive,
אם הוא פעיל. גיבוי פגום — נוצר מיד גיבוי חדש, ומגיעה התראה.</p>
{state}
<form method="post" action="/backup_check">{_t()}<button class="ghost">🧪 לבדוק עכשיו</button></form>'''


def blocked_block():
    from mailbrief.features.blocking import blocked
    rows = ''.join(
        f'<tr><td dir="ltr" style="text-align:right">{e(b["who"])}</td><td class="muted">מ-{e(b["since"][8:10])}/{e(b["since"][5:7])}</td>'
        f'<td><form method="post" action="/unblock" style="margin:0">{_t()}<input type="hidden" name="who" value="{e(b["who"])}">'
        f'<button class="ghost" style="margin:0;padding:4px 10px">ביטול החסימה</button></form></td></tr>' for b in blocked())
    return f'''{_h('blocked', '🚫 שולחים חסומים')}
<p class="muted">מיילים חדשים מהם יוצאים לבד מהדואר הנכנס (נשארים בתיבה, בארכיון) ולא מופיעים ב„היום שלי” ובהתראות.
חוסמים בלחיצה על 🚫 ליד מייל ב„היום שלי”, או כאן. אפשר כתובת או דומיין שלם (@shop.com).</p>
{f'<div class="scroll"><table><tbody>{rows}</tbody></table></div>' if rows else ''}
<form method="post" action="/block" style="display:flex;gap:8px;margin-top:8px">{_t()}
<input type="text" name="who" dir="ltr" required placeholder="spam@example.com או @example.com" style="flex:1;{FIELD}">
<button style="margin:0">🚫 חסימה</button></form>'''
