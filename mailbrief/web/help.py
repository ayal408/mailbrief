"""Guide, backups and health-check pages."""
import datetime as dt

from mailbrief.features.maintenance import health_checks, list_backups
from mailbrief.util import e
from mailbrief import __version__, config
from mailbrief.profile import g
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


GUIDE = [
    ('📬 התדריך השבועי', '/', 'כל יום ראשון ב-8:00 נוצר דוח של השבוע: דחוף, ממתינים לתשובה, קבלות, אבטחה, ניוזלטרים. „▶ הרצה עכשיו” — מיד.'),
    ('☀️ היום שלי', '/today', 'נפתח כשנכנסים למחשב: תאריך עברי, מזג אוויר, זמני שבת, דחוף, ממתינים, תשלומים, תזכורות ופרויקטים.'),
    ('⚡ אוטומציות', '/automations', 'כש___ ← אם___ ← אז___. יש מתכונים מוכנים וכפתור 🧪 שמראה מה היה נתפס בלי להריץ כלום.'),
    ('🏷️ כללים והעברות', '/', 'בדף הראשי: תווית לפי שולח/נושא, התראה 🔔, והעברה אוטומטית לכתובת (למשל לרו״ח).'),
    ('🧾 קבלות ואקסל', '/dashboard', 'כל קבלה נשמרת בתיקיית „קבלות” עם אקסל חודשי, שער יציג לדולר/יורו וזיהוי חיוב כפול.'),
    ('👥 לקוחות', '/clients', 'כרטיס לכל לקוח: מיילים, קבלות, ממתינים, הורדת כל הקבצים.'),
    ('🔍 חיפוש', '/search', 'חיפוש בכל התיבות יחד, והורדת כל הקבצים המצורפים מהתוצאות.'),
    ('📈 במספרים', '/stats', 'כמה מייל מגיע, מתי, ממי, ואחוז התשובות שלך.'),
    ('📚 רשימת קריאה', '/reading', 'כל הניוזלטרים של השבוע במקום אחד, וארכוב אופציונלי מהדואר הנכנס.'),
    ('🗄️ ארכיון מקומי', '/', 'קבלות ומיילים אישיים נשמרים במחשב כקבצים, עם דף חיפוש שעובד בלי אינטרנט.'),
    ('📝 תבניות וטיוטות', '/today', 'ליד כל מייל שמחכה לתשובה: בוחרים תבנית ← „📝 טיוטה” ← טיוטה מוכנה ב-Gmail.'),
    ('🏖️ מצב חופשה', '/', 'מענה אוטומטי בין תאריכים — פעם אחת לכל אדם, לא לרשימות תפוצה.'),
    ('🎣 פישינג', '/', 'מיילים מתחזים מסומנים באדום עם הסבר למה — לא ללחוץ ולא לענות.'),
    ('🕯️ שבת וחג', '/today', 'שום אוטומציה לא רצה מהדלקת נרות ועד הבדלה (לפי העיר שלך). מה שנדחה — רץ אחרי.'),
    ('⏸️ השהיה', '/', 'השהיה של כל ההתראות והאוטומציות לשעתיים / עד מחר — מהדף הראשי או מהסמל ליד השעון.'),
    ('🖱️ הסמל ליד השעון', '/', 'קליק ימני: תפריט מהיר. דאבל-קליק: „היום שלי”.'),
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
