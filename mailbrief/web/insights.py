"""The "30 days at a glance" page."""
from mailbrief import config
from mailbrief.profile import g
from mailbrief.storage import load_json
from mailbrief.util import e, money
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def insights_page(msg='', run=False):
    data = load_json(config.INSIGHTS_FILE, {})
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    if not data or run:
        accounts = load_json(config.ACCOUNTS_FILE, [])
        start = (f'<form method="post" action="/first_look" id="go"><input type="hidden" name="t" value="{TOKEN}">'
                 f'<button style="font-size:17px">🔎 {g("תראי לי", "תראה לי", "להציג")} מה יש</button></form>')
        auto = '<script>setTimeout(function(){ var f = document.getElementById("go"); f.requestSubmit ? f.requestSubmit() : f.submit(); }, 600);</script>' if run else ''
        return page('30 הימים שלך', f'''{heading('🔎', '30 הימים שלך במבט אחד')}{note}
<div style="text-align:center;padding:30px 10px">
<div style="font-size:64px" class="floaty">🔍</div>
<p style="font-size:18px;max-width:560px;margin:10px auto">{"MailBrief יעבור על 30 הימים האחרונים ויראה: כמה עולים המנויים שלך בחודש, אילו ניוזלטרים אפשר לבטל בלחיצה, ומי מחכה לתשובה." if accounts else "קודם צריך לחבר תיבת מייל — בדף ההגדרות."}</p>
<p class="muted">לוקח דקה-שתיים. שום דבר לא משתנה בתיבה — רק קוראים.</p>
{start if accounts else '<a href="/"><button>⚙️ לחיבור תיבה</button></a>'}</div>{auto if accounts else ''}''')

    def kpi(value, label, sub=''):
        return f'<div class="kpi"><b>{value}</b><span>{label}</span>{f"<div class=muted style=font-size:12px>{sub}</div>" if sub else ""}</div>'
    letters = data['newsletters']
    news_rows = ''.join(
        f'<tr><td dir="auto"><b>{e(n["name"])}</b><div class="muted" dir="ltr" style="font-size:12px;text-align:right">{e(n["sender"])}</div></td>'
        f'<td>{n["count"]}</td><td><form method="post" action="/unsubscribe" style="margin:0"{"" if n["one_click"] else " target=_blank"}>'
        f'<input type="hidden" name="t" value="{TOKEN}">'
        f'<input type="hidden" name="id" value="{e(n["id"])}"><input type="hidden" name="back" value="/insights">'
        f'<button class="ghost" style="margin:0;padding:6px 14px">{"⚡ ביטול בלחיצה" if n["one_click"] else "ביטול ↗"}</button></form></td></tr>'
        for n in letters[:15])
    subs_rows = ''.join(
        f'<tr><td dir="auto">{e(s["vendor"])}</td><td dir="ltr">{e(s["currency"])}{s["amount"] if s["amount"] is not None else "—"}</td>'
        f'<td>{"≈ " + money(s["ils"]) if s["ils"] is not None else ""}</td><td class="muted">{s["months"]} חודשים</td></tr>'
        for s in data['subs'])
    waiting_rows = ''.join(
        '<li dir="auto">' + (f'<a href="{e(w["link"])}" target="_blank">{e(w["subject"][:70])}</a>' if w['link'] else e(w['subject'][:70]))
        + f' <span class="muted">— {e(w["from"])} · {w["days"]} ימים</span></li>' for w in data['waiting'])
    tip = ('💡 הכי משתלם להתחיל מהניוזלטרים: כמה לחיצות — ותיבה שקטה יותר מחר בבוקר.' if len(letters) >= 5 else
           '💡 כדאי להציץ ברשימת המנויים — לפעמים יש שם משהו ששכחנו.' if data['subs'] else
           '💡 התיבה שלך די מסודרת! אפשר להגדיר אוטומציה ראשונה בלשונית „אוטומציות”.')
    return page('30 הימים שלך', f'''{heading('🔎', '30 הימים שלך במבט אחד')}{note}
<p class="muted">{data["days"]} הימים האחרונים · עודכן {e(data["at"])}</p>
<div class="kpis">
{kpi(f'{data["emails"]:,}', 'מיילים', f'מ-{data["senders"]:,} שולחים')}
{kpi(len(letters), 'ניוזלטרים לביטול', f'{data["newsletter_emails"]:,} מיילים בחודש')}
{kpi(money(data["subs_month_ils"]) if data["subs"] else '—', 'מנויים בחודש', f'{len(data["subs"])} מנויים קבועים')}
{kpi(data["waiting_count"], 'מחכים לתשובה', 'מאנשים אמיתיים')}
</div>
<div class="item" style="font-size:16px">{tip}</div>
{f'<div class="item bad">⚠️ {e(" · ".join(data["errors"]))}</div>' if data["errors"] else ''}
<h3>📰 ניוזלטרים — אפשר לבטל מכאן</h3>
{f'<div class="scroll"><table><thead><tr><th>שולח</th><th>החודש</th><th></th></tr></thead><tbody>{news_rows}</tbody></table></div>' if news_rows else '<p class="muted">לא נמצאו ניוזלטרים עם קישור ביטול ✨</p>'}
<h3>💳 מנויים וחיובים קבועים</h3>
{f'<div class="scroll"><table><tbody>{subs_rows}</tbody></table></div>' if subs_rows else '<p class="muted">עוד לא זוהו חיובים חוזרים (צריך קבלות מלפחות שני חודשים).</p>'}
<h3>⏳ מחכים לתשובה ממך</h3>
<ul>{waiting_rows or '<li class="muted">אין — הכול נענה ✨</li>'}</ul>
<form method="post" action="/first_look" style="margin-top:24px"><input type="hidden" name="t" value="{TOKEN}">
<button class="ghost">🔄 לרענן את הסקירה</button> <a href="/today" style="margin-inline-start:10px">☀️ להמשיך ל„היום שלי” ←</a></form>''')
