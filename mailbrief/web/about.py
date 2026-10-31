"""ℹ️ About: the version, updates, what's new, the license and the privacy promise — in one place."""
import sys

from mailbrief import __version__, config
from mailbrief.util import e
from mailbrief.web.layout import heading, page


def about_page(msg=''):
    from mailbrief.features.update import update_available
    try:
        rel = update_available()
    except Exception:
        rel = None
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    from mailbrief.features.auto_update import enabled, read_state
    from mailbrief.features.update import version_tuple
    from mailbrief.web.token import TOKEN
    state = read_state()
    pending = state.get('version', '')
    pending = pending if isinstance(pending, str) and version_tuple(pending) > version_tuple(__version__) else ''
    automatic = ('<h3>עדכונים אוטומטיים</h3><p class="muted">העדכון יורד ברקע, נבדק מול קובץ ההפצה הרשמי ומותקן בהפעלה המלאה הבאה של התוכנה. '
                 'החלון לא נסגר באמצע העבודה. אחרי ההתקנה התוכנה נפתחת מחדש.</p>')
    if config.INSTALLED:
        automatic += (f'<form method="post" action="/auto_update"><input type="hidden" name="t" value="{TOKEN}">'
                      f'<label><input type="checkbox" name="enabled" value="1"{" checked" if enabled() else ""}> הורדה והתקנה אוטומטיות של עדכונים</label> '
                      '<button>שמירת העדפה</button></form>')
        if pending:
            automatic += f'<p>גרסה {e(pending)} ' + ('כבר הופעלה להתקנה; אם לא עודכנה, אפשר להתקין ידנית מהקישור למעלה.' if state.get('launched') else 'הורדה וממתינה להפעלה הבאה.') + '</p>'
        if state.get('error'):
            automatic += f'<p class="err">{e(state["error"])} · אפשר להמשיך להשתמש בגרסה הנוכחית או להוריד ידנית.</p>'
    else:
        automatic += '<p class="muted">התקנה אוטומטית זמינה בעותק שהותקן באמצעות MailBrief-Setup.exe. עותק נייד או קוד מקור מתעדכנים ידנית.</p>'
    kind = ('מותקן' if config.INSTALLED else 'winget' if config.MANAGED else 'נייד (בלי התקנה)') if getattr(sys, 'frozen', False) else 'מקוד המקור'
    if rel:
        update = (f'<div class="item" style="border-color:var(--accent)">🎁 <b>גרסה חדשה {e(rel["version"])} זמינה</b> · '
                  f'<a href="{e(rel["page"])}" target="_blank">מה חדש בה?</a>'
                  + f' · <a href="{e(rel["url"])}" style="margin:0 8px">הורדה והתקנה</a>'
                  + ' · <code dir="ltr">winget upgrade mailbrief</code></div>')
    else:
        update = '<p>✓ זו הגרסה האחרונה. MailBrief בודק עדכונים לבד ומודיע כשיש חדשה.</p>'
    return page('אודות', f'''{heading('ℹ️', 'אודות MailBrief')}{note}
<div class="kpis"><div class="kpi"><b>{e(__version__)}</b><span>הגרסה שלך</span></div>
<div class="kpi"><b style="font-size:20px">{e(kind)}</b><span>סוג ההתקנה</span></div>
<div class="kpi"><b style="font-size:20px">MIT</b><span>קוד פתוח, חינם</span></div></div>
{update}
{automatic}
<p><a href="https://github.com/ayal408/mailbrief/releases" target="_blank">📜 כל הגרסאות ומה השתנה</a> ·
<a href="https://ayal408.github.io/mailbrief/" target="_blank">🌐 האתר</a> ·
<a href="https://github.com/ayal408/mailbrief/issues" target="_blank">🐞 דיווח על בעיה</a> ·
<a href="/help#report">📋 דוח תקלה</a></p>
<h3>🔒 פרטיות — בקצרה</h3>
<p class="muted">MailBrief רץ רק על המחשב שלך: אין שרת, אין חשבון ואין איסוף נתונים. בלי AI — כל המיון בכללים שרצים אצלך.
<a href="/help#privacy">הפירוט המלא</a> · <a href="https://ayal408.github.io/mailbrief/privacy.html" target="_blank">מדיניות הפרטיות</a></p>
<h3>📦 רכיבים</h3>
<p class="muted">Python, pywebview (החלון), ועוד רכיבי קוד פתוח — <a href="/notices" target="_blank">רשימה ורישיונות</a>.
הנתונים שלך נשמרים ב-<span dir="ltr">{e(config.HERE)}</span>.</p>''', '/help')
