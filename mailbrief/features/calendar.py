"""Shabbat / Yom Tov windows (Hebcal) and the user's pause switch."""
import datetime as dt

from mailbrief import config
from mailbrief import net
from mailbrief.storage import load_json, save_json


CITIES = {
    'ירושלים': (31.7683, 35.2137), 'תל אביב': (32.0853, 34.7818), 'חיפה': (32.7940, 34.9896),
    'אשדוד': (31.8014, 34.6435), 'באר שבע': (31.2518, 34.7913), 'בני ברק': (32.0807, 34.8338),
    'פתח תקווה': (32.0840, 34.8878), 'נתניה': (32.3215, 34.8532), 'בית שמש': (31.7470, 34.9881),
    'מודיעין': (31.8980, 35.0104), 'אלעד': (32.0522, 34.9510), 'ראשון לציון': (31.9730, 34.7925),
    'רחובות': (31.8928, 34.8113), 'צפת': (32.9646, 35.4960), 'טבריה': (32.7922, 35.5312),
}


HOLY_MARGIN = dt.timedelta(minutes=30)      # stop this long before candle lighting


def holy_windows(saved_only=False):
    """Shabbat / Yom Tov periods [(start, end)] from Hebcal for the chosen city: candle lighting -> havdalah.
    Consecutive candle lightings (two-day chag, chag next to Shabbat) stay one window. Chol HaMoed is a weekday.
    saved_only: use the stored calendar without going online."""
    lat, lon = CITIES.get(load_json(config.SETTINGS_FILE, {}).get('city', 'ירושלים'), CITIES['ירושלים'])
    today = dt.date.today()
    if saved_only:
        data = (load_json(config.CACHE_FILE, {}).get('holy') or {}).get('data')
    else:
        data = net.cached_json('holy', f'https://www.hebcal.com/hebcal?v=1&cfg=json&c=on&maj=on&i=on&geo=pos&latitude={lat}'
                           f'&longitude={lon}&tzid=Asia/Jerusalem&start={today - dt.timedelta(days=3)}'
                           f'&end={today + dt.timedelta(days=30)}', 24 * 60)
    if not data:
        return None
    events = sorted((dt.datetime.fromisoformat(i['date']), i['category']) for i in data.get('items', [])
                    if i.get('category') in ('candles', 'havdalah') and 'T' in i.get('date', ''))
    windows, start = [], None
    for when, kind in events:
        if kind == 'candles' and start is None:
            start = when - HOLY_MARGIN
        elif kind == 'havdalah' and start is not None:
            windows.append((start, when))
            start = None
    if start is not None:
        windows.append((start, start + dt.timedelta(days=3)))
    return windows


def is_holy_time(now=None):
    now = now or dt.datetime.now().astimezone()
    saved = holy_windows(saved_only=True)       # decide from the stored calendar first — no network on Shabbat
    if saved and any(start <= now < end for start, end in saved):
        return True
    windows = holy_windows()
    if windows is None:                          # no calendar at all: play safe — Friday 14:00 to Saturday night
        return (now.weekday() == 4 and now.hour >= 14) or (now.weekday() == 5 and (now.hour, now.minute) < (20, 30))
    return any(start <= now < end for start, end in windows)


def holy_status():
    now = dt.datetime.now().astimezone()
    windows = holy_windows() or []
    current = next(((s, e_) for s, e_ in windows if s <= now < e_), None)
    if current:
        return f'🕯️ שבת/חג — האוטומציות מושהות עד {current[1]:%H:%M} ({current[1]:%d/%m})'
    upcoming = next(((s, e_) for s, e_ in windows if s > now), None)
    return (f'🕯️ האוטומציות יושהו בשבת/חג הקרוב: {upcoming[0]:%d/%m %H:%M} עד {upcoming[1]:%d/%m %H:%M}'
            if upcoming else '🕯️ האוטומציות מושהות אוטומטית בשבתות ובחגים')


def paused_until():
    value = load_json(config.SETTINGS_FILE, {}).get('paused_until')
    if value and dt.datetime.fromisoformat(value) > dt.datetime.now().astimezone():
        return dt.datetime.fromisoformat(value)
    return None


def set_pause(until):
    settings = load_json(config.SETTINGS_FILE, {})
    if until:
        settings['paused_until'] = until.isoformat()
    else:
        settings.pop('paused_until', None)
    save_json(config.SETTINGS_FILE, settings)


def pause_for(mode):
    now = dt.datetime.now().astimezone()
    if mode == '2h':
        set_pause(now + dt.timedelta(hours=2))
    elif mode == 'tomorrow':
        set_pause((now + dt.timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0))
    else:
        set_pause(None)
    return paused_until()
