"""Search page."""

import re
from urllib.parse import quote

from mailbrief import config
from mailbrief.features.search import search_mail
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.view import dot
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


FIELD = 'width:100%;font:inherit;padding:8px 10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)'


def build_query(q):
    """The search options (from, subject, dates, attachments...) as one Gmail search. q: the page's query-string dict."""
    get = lambda k: (q.get(k, [''])[0] or '').strip()[:120]
    parts = [get('q')]
    if get('from'):
        parts.append(f'from:({get("from")})')
    if get('subject'):
        parts.append(f'subject:({get("subject")})')
    for key, op in (('after', 'after'), ('before', 'before')):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', get(key)):
            parts.append(f'{op}:{get(key).replace("-", "/")}')
    for key, term in (('files', 'has:attachment'), ('unread', 'is:unread'), ('starred', 'is:starred')):
        if get(key):
            parts.append(term)
    return ' '.join(p for p in parts if p).strip()[:300]


QUICK = [('📎 עם קבצים', 'has:attachment newer_than:30d'), ('🧾 חשבוניות', 'חשבונית OR invoice OR קבלה newer_than:60d'),
         ('📅 השבוע', 'newer_than:7d'), ('⭐ מסומנים', 'is:starred'), ('📭 לא נקראו', 'is:unread newer_than:14d'),
         ('💰 תשלום', 'לתשלום OR "דרישת תשלום" OR payment newer_than:30d')]


def pdf_results(query):
    """📄 The same words inside PDFs on this computer (receipts, clients' folders, Downloads)."""
    from mailbrief.features.pdfsearch import search
    try:
        hits = search(query)
    except Exception:
        return ''
    if not hits:
        return ''
    rows = ''.join(
        f'<div class="item"><div class="t" dir="auto">{"🧾" if h.get("scan") else "📄"} {e(h["name"])} <span class="muted" style="font-size:12px">· {e(h["label"])}'
        f'{" · נקרא מסריקה" if h.get("scan") else ""}</span></div>'
        + (f'<div class="s" dir="auto">…{e(h["snippet"])}…</div>' if h['snippet'] else '')
        + f'<form method="post" action="/open_file" style="margin:6px 0 0"><input type="hidden" name="t" value="{TOKEN}">'
          f'<input type="hidden" name="path" value="{e(h["path"])}"><input type="hidden" name="q" value="{e(query)}"><button class="ghost" style="margin:0;padding:4px 12px">פתיחה</button></form></div>'
        for h in hits)
    return f'<h3>📄 בתוך קבצים במחשב ({len(hits)})</h3><p class="muted" style="font-size:13px">קבלות, תיקיות לקוחות והורדות — נמצאה התאמה בתוך הקובץ עצמו. קבלות סרוקות ותמונות: מספרים ואנגלית בלבד.</p>{rows}'


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
                        + (f'<div class="scroll"><table><thead><tr><th>תאריך</th><th>מאת</th><th>נושא</th><th>תיבה</th></tr></thead><tbody>{rows}</tbody></table></div>' if found else '')
                        + pdf_results(query))
    saved = load_json(config.SETTINGS_FILE, {}).get('saved_searches') or []
    chips = ''.join(
        f'<span class="pill" style="display:inline-flex;gap:6px;align-items:center;font-size:14px;padding:4px 10px">'
        f'<a href="/search?q={quote(q)}" style="text-decoration:none">🔖 {e(q)}</a>'
        f'<form method="post" action="/search_forget" style="margin:0;display:inline"><input type="hidden" name="t" value="{TOKEN}">'
        f'<input type="hidden" name="q" value="{e(q)}"><button style="all:unset;cursor:pointer;color:var(--muted)" title="הסרה">✕</button></form></span> '
        for q in saved)
    keep = (f'<form method="post" action="/search_save" style="margin:0 0 10px"><input type="hidden" name="t" value="{TOKEN}">'
            f'<input type="hidden" name="q" value="{e(query)}"><button class="ghost" style="padding:6px 14px;background:transparent;color:var(--ink);'
            f'border:1px solid var(--line)">🔖 שמירת החיפוש</button></form>') if query and query not in saved else ''
    return page('חיפוש', f'''{heading('🔍', 'חיפוש בכל התיבות')}{f'<div style="margin:6px 0">{chips}</div>' if chips else ''}
<form method="get" action="/search" style="margin:16px 0">
<div style="display:flex;gap:8px"><input type="search" name="q" value="{e(query)}" autofocus placeholder="מה לחפש? למשל: חשבונית, שם של לקוח">
<button>חיפוש</button></div>
<details style="margin-top:8px"{' open' if not query else ''}><summary style="cursor:pointer;font-weight:600">⚙️ אפשרויות חיפוש</summary>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;margin-top:8px">
<label style="margin:0;font-size:14px">מאת (שם או כתובת)<input type="text" name="from" style="{FIELD}"></label>
<label style="margin:0;font-size:14px">בנושא<input type="text" name="subject" style="{FIELD}"></label>
<label style="margin:0;font-size:14px">מתאריך<input type="date" name="after" style="{FIELD}"></label>
<label style="margin:0;font-size:14px">עד תאריך<input type="date" name="before" style="{FIELD}"></label></div>
<div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:14px">
<label style="margin:0;display:flex;gap:6px;align-items:center"><input type="checkbox" name="files" value="1"> 📎 רק עם קבצים מצורפים</label>
<label style="margin:0;display:flex;gap:6px;align-items:center"><input type="checkbox" name="unread" value="1"> 📭 רק שלא נקראו</label>
<label style="margin:0;display:flex;gap:6px;align-items:center"><input type="checkbox" name="starred" value="1"> ⭐ רק מסומנים</label></div>
</details></form>
<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px"><span class="muted" style="font-size:13px;align-self:center">חיפוש מהיר:</span>
{''.join(f'<a class="pill" style="text-decoration:none;font-size:14px;padding:4px 12px" href="/search?q={quote(q)}">{label}</a>' for label, q in QUICK)}</div>
{keep}<p class="muted" style="font-size:13px">האפשרויות עובדות בתיבות Gmail (בתיבות אחרות — חיפוש לפי המילים בלבד).</p>{results_html}''')
