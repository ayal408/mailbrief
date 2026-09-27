"""📅 Free times from Google Calendar for the coming week, as a short text for a reply: "I'm available Sunday 10:00…".
Only working days and hours (Sunday–Thursday, by default 9:00–17:00), never Shabbat / Yom Tov, and never right now."""
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json


DAYS = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']


def hours():
    cfg = load_json(config.SETTINGS_FILE, {}).get('work_hours') or {}
    return int(cfg.get('start', 9)), int(cfg.get('end', 17)), int(cfg.get('length', 60))


def busy_ranges(events):
    """[(start, end)] from calendar rows (all-day events don't block)."""
    out = []
    for ev in events:
        if not ev.get('day') or ev.get('time') in ('', 'כל היום') or not ev.get('end_iso'):
            continue
        start = dt.datetime.fromisoformat(f'{ev["day"]}T{ev["time"]}').astimezone()
        end = dt.datetime.fromisoformat(ev['end_iso']).astimezone()
        out.append((start, end))
    return out


def free_slots(events, now=None, days=7, count=6, holy=None):
    """Up to `count` free slots of the working length, spread over the days (at most 2 a day)."""
    from mailbrief.features.calendar import holy_windows
    start_h, end_h, length = hours()
    now = now or dt.datetime.now().astimezone()
    holy = holy_windows() if holy is None else holy
    busy = busy_ranges(events)
    step, need = dt.timedelta(minutes=30), dt.timedelta(minutes=length)
    out = []
    for n in range(days + 1):
        day = (now + dt.timedelta(days=n)).date()
        if day.weekday() in (4, 5):                          # Friday, Shabbat
            continue
        t = dt.datetime.combine(day, dt.time(start_h)).astimezone()
        close = dt.datetime.combine(day, dt.time(end_h)).astimezone()
        today_count = 0
        while t + need <= close and today_count < 2 and len(out) < count:
            end = t + need
            clash = any(s < end and t < e for s, e in busy) or any(s < end and t < e for s, e in holy or [])
            if t >= now + dt.timedelta(hours=2) and not clash:
                out.append(t)
                today_count += 1
                t = end + dt.timedelta(hours=2)                  # spread the day's offers apart
                continue
            t += step
        if len(out) >= count:
            break
    return out


def slots_text(slots):
    if not slots:
        return ''
    lines = [f'• יום {DAYS[s.weekday()]} {s:%d/%m} בשעה {s:%H:%M}' for s in slots]
    return 'אני זמינ/ה באחד מהזמנים האלה:\n' + '\n'.join(lines) + '\nמה נוח לך?'


def suggest():
    """(text, error) — from the connected calendar."""
    from mailbrief.features import google_apps
    acc = google_apps.gapps_account()
    if not acc:
        return '', 'צריך קודם לחבר את Google Calendar (הגדרות ← חיבורים)'
    try:
        events = google_apps.events_on(acc, dt.date.today(), 9)
    except Exception as exc:
        from mailbrief.net import explain
        return '', explain(exc)
    text = slots_text(free_slots(events))
    return (text, '') if text else ('', 'לא נמצאו זמנים פנויים בשבוע הקרוב')
