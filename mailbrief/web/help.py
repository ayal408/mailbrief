"""Guide, backups and health-check pages."""
import datetime as dt

from mailbrief.features.maintenance import health_checks, list_backups
from mailbrief.util import e
from mailbrief import __version__, config
from mailbrief.profile import g
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


GUIDE = [
    ('📬 התדריך השבועי', '/?s=boxes', 'כל יום ראשון ב-8:00 נוצר דוח של השבוע: דחוף, ממתינים לתשובה, קבלות, אבטחה, ניוזלטרים. „▶ הרצה עכשיו” — מיד.'),
    ('☀️ היום שלי', '/today', 'נפתח כשנכנסים למחשב: תאריך עברי, מזג אוויר, זמני שבת, דחוף, ממתינים, תשלומים, חשבוניות שלא הגיעו, לקוחות שלא שילמו.'),
    ('⚡ מיון מהיר', '/triage', 'מייל אחרי מייל: בוצע, תזכורת, טיוטה, משימה, נודניק או תשובה — במקש אחד.'),
    ('⚡ אוטומציות', '/automations', 'כש___ ← אם___ ← אז___. יש מתכונים מוכנים וכפתור 🧪 שמראה מה היה נתפס בלי להריץ כלום.'),
    ('🏷️ כללים והעברות', '/?s=auto#rules', 'תווית לפי שולח/נושא, התראה 🔔, והעברה אוטומטית לכתובת (למשל לרו״ח).'),
    ('📝 תבניות עם שדות', '/?s=auto#templates', '{שם_פרטי}, {מספר_חשבונית}, {סכום} ועוד — מתמלאים לבד מהמייל שעונים עליו.'),
    ('🧾 קבלות ואקסל', '/dashboard', 'כל קבלה נשמרת בתיקיית „קבלות” עם אקסל חודשי, שער יציג לדולר/יורו וזיהוי חיוב כפול.'),
    ('🏷️ סיווג קבוע לספק', '/?s=money#vendors', 'בוחרים פעם אחת סוג הוצאה לכל ספק — וכל הקבלות שלו מסווגות כך באקסל ובייצוא.'),
    ('🧮 מע״מ חודשי', '/?s=money#vat', 'סיכום מע״מ התשומות מהקבלות של החודש, לפי סיווג.'),
    ('🧾 חשבונית שלא הגיעה', '/?s=money#missing', 'ספק שתמיד שולח עד תאריך מסוים — והחודש עוד לא? מופיע ב„היום שלי”, בסיכום היומי ובהתראה.'),
    ('📤 ייצוא לחשבשבת', '/?s=money#export', 'קובץ CSV לכל חודש עם חשבון הוצאה, כרטיס ספק ומע״מ — לקליטה בהנהלת החשבונות.'),
    ('💰 מעקב תשלומים', '/?s=clients#debts', 'חשבונית שלא שולמה: תזכורת מנומסת אחרי מועד התשלום, עד 3 פעמים, אף פעם לא בשבת.'),
    ('🎂 ימי הולדת של לקוחות', '/?s=clients#dates', 'ברכה אישית יוצאת לבד ביום עצמו ב-9:00.'),
    ('👥 לקוחות', '/clients', 'לוח לקוחות: כמה מיילים, אחוז תשובות, קשר אחרון, ממתינים ומי לא שילם.'),
    ('🧹 ניקוי הדואר הנכנס', '/?s=tidy#clean', 'מעביר לארכיון מיילים ישנים — בלי מסומנים ובלי ממתינים. שום דבר לא נמחק.'),
    ('✂️ ניוזלטרים שלא נפתחו', '/?s=tidy#unopened', 'כל מה שמגיע ואף פעם לא נפתח — וביטול של כולם יחד.'),
    ('☁️ גיבוי מוצפן ל-Drive', '/?s=data#cloud', 'עותק נעול בסיסמה שרק את/ה יודע/ת, למקרה שהמחשב מתקלקל.'),
    ('🔍 חיפוש', '/search', 'חיפוש בכל התיבות יחד, והורדת כל הקבצים המצורפים מהתוצאות.'),
    ('📈 במספרים', '/stats', 'כמה מייל מגיע, מתי, ממי, אחוז התשובות שלך — ו„השבוע שלך” מול השבוע שעבר.'),
    ('📚 ניוזלטרים', '/reading', 'כל הניוזלטרים של השבוע במקום אחד, וארכוב אופציונלי מהדואר הנכנס.'),
    ('🔕 שעות שקטות ו-VIP', '/?s=me#quiet', 'בלי התראות בלילה — חוץ מאנשים חשובים שבוחרים.'),
    ('🕯️ שבת וחג', '/today', 'שום אוטומציה לא רצה מהדלקת נרות ועד הבדלה (לפי העיר שלך). מה שנדחה — רץ אחרי.'),
    ('🤝 הבטחות במייל ששלחת', '/today', '„אחזור אליך ביום ראשון” — ונוצרת תזכורת ליום ראשון, לבד.'),
    ('⚡ קיצורי טקסט', '/?s=auto#snippets', 'כותבים ;תודה ורווח — ומקבלים פסקה שלמה, בכל תיבת טקסט.'),
    ('📎 כל הקבצים המצורפים', '/files', 'כל הקבצים מהחודש האחרון, עם סינון לפי סוג ושולח והורדה בלחיצה.'),
    ('📊 תקציב ומי זול יותר', '/?s=money#budget', 'תקציב חודשי לכל סוג הוצאה עם התראה, והשוואת מחירים בין ספקים מאותו סוג.'),
    ('🧾 מסמכים להחזר מס', '/?s=money#tax', 'הוצאות רפואיות, תרומות (סעיף 46) וביטוח חיים — בתיקייה אחת עם אקסל.'),
    ('💌 תודה עם קבלה', '/?s=clients#debts', 'כשלקוח משלם — מייל תודה עם הקבלה יוצא בלחיצה.'),
    ('📝 סיכום אחרי פגישה', '/today', 'בוקר אחרי פגישה עם אנשים מהיומן — תזכורת לשלוח להם סיכום.'),
    ('🕯️ לפני החג', '/today', 'יומיים לפני חג: מי מחכה לך, מה לתשלום ומי עוד לא שילם.'),
    ('🚨 זר מבקש כסף', '/today', 'מישהו שלא כתב לך אף פעם מבקש העברה או פרטי בנק — אזהרה אדומה.'),
    ('🔓 בדיקת דליפות', '/?s=me#leaks', 'פעם בשבוע: האם הכתובות שלך הופיעו בדליפת מידע.'),
    ('📋 דוח לשותף', '/?s=clients#share', 'כל יום ראשון — סיכום של התוויות שבוחרים, לשותף או לעובד.'),
    ('🖨️ הדפסה', '/today?print=1', '„היום שלי” על דף A4 נקי — או שמירה כ-PDF.'),
    ('♿ נגישות', 'javascript:MB.a11y()', 'הכפתור בצד המסך (או Alt+A): טקסט גדול, ניגודיות, עצירת אנימציות, ריווח, סמן גדול והקראה בקול.'),
    ('⌨️ קיצורי מקלדת', 'javascript:MB.keys()', 'G ואז אות — מעבר מהיר בין דפים (T היום, S הגדרות, Q מיון...). ? מציג את כולם.'),
    ('🖱️ הסמל ליד השעון', '/today', 'קליק ימני: תפריט מהיר. דאבל-קליק: „היום שלי”.'),
]


def help_page(msg=''):
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    guide = ''.join(f'<a href="{link}" style="text-decoration:none;color:inherit"><div class="item"><div class="t">{e(title)}</div>'
                    f'<div class="s">{e(text)}</div></div></a>' for title, link, text in GUIDE)
    backups = ''.join(
        f'<tr><td dir="ltr">{e(b[10:20])} {e(b[21:23])}:{e(b[23:25])}</td><td>{"לפני שחזור" if "before-restore" in b else "ידני" if "manual" in b else "אוטומטי"}</td>'
        f'<td><form method="post" action="/restore" style="margin:0"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="name" value="{e(b)}">'
        f'<button class="ghost" style="margin:0;font:inherit;padding:4px 10px;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer">שחזור</button></form></td></tr>'
        for b in list_backups()) or '<tr><td class="muted">עוד אין גיבויים</td></tr>'
    return page('מדריך', f'''{heading('❓', 'מדריך ותחזוקה')}{note}<p class="muted">גרסה {__version__}</p>
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap"><input type="hidden" name="t" value="{TOKEN}">
<button formaction="/health">🩺 בדיקת תקינות</button><button formaction="/backup_now">💾 גיבוי עכשיו</button></form>
<h3>מה יש כאן</h3>{guide}
<h3>💾 גיבויים</h3><p class="muted">כל הריצה השבועית שומרת גיבוי של הכללים, האוטומציות, התבניות, הקבלות וההיסטוריה (10 אחרונים). לפני כל שחזור נשמר גיבוי נוסף.</p>
<div class="scroll"><table><tbody>{backups}</tbody></table></div>
<h3 id="report">📋 משהו לא עובד?</h3>
<p class="muted">„דוח תקלה” שומר בשולחן העבודה קובץ zip עם הגרסה, פרטי Windows, בדיקת התקינות ויומן השגיאות — <b>בלי</b> תוכן של מיילים,
סיסמאות או מפתחות, והכתובות מוסתרות (a***@gmail.com). שום דבר לא נשלח לבד: {g('את מחליטה', 'אתה מחליט', 'מחליטים')} אם ולמי לשלוח אותו.</p>
<form method="post" action="/problem_report"><input type="hidden" name="t" value="{TOKEN}"><button>📋 דוח תקלה</button></form>
<h3 id="privacy">🔒 פרטיות</h3>
<ul class="muted" style="line-height:1.8">
<li>MailBrief רץ רק על המחשב {g('שלך', 'שלך', 'הזה')}. אין לו שרת, אין חשבון, ואין איסוף נתונים או סטטיסטיקות שימוש.</li>
<li>המיילים נקראים ישירות מ-Google / Microsoft / ספק הדואר אל המחשב, והכול נשמר בתיקייה <span dir="ltr">{e(config.HERE)}</span>.</li>
<li>הרשאות ההתחברות והסיסמאות נשמרות מוצפנות למשתמש Windows הזה. „הסרה” של תיבה, או ביטול הגישה ב-<a href="https://myaccount.google.com/permissions" target="_blank">myaccount.google.com/permissions</a>, מנתקים אותה.</li>
<li>פניות החוצה: ספק הדואר, יומן ומשימות Google (אם חיברת), לוח שבתות וחגים ומזג אוויר (לפי עיר בלבד), שערי מטבע של בנק ישראל, גופני התצוגה (Google Fonts), בדיקת עדכונים ב-GitHub, וקישור „ביטול מנוי” של שולח — רק כשלוחצים עליו.</li>
<li>אין AI ואין שליחת תוכן לשירות חיצוני כלשהו — כל המיון נעשה בכללים שרצים אצלך.</li></ul>
<h3 id="about">ℹ️ אודות</h3>
<p class="muted">MailBrief {__version__} · קוד פתוח ברישיון MIT ·
<a href="https://github.com/ayal408/mailbrief" target="_blank">github.com/ayal408/mailbrief</a> ·
<a href="/notices" target="_blank">רכיבי צד שלישי ורישיונות</a></p>''')


def health_page():
    rows = ''.join(f'<tr><td>{"✅" if ok else "⚠️"}</td><td>{e(area)}</td><td dir="auto">{e(detail)}</td></tr>' for area, ok, detail in health_checks())
    return page('בדיקת תקינות', f'''<p><a href="/help">→ מדריך</a></p>{heading('🩺', 'בדיקת תקינות')}
<p class="muted">{dt.datetime.now():%d/%m/%Y %H:%M}</p><div class="scroll"><table><tbody>{rows}</tbody></table></div>''')
