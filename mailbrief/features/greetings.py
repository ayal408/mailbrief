"""Holiday greetings to clients: a personal email to each person you actually correspond with, scheduled for the eve of
the holiday and sent in small batches — through the scheduled outbox, so never on Shabbat / Yom Tov."""
import collections
import datetime as dt
import re

from mailbrief import config, net
from mailbrief.features import outbox
from mailbrief.mail.classify import RX
from mailbrief.storage import load_json


MAX_RECIPIENTS = 300


OCCASIONS = {
    'rosh': ('🍎 ראש השנה', 'שנה טובה ומתוקה!',
             'שלום {first_name},\n\nלקראת השנה החדשה — רציתי לאחל לך ולכל המשפחה שנה טובה ומתוקה, שנה של בריאות, הצלחה ושמחה.\n'
             'תודה על שיתוף הפעולה בשנה שעברה!\n\nשנה טובה,\n{my_name}'),
    'sukkot': ('🌿 סוכות', 'חג סוכות שמח!', 'שלום {first_name},\n\nחג סוכות שמח לך ולכל המשפחה!\n\nבברכה,\n{my_name}'),
    'chanukah': ('🕎 חנוכה', 'חנוכה שמח!', 'שלום {first_name},\n\nחנוכה שמח ומאיר — הרבה אור ושמחה לך ולבני הבית!\n\nבברכה,\n{my_name}'),
    'purim': ('🎭 פורים', 'פורים שמח!', 'שלום {first_name},\n\nפורים שמח!\n\nבברכה,\n{my_name}'),
    'pesach': ('🍷 פסח', 'חג פסח כשר ושמח!',
               'שלום {first_name},\n\nלקראת פסח — רציתי לאחל לך ולכל המשפחה חג כשר ושמח, חג של חירות ושמחה.\n\nחג שמח,\n{my_name}'),
    'shavuot': ('🌾 שבועות', 'חג שבועות שמח!', 'שלום {first_name},\n\nחג שבועות שמח!\n\nבברכה,\n{my_name}'),
    'other': ('✉️ ברכה אחרת', '', 'שלום {first_name},\n\n\n\nבברכה,\n{my_name}'),
}


HEBCAL_NAMES = {    # exact titles — "Rosh Hashana LaBehemot" (1 Elul) or "Erev Pesach" must not match
    'rosh': r'Rosh Hashana \d{4}', 'sukkot': r'Sukkot I', 'chanukah': r'Chanukah: 1 Candle', 'purim': r'Purim',
    'pesach': r'Pesach I', 'shavuot': r'Shavuot( I)?'}


def first_name(name):
    word = (name or '').replace('"', ' ').split()
    word = word[0] if word else ''
    return word if re.fullmatch(r"[A-Za-z֐-׿'׳-]{2,20}", word) and word.lower() not in ('the', 'info', 'team') else ''


def recipients(days=365):
    """People you really correspond with in the last year (not newsletters, shops or robots), most frequent first."""
    own = {a['email'].lower() for a in load_json(config.ACCOUNTS_FILE, [])}
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    people = collections.defaultdict(lambda: {'count': 0, 'answered': 0, 'last': '', 'name': '', 'labels': set()})
    for h in load_json(config.HISTORY_FILE, {}).values():
        sender = (h.get('sender') or '').lower()
        if h['date'] < since or 'people' not in h['cats'] or not sender or sender in own or RX['robot_sender'].search(sender):
            continue
        p = people[sender]
        p['count'] += 1
        p['answered'] += 1 if h.get('answered') else 0
        p['last'] = max(p['last'], h['date'])
        p['name'] = h.get('name') or p['name']
        p['labels'].update(h.get('rules', []))
    rows = [{'email': k, 'name': v['name'], 'first_name': first_name(v['name']), 'count': v['count'], 'last': v['last'],
             'labels': sorted(v['labels']), 'suggested': bool(v['labels']) or v['answered'] > 0 or v['count'] >= 3}
            for k, v in people.items()]
    return sorted(rows, key=lambda r: (not r['labels'], -r['count']))


def next_date(occasion, now=None):
    """The holiday's first day from Hebcal's list (already cached for "My day"), or None."""
    name = HEBCAL_NAMES.get(occasion)
    if not name:
        return None
    today = (now or dt.date.today())
    year = net.cached_json('holidays_year', 'https://www.hebcal.com/hebcal?v=1&cfg=json&maj=on&min=on&i=on'
                                            f'&start={today}&end={today + dt.timedelta(days=420)}', 24 * 60) or {}
    for item in year.get('items', []):
        title = item.get('title', '')
        day = item.get('date', '')[:10]
        if re.fullmatch(name, title) and day and dt.date.fromisoformat(day) >= today:
            return dt.date.fromisoformat(day)
    return None


def personal(text, person, my_name):
    body = text.replace('{first_name}', person.get('first_name', '')).replace('{name}', person.get('name', '')).replace('{my_name}', my_name)
    return re.sub(r'שלום ,', 'שלום,', re.sub(r'Hi ,', 'Hi,', body)).strip() + '\n'


def schedule_greetings(account, people, subject, text, when, my_name=''):
    """One personal email per person, all queued for the chosen time (the outbox sends them gently, never on Shabbat)."""
    if not people:
        raise ValueError('לא נבחרו נמענים')
    if len(people) > MAX_RECIPIENTS:
        raise ValueError(f'עד {MAX_RECIPIENTS} נמענים בפעם אחת (Gmail מגביל שליחה המונית)')
    for person in people:
        outbox.schedule(account, person['email'], subject, personal(text, person, my_name), when)
    return len(people)
