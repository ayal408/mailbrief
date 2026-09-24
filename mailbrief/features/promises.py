"""Promises in sent mail: "I'll get back to you tomorrow", "אשלח עד יום חמישי" — a reminder is created by itself for
that day (09:00), so nothing I promised is forgotten. Plain rules, no AI: a promise phrase plus a date in the same sentence
(or no date: two days later)."""
import datetime as dt
import email.utils
import re
from urllib.parse import quote

from mailbrief.features.reminders import add_reminder
from mailbrief.mail.imap import fetch_recent, is_gmail, special_folder
from mailbrief.mail.message import body_text, decode


PROMISE = re.compile(
    r'(?:אחזור|אחזיר|נחזור|אעדכן|נעדכן|אשלח|נשלח|אבדוק|נבדוק|אכין|נכין|אתקשר|נתקשר|אטפל|נטפל|אסדר|אעביר|נעביר|אשתדל לענות|'
    r"I'?ll (?:get back|send|update|check|call|follow up|have)|I will (?:get back|send|update|check|call|follow up)|"
    r"we'?ll (?:get back|send|update)|will get back to you)", re.I)
DAYS_HE = {'ראשון': 6, 'שני': 0, 'שלישי': 1, 'רביעי': 2, 'חמישי': 3, 'שישי': 4}
DAYS_EN = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'sunday': 6}
MAX_SCANNED = 30


def _next_weekday(start, weekday):
    days = (weekday - start.weekday()) % 7 or 7
    return start + dt.timedelta(days=days)


def promise_date(sentence, sent):
    """The day the promise is due, from the words around it. sent: the date the mail was sent."""
    s = sentence.lower()
    if re.search(r'מחרתיים|day after tomorrow', s):
        return sent + dt.timedelta(days=2)
    if re.search(r'מחר|tomorrow', s):
        return sent + dt.timedelta(days=1)
    if re.search(r'היום|today|later today|בהמשך היום|עד הערב|tonight', s):
        return sent
    for name, wd in DAYS_HE.items():
        if re.search(rf'(?:ביום|עד יום|יום)\s+{name}(?![֐-׿])', s):
            return _next_weekday(sent, wd)
    for name, wd in DAYS_EN.items():
        if re.search(rf'\b(?:by|on|next)?\s*{name}\b', s):
            return _next_weekday(sent, wd)
    if re.search(r'שבוע הבא|בשבוע הקרוב|next week', s):
        return _next_weekday(sent, 6)                         # Sunday
    if re.search(r'סוף השבוע|end of (?:the )?week', s):
        return _next_weekday(sent, 3)                         # Thursday
    found = re.search(r'(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)', s)
    if found:
        day, month = int(found.group(1)), int(found.group(2))
        year = int(found.group(3)) if found.group(3) else sent.year
        year += 2000 if year < 100 else 0
        try:
            when = dt.date(year, month, day)
        except ValueError:
            when = None
        if when and not found.group(3) and when < sent:
            when = when.replace(year=when.year + 1)
        if when and 0 <= (when - sent).days <= 120:
            return when
    found = re.search(r'(?:עד ה-?|ב-?)(\d{1,2})\s*(?:לחודש)', s)
    if found and 1 <= int(found.group(1)) <= 31:
        day = int(found.group(1))
        month = sent.replace(day=1) if day >= sent.day else (sent.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        try:
            return month.replace(day=day)
        except ValueError:
            return None
    return sent + dt.timedelta(days=2)


def find_promises(text, sent):
    """[(sentence, due date)] — at most two per message (the first ones)."""
    out = []
    own = re.split(r'\n\s*(?:On .{5,80} wrote:|ב-.{3,60} כתב|-----Original|From:|מאת:)', text or '', maxsplit=1)[0]   # my words, not the quote
    for sentence in re.split(r'(?<=[.!?\n])\s+', own[:4000]):
        if PROMISE.search(sentence) and len(sentence) < 400:
            out.append((re.sub(r'\s+', ' ', sentence).strip(), promise_date(sentence, sent)))
        if len(out) == 2:
            break
    return out


def scan_sent(m, acc, state, own, days=2):
    """Looks at mail I sent in the last days and creates reminders for promises. Each message once. Returns how many."""
    sent_folder = special_folder(m, r'\Sent')
    if not sent_folder:
        return 0
    seen, made = set(state.get('_promises', [])), 0
    for _, gid, msg in fetch_recent(m, is_gmail(acc), days=days, readonly=True, folder=sent_folder, limit=MAX_SCANNED):
        mid = (msg.get('Message-ID') or '').strip()
        if not mid or mid in seen or msg.get('X-MailBrief-Forwarded') or msg.get('X-MailBrief-Auto'):
            continue
        seen.add(mid)
        to = [(n, a) for n, a in email.utils.getaddresses([str(msg.get('To', ''))]) if a and a.lower() not in own]
        try:
            when = email.utils.parsedate_to_datetime(msg['Date']).astimezone().date()
        except Exception:
            continue
        if not to:
            continue
        for sentence, due in find_promises(body_text(msg), when):
            days_left = max(0, (due - dt.date.today()).days)
            who = to[0][0] or to[0][1]
            link = f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{gid:x}" if gid else ''
            add_reminder(days_left, f'🤝 הבטחת ל{who}: {sentence[:120]}', who, link, acc['email'],
                         note=decode(msg.get('Subject')) or '')
            made += 1
    state['_promises'] = sorted(seen)[-800:]
    return made
