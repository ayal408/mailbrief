"""🏖️ Who is away: an automatic "I'm out of the office until 3/10" reply is remembered, so "waiting for their answer"
shows that they are away (and until when) instead of looking like they ignore you."""
import datetime as dt
import os
import re

from mailbrief import config
from mailbrief.mail.message import body_text, decode
from mailbrief.storage import load_json, save_json


AWAY_SUBJECT = re.compile(r'out of (?:the )?office|automatic reply|auto(?:matic)?[- ]?reply|away from|on (?:vacation|leave)|'
                          r'מענה אוטומטי|תשובה אוטומטית|מחוץ למשרד|בחופשה|בחופש|לא (?:נמצא|נמצאת|זמין|זמינה)', re.I)
UNTIL = re.compile(r'(?:until|till|through|back (?:on|at)?|return(?:ing)? (?:on)?|עד (?:ל-?|ה-?)?|אחזור (?:ב-?|ביום )?|חוזר(?:ת)? (?:ב-?|ביום )?)'
                   r'\s*(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?', re.I)


def _path():
    return os.path.join(config.DATA, 'away.json')


def is_auto_reply(msg):
    auto = str(msg.get('Auto-Submitted', '')).lower()
    return (auto.startswith('auto-replied') or bool(msg.get('X-Autoreply')) or bool(msg.get('X-Autorespond'))
            or bool(AWAY_SUBJECT.search(decode(msg.get('Subject')) or '')))


def away_until(text, received):
    """The return date written in an out-of-office reply, or received + 7 days when none is found."""
    found = UNTIL.search(text or '')
    if found:
        day, month = int(found.group(1)), int(found.group(2))
        year = int(found.group(3)) if found.group(3) else received.year
        year += 2000 if year < 100 else 0
        try:
            when = dt.date(year, month, day)
            if when < received and not found.group(3):
                when = when.replace(year=year + 1)
            if 0 <= (when - received).days <= 120:
                return when
        except ValueError:
            pass
    return received + dt.timedelta(days=7)


def note(msg, sender, received=None):
    """Called for incoming mail: remembers an out-of-office reply. Returns the date, or None."""
    if not sender or not is_auto_reply(msg):
        return None
    received = received or dt.date.today()
    until = away_until(f"{decode(msg.get('Subject')) or ''}\n{body_text(msg)[:2000]}", received)
    rows = load_json(_path(), {})
    rows[sender.lower()] = {'until': until.isoformat(), 'seen': received.isoformat()}
    save_json(_path(), {k: v for k, v in rows.items() if v['until'] >= (dt.date.today() - dt.timedelta(days=30)).isoformat()})
    return until


def away(address, today=None):
    """The return date when this person is away now, else None."""
    row = load_json(_path(), {}).get((address or '').lower())
    if row and row['until'] >= (today or dt.date.today()).isoformat():
        return dt.date.fromisoformat(row['until'])
    return None
