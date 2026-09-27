"""ℹ️ About: the version, updates, what's new, the license and the privacy promise — in one place."""
import sys

from mailbrief import __version__, config
from mailbrief.util import e
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def about_page(msg=''):
    from mailbrief.features.update import can_self_update, update_available
    try:
        rel = update_available()
    except Exception:
        rel = None
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    kind = ('מותקן' if config.INSTALLED else 'winget' if config.MANAGED else 'נייד (בלי התקנה)') if getattr(sys, 'frozen', False) else 'מקוד המקור'
    if rel:
        update = (f'<div class="item" style="border-color:var(--accent)">🎁 <b>גרסה חדשה {e(rel["version"])} זמינה</b> · '
                  f'<a href="{e(rel["page"])}" target="_blank">מה חדש בה?</a>'
                  + (f'<form method="post" action="/update" style="display:inline;margin:0 8px"><input type="hidden" name="t" value="{TOKEN}">'
                     '<button style="margin:0;padding:7px 16px">✨ עדכון עכשיו</button></form>' if can_self_update() else
                     ' · <code dir="ltr">winget upgrade mailbrief</code>') + '</div>')
    else:
        update = '<p>✓ זו הגרסה האחרונה. MailBrief בודק עדכונים לבד ומודיע כשיש חדשה.</p>'
    return page('אודות', f'''{heading('ℹ️', 'אודות MailBrief')}{note}
<div class="kpis"><div class="kpi"><b>{e(__version__)}</b><span>הגרסה שלך</span></div>
<div class="kpi"><b style="font-size:20px">{e(kind)}</b><span>סוג ההתקנה</span></div>
<div class="kpi"><b style="font-size:20px">MIT</b><span>קוד פתוח, חינם</span></div></div>
{update}
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
