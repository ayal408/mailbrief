"""Local sent-mail and follow-up history; delivery is distinct from reading."""
from urllib.parse import urlencode

from mailbrief import config, view
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


DELIVERY = {'sent': 'נשלח לשרת הדואר', 'waiting': 'ממתין לשליחה', 'sending': 'שליחה בתהליך',
            'failed': 'השליחה נכשלה', 'partial': 'שליחה חלקית', 'uncertain': 'תוצאת השליחה אינה ידועה',
            'cancelled': 'השליחה בוטלה'}
REPLY = {'awaiting': 'לא נמצאה תשובה בבדיקה האחרונה', 'answered': 'זוהתה תשובה',
         'unknown': 'מענה טרם נבדק', 'followed': 'נשלחה תזכורת המשך'}


def tracking_rows(account=''):
    known = {a.lower() for a in view.emails()}
    rows = {}

    def key(item, fallback):
        return ((item.get('account') or '').lower(), item.get('message_id') or fallback)

    def allowed(item):
        address = (item.get('account') or '').lower()
        return address in known and (not account or address == account.lower())

    def row(item, delivery):
        to = item.get('to') or item.get('to_email') or ''
        return {'account': item['account'], 'to': ', '.join(to) if isinstance(to, list) else to,
                'subject': item.get('subject') or '(ללא נושא)', 'at': item.get('sent') or item.get('send_at') or '',
                'delivery': delivery, 'reply': 'unknown', 'error': item.get('error') or item.get('retry') or '',
                'link': item.get('link') or '', 'days': item.get('days')}

    for item in load_json(config.OUTBOX_FILE, []):
        if allowed(item):
            rows[key(item, item.get('id', ''))] = row(item, item.get('status', 'uncertain'))
    for item in load_json(config.AUTOFOLLOW_FILE, []):
        if not allowed(item):
            continue
        k = key(item, item.get('id', ''))
        current = rows.setdefault(k, row(item, 'sent'))
        status = item.get('status')
        if status == 'answered':
            current['reply'] = 'answered'
        elif status == 'sent':
            current['reply'] = 'followed'
        # "waiting" here is an unperformed future check, not proof of no reply.
    snapshot = load_json(config.SNAPSHOT_FILE, {})
    for item in snapshot.get('awaiting', []):
        if not allowed(item):
            continue
        current = rows.setdefault(key(item, item.get('subject', '')), row(item, 'sent'))
        if current['reply'] == 'unknown':
            current.update(reply='awaiting', days=item.get('days'), link=item.get('link') or current['link'])
    return sorted(rows.values(), key=lambda r: r['at'], reverse=True)


def tracking_page(account='', status='all', query=''):
    rows = tracking_rows(account)
    statuses = [('all', 'הכול'), ('awaiting', 'מחכים לתשובה'), ('answered', 'התקבלה תשובה'),
                ('waiting', 'ממתינים לשליחה'), ('sent', 'נשלחו'), ('issues', 'בעיות בשליחה')]
    if status not in {s[0] for s in statuses}:
        status = 'all'
    def matches(r):
        state = (status == 'all' or status in ('awaiting', 'answered') and r['reply'] == status
                 or status == 'issues' and r['delivery'] in ('failed', 'partial', 'uncertain')
                 or status in ('waiting', 'sent') and r['delivery'] == status)
        return state and query.casefold() in ' '.join((r['subject'], r['to'], r['account'])).casefold()
    visible = [r for r in rows if matches(r)]
    options = lambda items, chosen: ''.join(f'<option value="{e(v)}"{" selected" if v == chosen else ""}>{e(label)}</option>' for v, label in items)
    controls = (f'<form method="get" action="/sent-tracking" style="display:flex;gap:8px;flex-wrap:wrap;margin:16px 0">'
                f'<label>תיבה <select name="a">{options([("*", "כל התיבות")] + [(a, a) for a in view.emails()], account or "*")}</select></label>'
                f'<label>מצב <select name="status">{options(statuses, status)}</select></label>'
                f'<input type="search" name="q" aria-label="חיפוש בנושא או בנמען" placeholder="חיפוש בנושא או בנמען" value="{e(query)}" style="flex:1;min-width:180px">'
                '<button>סינון ורענון תצוגה</button></form>')
    cards = []
    for r in visible[:200]:
        link = r['link']
        title = (f'<a href="{e(link)}" target="_blank" rel="noopener">{e(r["subject"])}</a>'
                 if link.startswith('https://mail.google.com/') else e(r['subject']))
        issue = r['delivery'] in ('failed', 'partial', 'uncertain')
        remind = ''
        if r['delivery'] == 'sent' and r['reply'] != 'answered':
            fields = {'t': TOKEN, 'days': '1', 'subject': 'מעקב: ' + r['subject'], 'from': r['to'],
                      'link': link, 'account': r['account'], 'back': '/sent-tracking'}
            remind = ('<form method="post" action="/remind" style="margin-top:8px">'
                      + ''.join(f'<input type="hidden" name="{k}" value="{e(v)}">' for k, v in fields.items())
                      + '<button class="ghost">⏰ להזכיר לי מחר</button></form>')
        cards.append(f'<article class="item{" bad" if issue else ""}"><div class="t">{title}</div>'
                     f'<div class="m" dir="auto">אל: {e(r["to"])} · מאת: {e(r["account"])}</div>'
                     f'<div class="m">{e(r["at"])} · {e(DELIVERY.get(r["delivery"], "מצב לא ידוע"))}</div>'
                     f'<div>{e(REPLY[r["reply"]])}' + (f' · {e(str(r["days"]))} ימים' if r['days'] is not None else '') + '</div>'
                     + (f'<p class="err">{e(str(r["error"]))}</p>' if r['error'] else '') + remind + '</article>')
    snap = load_json(config.SNAPSHOT_FILE, {})
    counts = [('הודעות במעקב', len(rows)), ('מחכים לתשובה', sum(r['reply'] == 'awaiting' for r in rows)),
              ('תשובות שזוהו', sum(r['reply'] == 'answered' for r in rows))]
    body = (heading('📤', 'מעקב הודעות שנשלחו') + '<p class="muted">היסטוריית השליחה דרך MailBrief ומעקבי ההמשך שנשמרו במחשב. '
            '״נשלח״ מציין מסירה לשרת הדואר, ואינו אישור מסירה לנמען או אישור קריאה. '
            'אין כאן היסטוריה מלאה של כל הדואר שנשלח; הסרת הודעה מרשימת ההמתנה אינה מוכיחה שהתקבלה תשובה.</p>'
            f'<p class="muted">עדכון תמונת המצב האחרונה: {e(str(snap.get("at") or "טרם בוצעה"))}. הנתונים מתעדכנים בבדיקות הדואר הרגילות.</p>'
            + '<div class="kpis">' + ''.join(f'<div class="kpi"><b>{n}</b><span>{label}</span></div>' for label, n in counts) + '</div>'
            + controls + f'<p class="muted">{len(visible)} תוצאות' + (' · מוצגות 200 האחרונות' if len(visible) > 200 else '') + '</p>'
            + (''.join(cards) or '<div class="item">אין הודעות במעקב שמתאימות למסננים. הודעות ומעקבים יופיעו כאן לאחר שליחה או בדיקת דואר.</div>')
            + f'<a href="/inbox?{urlencode({"a": account or "*"})}">חזרה לתיבת הדואר</a>')
    return page('מעקב הודעות שנשלחו', body, '/sent-tracking')
