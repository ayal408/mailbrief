"""The newsletters tab: unsubscribe, this week's reading list, and archiving — all in one place."""
import collections
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.view import current_account, dot, mine
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def reading_page(msg=''):
    box = current_account()
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    news = [h for h in load_json(config.HISTORY_FILE, {}).values()
            if 'newsletters' in h['cats'] and h['date'] >= since and mine(h, current=box)]
    by = collections.defaultdict(list)
    for h in sorted(news, key=lambda h: h['date'], reverse=True):
        by[h.get('name') or h['sender']].append(h)
    groups = ''.join(
        f'<div class="item"><div class="t" dir="auto">{e(name)} <span class="pill">{len(hs)}</span></div><ul style="margin:6px 0 0;padding-inline-start:18px">'
        + ''.join('<li dir="auto">' + dot(h.get('account', '')) + (f'<a href="{e(h["link"])}" target="_blank">{e(h.get("subject") or "—")}</a>' if h.get('link') else e(h.get('subject') or '—'))
                  + f' <span class="muted">· {e(h["date"][8:10])}/{e(h["date"][5:7])}</span></li>' for h in hs[:6])
        + (f'<li class="muted">ועוד {len(hs) - 6}...</li>' if len(hs) > 6 else '') + '</ul></div>'
        for name, hs in sorted(by.items(), key=lambda kv: -len(kv[1])))

    unsubs = {k: u for k, u in load_json(config.UNSUBS_FILE, {}).items() if mine(u, current=box)}
    open_ones = [(k, u) for k, u in unsubs.items() if not u.get('done')]
    rows = ''.join(
        f'<tr><td dir="auto">{dot(u.get("account", ""))}<b>{e(u.get("name") or u["sender"])}</b>'
        f'<div class="muted" dir="ltr" style="font-size:12px;text-align:right">{e(u["sender"])} → {e(u["account"])}</div></td>'
        f'<td>{u.get("count", 0)}</td><td>'
        + (f'<span style="color:var(--good)">✓ בוטל {e(u["done"])}</span>' if u.get('done') else
           f'<form method="post" action="/unsubscribe" style="margin:0"{"" if u.get("one_click") else " target=_blank"}>'
           f'<input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="id" value="{k}"><input type="hidden" name="back" value="/reading">'
           f'<button class="ghost" style="margin:0;padding:6px 14px">{"⚡ ביטול בלחיצה" if u.get("one_click") else "ביטול ↗"}</button></form>')
        + '</td></tr>'
        for k, u in sorted(unsubs.items(), key=lambda kv: (bool(kv[1].get('done')), -kv[1].get('count', 0)))[:60]
    ) or '<tr><td colspan="3" class="muted">יופיעו כאן אחרי הריצה הראשונה</td></tr>'
    auto = load_json(config.SETTINGS_FILE, {}).get('auto_archive_news', False)
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    return page('ניוזלטרים', f'''{heading('📰', 'ניוזלטרים')}{note}
<div class="kpis"><div class="kpi"><b>{len(news)}</b><span>ניוזלטרים השבוע</span></div>
<div class="kpi"><b>{len(by)}</b><span>שולחים</span></div>
<div class="kpi"><b>{len(open_ones)}</b><span>אפשר לבטל</span></div>
<div class="kpi"><b>{sum(1 for u in unsubs.values() if u.get('done'))}</b><span>כבר בוטלו</span></div></div>

<h3>✂️ ביטול מנויים</h3>
<p class="muted">דרך הקישור הרשמי של השולח. ⚡ = ביטול מיידי מכאן; „↗” = נפתח דף הביטול של השולח לאישור.</p>
<div class="scroll"><table><thead><tr><th>שולח</th><th>הודעות</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>

<h3>📥 פחות רעש בתיבה</h3>
<form method="post" style="display:flex;gap:8px;flex-wrap:wrap"><input type="hidden" name="t" value="{TOKEN}">
<button formaction="/news_archive_now">📥 להעביר לארכיון עכשיו ניוזלטרים בני 3+ ימים (Gmail)</button>
<button formaction="/news_auto" class="ghost">{'✓ ארכוב אוטומטי פעיל — לכבות' if auto else 'להפעיל ארכוב אוטומטי שבועי'}</button></form>
<p class="muted" style="font-size:13px">ארכיון ב-Gmail = יציאה מתיבת הדואר הנכנס בלבד. לא נמחק כלום, והכול נשאר ב„כל הדואר” ובחיפוש.</p>

<h3>📚 רשימת קריאה — השבוע</h3>
<p class="muted">כל הניוזלטרים מהשבוע האחרון במקום אחד — לקרוא כשנוח, בלי שהם יסתירו את המיילים החשובים.</p>
{groups or '<p class="muted">אין ניוזלטרים מהשבוע האחרון (או שעוד לא נבנתה היסטוריה).</p>'}''')
