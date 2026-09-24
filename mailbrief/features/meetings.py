"""Around the calendar: the morning after a meeting with other people — a reminder to send them a summary;
and two days before a Yom Tov — what is still open (people waiting for you, payments due over the holiday, clients who owe)."""
import datetime as dt

from mailbrief import config
from mailbrief.features import google_apps
from mailbrief.features.calendar import holy_windows
from mailbrief.features.reminders import add_reminder
from mailbrief.storage import load_json


# ---- after a meeting ---------------------------------------------------------------------------------------------------

def meeting_followups(state, today=None):
    """Once a day: yesterday's meetings that had other participants -> a reminder at 09:00 today. Returns how many."""
    today = today or dt.date.today()
    if state.get('_meetings') == today.isoformat():
        return 0
    acc = google_apps.gapps_account()
    if not acc:
        return 0
    state['_meetings'] = today.isoformat()
    made = 0
    for ev in google_apps.events_on(acc, today - dt.timedelta(days=1)):
        if not ev.get('attendees') or ev['time'] == 'כל היום':
            continue
        who = ', '.join(ev['attendees'][:3]) + (f' ועוד {len(ev["attendees"]) - 3}' if len(ev['attendees']) > 3 else '')
        add_reminder(0, f'📝 לשלוח סיכום פגישה: {ev["title"]}', who, ev.get('link', ''), acc['email'],
                     note='מה סוכם, מי עושה מה ועד מתי')
        made += 1
    return made


# ---- before a holiday -------------------------------------------------------------------------------------------------

def _holiday_name(start, end):
    data = (load_json(config.CACHE_FILE, {}).get('holy') or {}).get('data') or {}
    for i in data.get('items', []):
        if i.get('category') == 'holiday' and i.get('yomtov') and start.date() <= dt.date.fromisoformat(i['date'][:10]) <= end.date():
            return i.get('hebrew') or i.get('title', '')
    return ''


def next_holiday(now=None, within_days=2):
    """(start, end, name) of a Yom Tov window that begins within the next days — not a plain Shabbat."""
    now = now or dt.datetime.now().astimezone()
    for start, end in holy_windows(saved_only=True) or []:
        if now < start <= now + dt.timedelta(days=within_days):
            plain_shabbat = start.weekday() == 4 and (end - start) < dt.timedelta(hours=30)
            if not plain_shabbat:
                return start, end, _holiday_name(start, end)
    return None


def holiday_prep(now=None):
    """What to close before the holiday. None when no Yom Tov is two days away."""
    found = next_holiday(now)
    if not found:
        return None
    start, end, name = found
    snap = load_json(config.SNAPSHOT_FILE, {})
    until = (end + dt.timedelta(days=3)).date().isoformat()
    due = [d for d in snap.get('due', []) if d.get('due') and d['due'] <= until]
    from mailbrief.features.clientcare import debts
    owed = [d for d in debts() if d['status'] == 'open']
    return {'start': start, 'end': end, 'name': name, 'waiting': snap.get('waiting', [])[:8], 'due': due[:8],
            'awaiting': snap.get('awaiting', [])[:5], 'owed': owed[:5]}


def holiday_lines(prep):
    lines = []
    if prep['waiting']:
        lines.append(f"⏳ {len(prep['waiting'])} מחכים לתשובה ממך — " + ', '.join(w['from'] for w in prep['waiting'][:3]))
    if prep['due']:
        lines.append(f"💸 {len(prep['due'])} תשלומים עד אחרי החג — " + ', '.join(d['from'] for d in prep['due'][:3]))
    if prep['owed']:
        lines.append(f"💰 {len(prep['owed'])} לקוחות עוד לא שילמו — " + ', '.join(d['name'] for d in prep['owed'][:3]))
    if prep['awaiting']:
        lines.append(f"📤 {len(prep['awaiting'])} שיחות שמחכות לתשובה מאחרים")
    return lines
