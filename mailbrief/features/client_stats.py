"""📊 Per-client email statistics (last 90 days): who writes most, how fast you answer each one, who waits now —
and a short "worth your attention first" list with the reason. Only numbers from the history on this computer."""
import datetime as dt
import statistics

from mailbrief.features.history import client_groups


def client_stats(today=None, current=''):
    today = today or dt.date.today()
    out = []
    for key, g in client_groups().items():
        rows = [h for h in g['emails'] if not current or (h.get('account') or '').lower() == current.lower()]
        if not rows:
            continue
        hours = [h['reply_hours'] for h in rows if h.get('reply_hours') is not None]
        people = [h for h in rows if 'people' in h.get('cats', [])]
        answered = [h for h in people if h.get('answered') is not None]
        waiting = [h for h in people if h.get('answered') is False]
        first = min(h['date'] for h in rows)
        weeks = max(1.0, (today - dt.date.fromisoformat(first)).days / 7)
        last = max(h['date'] for h in rows)
        s = {'key': key, 'name': g['name'], 'emails': len(rows), 'per_week': round(len(rows) / weeks, 1),
             'answered_pct': round(100 * sum(1 for h in answered if h['answered']) / len(answered)) if answered else None,
             'median_hours': round(statistics.median(hours), 1) if hours else None,
             'waiting': len(waiting), 'oldest_wait': max(((today - dt.date.fromisoformat(h['date'])).days for h in waiting), default=0),
             'last': last, 'silent_days': (today - dt.date.fromisoformat(last)).days}
        s['score'], s['why'] = priority(s)
        out.append(s)
    return sorted(out, key=lambda s: -s['emails'])


def priority(s):
    """(score, reason) — someone who writes a lot, waits for you now, or usually gets a slow answer comes first."""
    score, why = 0.0, []
    if s['waiting']:
        score += 3 * s['waiting'] + min(s['oldest_wait'], 14) / 2
        why.append(f'{s["waiting"]} מיילים מחכים לתשובה' + (f' (הוותיק {s["oldest_wait"]} ימים)' if s['oldest_wait'] > 1 else ''))
    if s['median_hours'] is not None and s['median_hours'] > 24 and s['per_week'] >= 1:
        score += 2
        why.append(f'בדרך כלל עונים אחרי {fmt_hours(s["median_hours"])}')
    if s['per_week'] >= 3:
        score += 1.5
        why.append(f'כותב/ת הרבה — {s["per_week"]:g} בשבוע')
    if s['answered_pct'] is not None and s['answered_pct'] < 60 and s['emails'] >= 4:
        score += 1
        why.append(f'רק {s["answered_pct"]}% מהמיילים נענו')
    return round(score, 1), ' · '.join(why)


def fmt_hours(h):
    if h is None:
        return '—'
    if h < 1:
        return f'{max(1, round(h * 60))} דק׳'
    if h < 48:
        return f'{h:g} שע׳'
    return f'{round(h / 24, 1):g} ימים'


def top_priorities(stats, n=3):
    return [s for s in sorted(stats, key=lambda s: -s['score']) if s['score'] > 0][:n]
