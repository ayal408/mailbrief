"""📅 From a reply to a meeting: when someone answers "Sunday at 10:00 works for me", the email gets a button that puts
the meeting in Google Calendar with them invited. Only a reply that names a time AND agrees to it — never a guess
from a date that is just mentioned somewhere."""
import datetime as dt
import re

from mailbrief.features.contacts import own_part


DAYS = {'ראשון': 6, 'שני': 0, 'שלישי': 1, 'רביעי': 2, 'חמישי': 3, 'שישי': 4,
        'sunday': 6, 'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4}
AGREE = re.compile(r'מתאים|מתאימה|נוח לי|בסדר|אשמח|סגור|מאשר|מאשרת|נקבע|נתראה|יאללה|works|fine|confirm|see you|perfect|great', re.I)
TIME = r'(?:ב|בשעה\s*|ב-|at\s*)?\s*(\d{1,2})[:.](\d{2})'
WITH_DAY = re.compile(r'(?:יום\s+)?(ראשון|שני|שלישי|רביעי|חמישי|שישי|sunday|monday|tuesday|wednesday|thursday|friday)'
                      r'(?:\s*,?\s*(?:ה-?)?(\d{1,2})[./](\d{1,2}))?\s*,?\s*' + TIME, re.I)
WITH_DATE = re.compile(r'(?:ב-?|on\s*)?(\d{1,2})[./](\d{1,2})(?:[./]\d{2,4})?\s*,?\s*' + TIME, re.I)
TOMORROW = re.compile(r'(מחר|tomorrow)\s*,?\s*' + TIME, re.I)


def find_meeting(text, received):
    """(start datetime, the sentence) — or (None, '') when the reply doesn't agree to a specific time.
    received: when the reply arrived (a weekday means the next one after it)."""
    own = own_part(text or '')[:3000]
    for line in re.split(r'[\n.!?]+', own):
        if not AGREE.search(line):
            continue
        start = None
        m = WITH_DAY.search(line)
        if m:
            if m[2]:
                start = _date(int(m[2]), int(m[3]), received)
            else:
                ahead = (DAYS[m[1].lower()] - received.weekday()) % 7 or 7
                start = received.date() + dt.timedelta(days=ahead)
            hour, minute = int(m[4]), int(m[5])
        else:
            m = TOMORROW.search(line)
            if m:
                start, hour, minute = received.date() + dt.timedelta(days=1), int(m[2]), int(m[3])
            else:
                m = WITH_DATE.search(line)
                if m:
                    start, hour, minute = _date(int(m[1]), int(m[2]), received), int(m[3]), int(m[4])
        if start and 0 <= hour <= 23 and 0 <= minute <= 59 and 6 <= hour <= 22:
            when = dt.datetime.combine(start, dt.time(hour, minute)).replace(tzinfo=received.tzinfo)
            if received < when <= received + dt.timedelta(days=60):
                return when, re.sub(r'\s+', ' ', line).strip()[:140]
    return None, ''


def _date(day, month, received):
    try:
        found = dt.date(received.year, month, day)
    except ValueError:
        return None
    return found if found >= received.date() else _next_year(found)


def _next_year(day):
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return None


def event(title, start, attendee, minutes=60, notes=''):
    """A Google Calendar event with the other side invited (Google sends them the invitation)."""
    from mailbrief.features.google_apps import TZ
    end = start + dt.timedelta(minutes=minutes)
    naive = lambda d: d.replace(tzinfo=None).isoformat(timespec='minutes')
    return {'summary': title, 'description': notes,
            'start': {'dateTime': naive(start), 'timeZone': TZ}, 'end': {'dateTime': naive(end), 'timeZone': TZ},
            'attendees': [{'email': attendee}] if attendee else []}


def add_meeting(title, start, attendee, notes=''):
    from mailbrief.features import google_apps
    acc = google_apps.gapps_account()
    if not acc:
        raise RuntimeError('צריך קודם לחבר את Google Calendar (הגדרות ← חיבורים)')
    google_apps.forget_cache()
    return google_apps.api(acc, 'POST', 'calendar/v3/calendars/primary/events', {'sendUpdates': 'all'}, event(title, start, attendee, notes=notes))
