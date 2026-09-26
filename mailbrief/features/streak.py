"""🔥 A small game: how many days in a row nobody was left waiting for your answer."""
import datetime as dt
import os

from mailbrief import config
from mailbrief.storage import load_json, save_json


def _path():
    return os.path.join(config.DATA, 'streak.json')


def update_streak(clear, today=None):
    """clear: nobody is waiting for your answer right now. Returns the current streak (days)."""
    today = today or dt.date.today()
    s = load_json(_path(), {})
    last = dt.date.fromisoformat(s['last']) if s.get('last') else None
    days = s.get('days', 0)
    if last and (today - last).days > 1:
        days = 0                                              # a day went by with someone waiting
    if clear and last != today:
        days = days + 1 if last == today - dt.timedelta(days=1) else 1
        last = today
        s['best'] = max(s.get('best', 0), days)
    s.update({'last': last.isoformat() if last else '', 'days': days})
    save_json(_path(), s)
    return days
