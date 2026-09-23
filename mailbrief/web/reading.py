"""Reading list page."""
import collections
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def reading_page(msg=''):
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    news = [h for h in load_json(config.HISTORY_FILE, {}).values() if 'newsletters' in h['cats'] and h['date'] >= since]
    by = collections.defaultdict(list)
    for h in sorted(news, key=lambda h: h['date'], reverse=True):
        by[h.get('name') or h['sender']].append(h)
    groups = ''.join(
        f'<div class="item"><div class="t" dir="auto">{e(name)} <span class="pill">{len(hs)}</span></div><ul style="margin:6px 0 0;padding-inline-start:18px">'
        + ''.join('<li dir="auto">' + (f'<a href="{e(h["link"])}" target="_blank">{e(h.get("subject") or "—")}</a>' if h.get('link') else e(h.get('subject') or '—'))
                  + f' <span class="muted">· {e(h["date"][8:10])}/{e(h["date"][5:7])}</span></li>' for h in hs[:6])
        + (f'<li class="muted">ועוד {len(hs) - 6}...</li>' if len(hs) > 6 else '') + '</ul></div>'
        for name, hs in sorted(by.items(), key=lambda kv: -len(kv[1])))
    auto = load_json(config.SETTINGS_FILE, {}).get('auto_archive_news', False)
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    return page('רשימת קריאה', f'''{heading('📚', 'רשימת קריאה')}
<p class="muted">כל הניוזלטרים מהשבוע האחרון במקום אחד ({len(news)} מ-{len(by)} שולחים). לקרוא כשנוח — בלי שהם יסתירו את המיילים החשובים.</p>{note}
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap"><input type="hidden" name="t" value="{TOKEN}">
<button formaction="/news_archive_now">📥 להעביר לארכיון עכשיו ניוזלטרים בני 3+ ימים (Gmail)</button>
<button formaction="/news_auto" class="ghost" style="background:transparent;color:var(--ink);border:1px solid var(--line)">{'✓ ארכוב אוטומטי פעיל — לכבות' if auto else 'להפעיל ארכוב אוטומטי שבועי'}</button></form>
<p class="muted" style="font-size:13px">ארכיון ב-Gmail = יציאה מתיבת הדואר הנכנס בלבד. לא נמחק כלום, והכול נשאר ב„כל הדואר” ובחיפוש.</p>
{groups or '<p class="muted">אין ניוזלטרים מהשבוע האחרון (או שעוד לא נבנתה היסטוריה).</p>'}''')
