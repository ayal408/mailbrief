"""Google Calendar and Google Tasks for a connected Google mailbox (same sign-in, two extra permissions)."""
import datetime as dt
import json
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from mailbrief import config
from mailbrief.mail.accounts import APPS_SCOPES
from mailbrief.mail.oauth import access_token
from mailbrief.net import _PUBLIC_TLS
from mailbrief.storage import load_json, save_json


SCOPES = ' '.join(APPS_SCOPES)


API_PAGES = {
    'calendar': 'https://console.cloud.google.com/apis/library/calendar-json.googleapis.com',
    'tasks': 'https://console.cloud.google.com/apis/library/tasks.googleapis.com',
}


TZ = 'Asia/Jerusalem'


_TOKENS = {}    # email -> (access token, expires at) — in memory only


def gapps_account(accounts=None):
    """The Google mailbox that holds Calendar/Tasks access: the one chosen in settings, else the first connected."""
    accounts = load_json(config.ACCOUNTS_FILE, []) if accounts is None else accounts
    linked = [a for a in accounts if a.get('auth') == 'google' and a.get('gapps')]
    chosen = load_json(config.SETTINGS_FILE, {}).get('gapps_account', '').lower()
    return next((a for a in linked if a['email'].lower() == chosen), linked[0] if linked else None)


def _token(acc):
    hit = _TOKENS.get(acc['email'])
    if hit and hit[1] > time.time():
        return hit[0]
    token = access_token(acc)
    _TOKENS[acc['email']] = (token, time.time() + 50 * 60)
    return token


def api(acc, method, path, params=None, body=None):
    url = 'https://www.googleapis.com/' + path + ('?' + urlencode(params) if params else '')
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': f'Bearer {_token(acc)}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_PUBLIC_TLS) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        which = 'Google Tasks' if path.startswith('tasks/') else 'Google Calendar'
        if exc.code == 403 and ('accessNotConfigured' in detail or 'has not been used' in detail or 'disabled' in detail):
            raise RuntimeError(f'צריך להפעיל את {which} API בפרויקט ב-Google Cloud (הקישור בדף ההגדרות)') from None
        if exc.code in (401, 403):
            _TOKENS.pop(acc['email'], None)
            raise RuntimeError(f'אין הרשאה ל-{which} — צריך ללחוץ שוב „חיבור יומן ומשימות”') from None
        raise RuntimeError(f'{which}: שגיאה {exc.code}') from None


def _day_bounds(day):
    start = dt.datetime.combine(day, dt.time()).astimezone()
    return start.isoformat(), (start + dt.timedelta(days=1)).isoformat()


def events_on(acc, day=None, days=1):
    day = day or dt.date.today()
    start = _day_bounds(day)[0]
    end = _day_bounds(day + dt.timedelta(days=days - 1))[1]
    data = api(acc, 'GET', 'calendar/v3/calendars/primary/events',
               {'timeMin': start, 'timeMax': end, 'singleEvents': 'true', 'orderBy': 'startTime', 'maxResults': 25 * days})
    rows = []
    for ev in data.get('items', []):
        if ev.get('status') == 'cancelled':
            continue
        begin = ev.get('start', {})
        rows.append({'title': ev.get('summary') or '(בלי כותרת)', 'link': ev.get('htmlLink', ''),
                     'day': (begin.get('dateTime') or begin.get('date') or '')[:10],
                     'time': begin['dateTime'][11:16] if 'dateTime' in begin else 'כל היום',
                     'end': ev.get('end', {}).get('dateTime', '')[11:16], 'where': ev.get('location', ''),
                     'end_iso': ev.get('end', {}).get('dateTime') or ev.get('end', {}).get('date', ''),
                     'attendees': [a['email'] for a in ev.get('attendees', []) if a.get('email') and not a.get('self')
                                   and a.get('responseStatus') != 'declined' and not a.get('resource')]})
    return rows


def open_tasks(acc):
    data = api(acc, 'GET', 'tasks/v1/lists/@default/tasks', {'showCompleted': 'false', 'showHidden': 'false', 'maxResults': 100})
    rows = [{'id': t['id'], 'title': t.get('title') or '(בלי כותרת)', 'due': (t.get('due') or '')[:10],
             'notes': t.get('notes', ''), 'link': t.get('webViewLink', '')}
            for t in data.get('items', []) if t.get('status') != 'completed' and (t.get('title') or '').strip()]
    return sorted(rows, key=lambda t: (not t['due'], t['due']))


def task_body(title, notes='', due=''):
    body = {'title': title[:1000], 'notes': notes[:8000]}
    if due:
        body['due'] = f'{due}T00:00:00.000Z'      # Tasks keeps the date only
    return body


def event_body(title, day, notes='', at=None, minutes=60):
    """All-day event on `day`, or a timed one when `at` ("HH:MM") is given."""
    if at:
        start = dt.datetime.combine(day, dt.time.fromisoformat(at))
        return {'summary': title, 'description': notes,
                'start': {'dateTime': start.isoformat(), 'timeZone': TZ},
                'end': {'dateTime': (start + dt.timedelta(minutes=minutes)).isoformat(), 'timeZone': TZ}}
    return {'summary': title, 'description': notes,
            'start': {'date': day.isoformat()}, 'end': {'date': (day + dt.timedelta(days=1)).isoformat()}}


def add_task(acc, title, notes='', due=''):
    forget_cache()
    return api(acc, 'POST', 'tasks/v1/lists/@default/tasks', body=task_body(title, notes, due))


def complete_task(acc, task_id):
    forget_cache()
    return api(acc, 'PATCH', f"tasks/v1/lists/@default/tasks/{quote(task_id, safe='')}", body={'status': 'completed'})


def add_event(acc, title, day, notes='', at=None):
    forget_cache()
    return api(acc, 'POST', 'calendar/v3/calendars/primary/events', body=event_body(title, day, notes, at))


def import_invite(acc, resource):
    """Add a meeting invitation; importing by its iCalUID means a second click doesn't create a copy."""
    forget_cache()
    return api(acc, 'POST', 'calendar/v3/calendars/primary/events/import', body=resource)


def forget_cache():
    cache = load_json(config.CACHE_FILE, {})
    if cache.pop('gapps', None) is not None:
        save_json(config.CACHE_FILE, cache)


def today_overview(max_age_min=5):
    """Today's events and open tasks for "My day", cached for a few minutes. None = not connected."""
    acc = gapps_account()
    if not acc:
        return None
    cache = load_json(config.CACHE_FILE, {})
    hit = cache.get('gapps')
    if hit and hit.get('account') == acc['email'] and hit.get('day') == dt.date.today().isoformat() \
            and time.time() - hit['at'] < max_age_min * 60:
        return hit
    result = {'account': acc['email'], 'day': dt.date.today().isoformat(), 'at': time.time()}
    for key, fetch in (('events', events_on), ('tasks', open_tasks)):
        try:
            result[key] = fetch(acc)
        except Exception as exc:
            result[key + '_error'] = str(exc)
    if 'events' in result or 'tasks' in result:
        cache['gapps'] = result
        save_json(config.CACHE_FILE, cache)
    return result
