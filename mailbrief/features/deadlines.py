"""⏰ Deadlines found in emails: "by 15/10", "no later than Thursday", "deadline: 3.11", "by the end of the month" —
a list in My day and a reminder the day before at 9:00. Only in emails from people, only in their own words."""
import datetime as dt
import re

from mailbrief import config
from mailbrief.features.contacts import own_part
from mailbrief.mail.message import body_text
from mailbrief.storage import load_json, save_json


WEEKDAYS = {'ראשון': 6, 'שני': 0, 'שלישי': 1, 'רביעי': 2, 'חמישי': 3, 'שישי': 4}
LEAD = r'(?:עד|לא יאוחר מ|לפני|מועד אחרון(?: להגשה)?|תאריך יעד|דדליין|deadline|due(?: date)?|no later than|by)'
DATE = re.compile(LEAD + r'\s*[:\-]?\s*(?:ל?תאריך\s*|ה-?|יום\s+\S+\s*,?\s*)?(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)', re.I)
DAY = re.compile(r'(?:עד|לא יאוחר מ|לפני)\s*(?:יום\s+)?(ראשון|שני|שלישי|רביעי|חמישי|שישי)\b')
MONTH_END = re.compile(r'עד סוף (?:ה)?חודש|by the end of the month', re.I)


def find_deadline(text, today):
    """The first future date (within 4 months) the text asks for, with the sentence around it — or (None, '')."""
    def around(m):
        start = max(text.rfind('\n', 0, m.start()), text.rfind('.', 0, m.start())) + 1
        end = min([i for i in (text.find('\n', m.end()), text.find('.', m.end())) if i >= 0] or [len(text)])
        return re.sub(r'\s+', ' ', text[start:end]).strip()[:140]
    found = []
    for m in DATE.finditer(text):
        day, month = int(m[1]), int(m[2])
        year = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else today.year
        try:
            when = dt.date(year, month, day)
        except ValueError:
            continue
        if not m[3] and when < today:
            try:
                when = dt.date(year + 1, month, day)
            except ValueError:
                continue
        found.append((m.start(), when, around(m)))
    for m in DAY.finditer(text):
        ahead = (WEEKDAYS[m[1]] - today.weekday()) % 7 or 7
        found.append((m.start(), today + dt.timedelta(days=ahead), around(m)))
    m = MONTH_END.search(text)
    if m:
        nxt = (today.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        found.append((m.start(), nxt - dt.timedelta(days=1), around(m)))
    for _, when, sentence in sorted(found):
        if today <= when <= today + dt.timedelta(days=120):
            return when, sentence
    return None, ''


def deadlines():
    return load_json(config.DEADLINES_FILE, {})


def learn(pairs, account, own=()):
    """New deadlines from the latest check; each also gets a reminder the day before at 9:00."""
    from mailbrief.features.reminders import remind_at
    rows, added, today = deadlines(), 0, dt.date.today()
    for it, msg in pairs:
        key = (msg.get('Message-ID') or '').strip()
        if not key or key in rows or 'people' not in it.get('cats', []) or (it.get('sender') or '').lower() in own:
            continue
        received = dt.date.fromisoformat(it['iso'][:10]) if it.get('iso') else today
        text = f"{it.get('subject', '')}\n{own_part(body_text(msg) or '')[:4000]}"
        when, sentence = find_deadline(text, received)
        if not when or when < today:
            continue
        rows[key] = {'date': when.isoformat(), 'subject': (it.get('subject') or '')[:200], 'from': it.get('sender_name') or it.get('sender', ''),
                     'sentence': sentence, 'link': it.get('link', ''), 'account': account}
        eve = dt.datetime.combine(when - dt.timedelta(days=1), dt.time(9, 0)).astimezone()
        if eve > dt.datetime.now().astimezone():
            remind_at(eve, f'מחר: {rows[key]["subject"]}', rows[key]['from'], rows[key]['link'], account, sentence)
        added += 1
    if added:
        save_json(config.DEADLINES_FILE, rows)
    return added


def upcoming(days=21, today=None):
    today = today or dt.date.today()
    rows = [(k, r) for k, r in deadlines().items() if not r.get('done') and today <= dt.date.fromisoformat(r['date']) <= today + dt.timedelta(days=days)]
    return sorted(rows, key=lambda kv: kv[1]['date'])


def done(key):
    rows = deadlines()
    if key in rows:
        rows[key]['done'] = True
        save_json(config.DEADLINES_FILE, rows)
