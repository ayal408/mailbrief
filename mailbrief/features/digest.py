"""The week in numbers — "my mail this week" compared with the week before: how much came in, how much of the personal
mail was answered, who has been waiting longest, and what was spent. For the stats page and the Sunday daily email."""
import collections
import datetime as dt

from mailbrief import config
from mailbrief.money.ledger import ils
from mailbrief.storage import load_json


def _week(history, start, end):
    rows = [h for h in history if start <= h['date'] < end]
    people = [h for h in rows if 'people' in h['cats'] and h.get('answered') is not None]
    return {'total': len(rows), 'people': len(people), 'answered': sum(1 for h in people if h['answered']),
            'news': sum(1 for h in rows if 'newsletters' in h['cats']),
            'top': collections.Counter(h.get('name') or h['sender'] for h in rows if 'people' in h['cats']).most_common(3)}


def weekly_summary(today=None, account=None):
    today = today or dt.date.today()
    start = today - dt.timedelta(days=7)
    history = [h for h in load_json(config.HISTORY_FILE, {}).values() if not account or h.get('account', '').lower() == account.lower()]
    this, last = _week(history, start.isoformat(), today.isoformat()), _week(
        history, (start - dt.timedelta(days=7)).isoformat(), start.isoformat())
    snap = load_json(config.SNAPSHOT_FILE, {})
    waiting = sorted(snap.get('waiting', []), key=lambda w: -w.get('days', 0))[:3]
    spent = sum(ils(r) or 0 for r in load_json(config.LEDGER_FILE, {}).values()
                if start.isoformat() <= r['date'] < today.isoformat() and not r.get('duplicate'))
    rate = round(100 * this['answered'] / this['people']) if this['people'] else None
    return {'this': this, 'last': last, 'rate': rate, 'waiting': waiting, 'spent': round(spent, 2),
            'change': this['total'] - last['total']}


def summary_lines(s):
    """Short lines for the email / the page."""
    lines = [f"📥 {s['this']['total']} מיילים השבוע" + (f" ({'+' if s['change'] > 0 else ''}{s['change']} משבוע שעבר)" if s['last']['total'] else '')]
    if s['rate'] is not None:
        lines.append(f"💬 ענית ל-{s['rate']}% מהמיילים האישיים ({s['this']['answered']} מתוך {s['this']['people']})")
    if s['this']['news']:
        lines.append(f"📰 {s['this']['news']} ניוזלטרים")
    if s['spent']:
        lines.append(f"🧾 הוצאות שנרשמו: ₪{s['spent']:,.0f}")
    if s['this']['top']:
        lines.append('👥 הכי הרבה קשר: ' + ', '.join(name for name, _ in s['this']['top']))
    for w in s['waiting']:
        lines.append(f"⏳ מחכה הכי הרבה: {w['from']} — {w['days']} ימים")
    return lines
