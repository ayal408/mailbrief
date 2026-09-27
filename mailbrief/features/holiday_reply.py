"""🕯️ Automatic reply over the holidays (Sukkot and Pesach, from Erev Chag to the last Yom Tov): whoever writes gets
"we're on holiday, back on …" — once per person per holiday. The dates come from the Hebrew calendar (Hebcal).
Nothing goes out on Shabbat or Yom Tov itself: the hourly check doesn't run then, so the reply goes out on Chol HaMoed
or right after the holiday."""
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json


DEFAULT = 'שלום {from_name},\nתודה על הפנייה. אנחנו בחופשת {holiday} עד {to}, ונחזור אלייך מיד אחרי.\n\nחג שמח!'
FAMILIES = {'Sukkot': ('סוכות', ('Sukkot', 'Shmini Atzeret', 'Simchat Torah')), 'Pesach': ('פסח', ('Pesach',))}


def cfg():
    return load_json(config.SETTINGS_FILE, {}).get('holiday_reply') or {}


def holiday_period(items, today):
    """(Hebrew name, first day, last Yom Tov) when `today` is inside Sukkot / Pesach (from Erev Chag), else None."""
    for base, (name, titles) in FAMILIES.items():
        days = sorted(dt.date.fromisoformat(i['date'][:10]) for i in items
                      if i.get('category') == 'holiday' and any(i.get('title', '').startswith(t) for t in titles))
        erev = [dt.date.fromisoformat(i['date'][:10]) for i in items if i.get('title', '') == f'Erev {base}']
        if not days:
            continue
        first = min(erev + days)
        # one festival: consecutive days (Chol HaMoed has no gaps longer than a day or two)
        last = days[0]
        for d in days:
            if (d - last).days <= 2:
                last = d
        if first <= today <= last:
            return name, first, last
    return None


def active(today=None):
    """{'from', 'to', 'message', 'holiday'} while the holiday reply should go out, else None."""
    c = cfg()
    if not c.get('on'):
        return None
    today = today or dt.date.today()
    data = (load_json(config.CACHE_FILE, {}).get('holy') or {}).get('data') or {}
    found = holiday_period(data.get('items', []), today)
    if not found:
        return None
    name, first, last = found
    return {'from': first.isoformat(), 'to': last.isoformat(), 'message': c.get('message') or DEFAULT, 'holiday': name}
