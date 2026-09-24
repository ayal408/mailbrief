"""Dashboard and statistics pages."""
import collections
import datetime as dt

from mailbrief import config
from mailbrief.features.digest import summary_lines, weekly_summary
from mailbrief.mail.classify import CATS
from mailbrief.money.ledger import find_subscriptions, ils
from mailbrief.storage import load_json
from mailbrief.view import current_account, mine
from mailbrief.util import e, money, month_back
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


HE_DAYS = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי']


def heatmap(rows):
    """Day of week × hour (Sunday–Friday, 7:00–22:00) — how much mail comes in."""
    grid = collections.Counter()
    for h in rows:
        if h.get('hour'):
            grid[((dt.date.fromisoformat(h['date']).weekday() + 1) % 7, int(h['hour']))] += 1
    peak = max(grid.values(), default=1) or 1
    hours = range(7, 23)
    head = '<tr><th></th>' + ''.join(f'<th style="font-size:11px;padding:2px">{hr}</th>' for hr in hours) + '</tr>'
    body = ''.join(
        f'<tr><td style="font-size:12px;white-space:nowrap">{name}</td>' + ''.join(
            f'<td title="{name} {hr:02d}:00 — {grid[(d, hr)]} מיילים" style="padding:0;height:22px;min-width:20px;'
            f'background:color-mix(in srgb,var(--accent) {round(grid[(d, hr)] / peak * 100)}%,transparent);border:1px solid var(--bg)"></td>'
            for hr in hours) + '</tr>' for d, name in enumerate(HE_DAYS))
    return f'<table style="width:auto;border-collapse:collapse">{head}{body}</table>'


def answer_tip(rows):
    """Two fixed times to answer mail: the hour after the two busiest hours of the day."""
    by_hour = collections.Counter(int(h['hour']) for h in rows if h.get('hour') and 7 <= int(h['hour']) <= 20)
    if len(by_hour) < 3:
        return ''
    top = sorted(hr + 1 for hr, _ in by_hour.most_common(2))
    return f'💡 כדאי לשריין זמן קבוע לענות ב-{top[0]:02d}:00 וב-{top[1]:02d}:00 — אחרי שעות השיא, כשרוב המייל כבר הגיע.'


def stats_page():
    cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    box = current_account()
    rows = [h for h in load_json(config.HISTORY_FILE, {}).values() if h['date'] >= cutoff and mine(h, current=box)]
    if not rows:
        return page('המייל שלי במספרים', f'''{heading('📈', 'המייל שלי במספרים')}<p>עוד אין מספיק היסטוריה.</p>
<form method="post" action="/build_history"><input type="hidden" name="t" value="{TOKEN}"><button>📥 בניית היסטוריה של 30 יום (כדקה)</button></form>''')

    def bars(counter, labels=None, top=None):
        items = list(counter.items()) if labels is None else [(k, counter.get(k, 0)) for k in labels]
        if top:
            items = sorted(items, key=lambda kv: -kv[1])[:top]
        peak = max((v for _, v in items), default=1) or 1
        return ''.join(f'<tr><td style="width:170px" dir="auto">{e(str(k))}</td><td><div class="bar" style="width:{v / peak * 100:.1f}%"></div></td>'
                       f'<td style="width:50px">{v}</td></tr>' for k, v in items)

    total = len(rows)
    cats = collections.Counter(c for h in rows for c in h['cats'])
    names = {c: f'{CATS[c][0]} {CATS[c][1]}' for c in CATS}
    cat_counts = collections.Counter({names[c]: n for c, n in cats.items() if c in names})
    other = sum(1 for h in rows if not h['cats'])
    if other:
        cat_counts['📭 אחר'] = other
    days_he = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']
    weekday = collections.Counter(days_he[dt.date.fromisoformat(h['date']).weekday()] for h in rows)
    hours = collections.Counter(f'{h["hour"]}:00' for h in rows if h.get('hour'))
    senders = collections.Counter(h.get('name') or h['sender'] for h in rows)
    news = [h for h in rows if 'newsletters' in h['cats']]
    top_news = collections.Counter(h.get('name') or h['sender'] for h in news).most_common(1)
    people = [h for h in rows if 'people' in h['cats'] and h.get('answered') is not None]
    answered = sum(1 for h in people if h['answered'])
    busiest_day = weekday.most_common(1)[0][0] if weekday else '—'
    busiest_hour = hours.most_common(1)[0][0] if hours else '—'
    accounts = collections.Counter(h['account'] for h in rows)
    heat = heatmap(rows)

    facts = [f'בממוצע מגיעים אלייך <b>{total / 30:.1f}</b> מיילים ביום.',
             f'<b>{len(news) / total:.0%}</b> מהמייל שלך הם ניוזלטרים והתראות אוטומטיות.' if total else '',
             f'השולח הכי חרוץ: <b dir="auto">{e(top_news[0][0])}</b> — {top_news[0][1]} מיילים בחודש. אפשר לבטל בלשונית <a href="/reading">📰 ניוזלטרים</a>.' if top_news else '',
             f'היום הכי עמוס: <b>{busiest_day}</b>; השעה הכי עמוסה: <b dir="ltr">{busiest_hour}</b>.',
             f'ענית ל-<b>{answered}</b> מתוך <b>{len(people)}</b> מיילים מאנשים ({answered / len(people):.0%}).' if people else '']
    kpis = ''.join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for k, v in [
        ('מיילים ב-30 יום', total), ('ביום בממוצע', f'{total / 30:.1f}'),
        ('מאנשים', cats.get('people', 0)), ('ניוזלטרים', cats.get('newsletters', 0))])
    return page('המייל שלי במספרים', f'''{heading('📈', 'המייל שלי במספרים')}<p class="muted">30 הימים האחרונים · {len(accounts)} תיבות</p>
<div class="kpis">{kpis}</div>
<h3>📊 השבוע שלך</h3><div class="item">{"<br>".join(e(line) for line in summary_lines(weekly_summary(account=box)))}</div>
<div class="item">{"<br>".join(f for f in facts if f)}</div>
<h3>לפי סוג</h3><div class="scroll"><table><tbody>{bars(cat_counts, top=10)}</tbody></table></div>
<h3>🔥 מתי מגיע הכי הרבה מייל</h3>
<p class="muted">כל משבצת = שעה ביום בשבוע. ככל שהצבע חזק יותר — יותר מיילים. {e(answer_tip(rows))}</p>
<div class="scroll">{heat}</div>
<h3>לפי יום בשבוע</h3><div class="scroll"><table><tbody>{bars(weekday, labels=['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'])}</tbody></table></div>
<h3>לפי שעה</h3><div class="scroll"><table><tbody>{bars(hours, labels=[f"{h:02d}:00" for h in range(6, 24)])}</tbody></table></div>
<h3>10 השולחים הכי פעילים</h3><div class="scroll"><table><tbody>{bars(senders, top=10)}</tbody></table></div>
<h3>לפי תיבה</h3><div class="scroll"><table><tbody>{bars(accounts)}</tbody></table></div>
<form method="post" action="/build_history" style="margin-top:20px"><input type="hidden" name="t" value="{TOKEN}"><button class="ghost" style="background:transparent;color:var(--ink);border:1px solid var(--line)">🔄 רענון היסטוריה (30 יום)</button></form>''')


def dashboard_page():
    box = current_account()
    ledger = {k: r for k, r in load_json(config.LEDGER_FILE, {}).items() if mine(r, current=box)}
    history = {k: h for k, h in load_json(config.HISTORY_FILE, {}).items() if mine(h, current=box)}
    labels = [r['label'] for r in load_json(config.RULES_FILE, [])]
    month = month_back(0)
    priced = [r for r in ledger.values() if ils(r) is not None]
    this_month = [r for r in ledger.values() if r['date'].startswith(month)]
    subs = find_subscriptions(ledger)
    doubles = [r for r in ledger.values() if r.get('duplicate')]
    kpis = ''.join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for k, v in [
        ('הוצאות החודש (₪)', money(sum(ils(r) for r in priced if r['date'].startswith(month)))),
        ('קבלות החודש', len(this_month)), ('מנויים קבועים', len(subs)),
        ('מיילים החודש', sum(1 for h in history.values() if h['date'].startswith(month)))])

    months = [month_back(i) for i in range(5, -1, -1)]
    totals = {m: sum(ils(r) for r in priced if r['date'].startswith(m)) for m in months}
    top = max(totals.values()) or 1
    bars = ''.join(f'<tr><td dir="ltr" style="width:80px">{m}</td><td><div class="bar" style="width:{max(totals[m] / top * 100, 0.5):.1f}%"></div></td>'
                   f'<td dir="ltr" style="width:100px">{money(totals[m])}</td></tr>' for m in months)

    books = {}
    for r in this_month:
        if ils(r) is not None:
            books[r['book']] = books.get(r['book'], 0) + ils(r)
    book_rows = ''.join(f'<tr><td>{e(k)}</td><td dir="ltr">{money(v)}</td></tr>'
                        for k, v in sorted(books.items(), key=lambda kv: -kv[1])) or '<tr><td class="muted">אין עדיין</td></tr>'

    all_labels = sorted(set(labels) | {l for h in history.values() for l in h.get('rules', [])})
    client_rows = ''.join(
        f'<tr><td>🏷️ {e(label)}</td>'
        f'<td>{sum(1 for h in history.values() if label in h.get("rules", []) and h["date"].startswith(month))}</td>'
        f'<td>{sum(1 for r in this_month if label in r.get("rules", []))}</td>'
        f'<td dir="ltr">{money(sum(ils(r) for r in this_month if label in r.get("rules", []) and ils(r)))}</td></tr>'
        for label in all_labels) or '<tr><td colspan="4" class="muted">מגדירים לקוחות דרך „הכללים שלי” (למשל: השולח מכיל @client.co.il ← תווית „לקוח כהן”)</td></tr>'

    sub_rows = ''.join(
        f'<tr><td dir="auto">{e(s["vendor"])}{" <span class=\"pill bad\">חדש</span>" if s["new"] else ""}</td>'
        f'<td dir="ltr">{e(s["currency"])}{s["amount"] if s["amount"] is not None else "—"}</td><td>{e(s["last"])}</td>'
        f'<td>{s["months"]}</td><td>{e(s["book"])}</td></tr>' for s in subs) or '<tr><td colspan="5" class="muted">יתמלא אחרי ייבוא קבלות</td></tr>'

    double_rows = ''.join(
        f'<div class="item urgent">⚠️ <b dir="auto">{e(r["vendor"])}</b> — {e(r["currency"])}{r["amount"]} ב-{e(r["date"])} וגם ב-{e(r["duplicate"])}. '
        f'כדאי לבדוק שלא חויבת פעמיים.</div>' for r in doubles if r['date'] > r['duplicate'])
    return page('לוח בקרה', f'''{heading('📊', 'לוח בקרה')}<p class="muted">{month} · מבוסס על הקבלות וההיסטוריה ש-MailBrief שמר מקומית ·
סכומים במטבע זר מומרים לפי השער היציג של בנק ישראל ביום החשבונית</p>
{double_rows}<div class="kpis">{kpis}</div>
<h3>💸 הוצאות בשקלים — 6 חודשים</h3><div class="scroll"><table><tbody>{bars}</tbody></table></div>
<h3>📂 לפי סיווג — החודש</h3><div class="scroll"><table><tbody>{book_rows}</tbody></table></div>
<h3>👥 לקוחות ותוויות — החודש</h3><div class="scroll"><table><thead><tr><th>תווית</th><th>מיילים</th><th>קבלות</th><th>סכום ₪</th></tr></thead><tbody>{client_rows}</tbody></table></div>
<h3>💳 מנויים וחיובים קבועים</h3><div class="scroll"><table><thead><tr><th>ספק</th><th>חיוב אחרון</th><th>תאריך</th><th>חודשים</th><th>סיווג</th></tr></thead><tbody>{sub_rows}</tbody></table></div>''')
