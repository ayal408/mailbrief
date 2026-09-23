"""Meeting invitations: the text/calendar (iCalendar) part that Outlook, Zoom, Teams and Google attach to invites."""
import datetime as dt
import hashlib
import re


WINDOWS_ZONES = {'israel standard time': 'Asia/Jerusalem', 'jerusalem standard time': 'Asia/Jerusalem',
                 'utc': 'UTC', 'gmt standard time': 'Europe/London', 'eastern standard time': 'America/New_York',
                 'pacific standard time': 'America/Los_Angeles', 'central europe standard time': 'Europe/Budapest',
                 'w. europe standard time': 'Europe/Berlin'}


def _unfold(text):
    return re.sub(r'\r?\n[ \t]', '', text).splitlines()


def _unescape(value):
    return re.sub(r'\\([nN,;\\])', lambda m: '\n' if m.group(1) in 'nN' else m.group(1), value).strip()


def _when(params, value):
    """(ISO date/time as written, time zone name, all day). UTC times become local time."""
    value = value.strip()
    if 'VALUE=DATE' in params.upper() or re.fullmatch(r'\d{8}', value):
        return dt.datetime.strptime(value[:8], '%Y%m%d').date().isoformat(), '', True
    if value.endswith('Z'):
        moment = dt.datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc).astimezone()
        return moment.replace(tzinfo=None).isoformat(timespec='minutes'), 'Asia/Jerusalem', False
    zone = re.search(r'TZID=("?)([^;:"]+)\1', params)
    zone = zone.group(2).strip() if zone else ''
    zone = zone if '/' in zone else WINDOWS_ZONES.get(zone.lower(), 'Asia/Jerusalem')
    return dt.datetime.strptime(value[:15], '%Y%m%dT%H%M%S').isoformat(timespec='minutes'), zone, False


def parse_ics(text):
    """The first VEVENT of an invitation, or None. Cancellations come back with cancelled=True."""
    lines = _unfold(text)
    method = next((l.split(':', 1)[1].strip().upper() for l in lines if l.upper().startswith('METHOD:')), '')
    event, inside = {}, False
    for line in lines:
        upper = line.upper()
        if upper.startswith('BEGIN:VEVENT'):
            inside = True
        elif upper.startswith('END:VEVENT'):
            break
        elif inside and ':' in line:
            head, value = line.split(':', 1)
            name, _, params = head.partition(';')
            event.setdefault(name.upper(), (params, value))
    if 'DTSTART' not in event:
        return None
    start, zone, all_day = _when(*event['DTSTART'])
    if 'DTEND' in event:
        end = _when(*event['DTEND'])[0]
    elif all_day:
        end = (dt.date.fromisoformat(start) + dt.timedelta(days=1)).isoformat()
    else:
        end = (dt.datetime.fromisoformat(start) + dt.timedelta(hours=1)).isoformat(timespec='minutes')
    status = event.get('STATUS', ('', ''))[1].strip().upper()
    return {'title': _unescape(event.get('SUMMARY', ('', ''))[1]) or '(פגישה)', 'start': start, 'end': end, 'zone': zone,
            'all_day': all_day, 'where': _unescape(event.get('LOCATION', ('', ''))[1])[:200],
            'uid': event.get('UID', ('', ''))[1].strip()[:300],
            'organizer': re.sub(r'(?i)^mailto:', '', event.get('ORGANIZER', ('', ''))[1].strip()),
            'cancelled': method == 'CANCEL' or status == 'CANCELLED'}


def find_invite(msg):
    """The invitation inside an email (inline text/calendar or an .ics attachment)."""
    for part in msg.walk():
        name = (part.get_filename() or '').lower()
        if part.get_content_type() == 'text/calendar' or name.endswith('.ics'):
            try:
                data = part.get_payload(decode=True) or b''
                found = parse_ics(data.decode(part.get_content_charset() or 'utf-8', 'replace'))
            except Exception:
                continue
            if found:
                return found
    return None


def invite_key(invite):
    return invite.get('uid') or f"{invite['start']}|{invite['title']}"


def upcoming(invite, now=None):
    now = now or dt.datetime.now()
    end = invite['end'] if not invite['all_day'] else invite['end'] + 'T00:00'
    return not invite['cancelled'] and dt.datetime.fromisoformat(end) > now


def when_text(invite):
    days = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']
    start = dt.datetime.fromisoformat(invite['start'] if not invite['all_day'] else invite['start'] + 'T00:00')
    head = f'יום {days[start.weekday()]} {start:%d/%m}'
    return head + (' · כל היום' if invite['all_day'] else f' · {start:%H:%M}–{invite["end"][11:16]}')


def event_resource(invite, notes=''):
    """Google Calendar "import" body: the iCalUID keeps the same invitation from being added twice."""
    if invite['all_day']:
        start, end = {'date': invite['start']}, {'date': invite['end'][:10]}
    else:
        start = {'dateTime': invite['start'] + ':00', 'timeZone': invite['zone'] or 'Asia/Jerusalem'}
        end = {'dateTime': invite['end'] + ':00', 'timeZone': invite['zone'] or 'Asia/Jerusalem'}
    body = {'summary': invite['title'], 'location': invite['where'], 'description': notes, 'start': start, 'end': end,
            'iCalUID': invite['uid'] or 'mailbrief-' + hashlib.sha1(f"{invite['start']}|{invite['title']}".encode()).hexdigest()[:16] + '@mailbrief'}
    if invite.get('organizer'):
        body['organizer'] = {'email': invite['organizer']}
    return body
