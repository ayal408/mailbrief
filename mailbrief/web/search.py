"""Search page."""

from mailbrief.features.search import search_mail
from mailbrief.util import e
from mailbrief.view import dot
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def search_page(query):
    results_html = ''
    if query:
        found, errors = search_mail(query)
        rows = ''.join(
            f'<tr><td>{e(r["when"].strftime("%d/%m/%y") if r["when"] else "")}</td><td dir="auto">{e(r["from"])}</td><td dir="auto">'
            + (f'<a href="{e(r["link"])}" target="_blank">{e(r["subject"])}</a>' if r['link'] else e(r['subject']))
            + f'</td><td dir="ltr" class="muted" style="font-size:12px">{dot(r["account"])}{e(r["account"])}</td></tr>' for r in found)
        download = (f'<form method="post" action="/search_download" style="margin:8px 0"><input type="hidden" name="t" value="{TOKEN}">'
                    f'<input type="hidden" name="q" value="{e(query)}"><button>📥 הורדת כל הקבצים המצורפים מהתוצאות</button></form>') if found else ''
        results_html = (''.join(f'<div class="err">⚠️ {e(x)}</div>' for x in errors)
                        + f'<p class="muted">{len(found)} תוצאות (עד 40 האחרונות מכל תיבה)</p>' + download
                        + (f'<div class="scroll"><table><thead><tr><th>תאריך</th><th>מאת</th><th>נושא</th><th>תיבה</th></tr></thead><tbody>{rows}</tbody></table></div>' if found else ''))
    return page('חיפוש', f'''{heading('🔍', 'חיפוש בכל התיבות')}
<form method="get" action="/search" style="display:flex;gap:8px;margin:16px 0"><input type="search" name="q" value="{e(query)}" autofocus placeholder="למשל: חשבונית, שם של לקוח, from:bank.co.il">
<button>חיפוש</button></form><p class="muted" style="font-size:13px">בתיבות Gmail אפשר להשתמש בכל תחביר החיפוש של Gmail (from:, has:attachment, after:2026/01/01...).</p>{results_html}''')
