"""Hebrew dates (Hebcal's converter): a client's birthday by the Hebrew calendar falls on a different day every year."""
import datetime as dt

from mailbrief import net


def g2h(day):
    """{'hy', 'hm', 'hd', 'hebrew'} for a Gregorian date, or None offline."""
    data = net.cached_json(f'g2h|{day}', f'https://www.hebcal.com/converter?cfg=json&gy={day.year}&gm={day.month}&gd={day.day}&g2h=1',
                           60 * 24 * 365)
    if not data or 'hy' not in data:
        return None
    return {'hy': data['hy'], 'hm': data['hm'], 'hd': data['hd'], 'hebrew': data.get('hebrew', '')}


def h2g(hy, hm, hd):
    """The Gregorian date of a Hebrew date in year hy (Adar II in a regular year -> Adar), or None offline."""
    for month in ([hm, 'Adar'] if hm in ('Adar I', 'Adar II') else [hm]):
        data = net.cached_json(f'h2g|{hy}|{month}|{hd}',
                               f'https://www.hebcal.com/converter?cfg=json&hy={hy}&hm={month.replace(" ", "%20")}&hd={hd}&h2g=1',
                               60 * 24 * 365)
        if data and 'gy' in data:
            return dt.date(data['gy'], data['gm'], data['gd'])
    return None


def next_occurrence(hm, hd, today=None):
    """The next Gregorian date (today or later) of a yearly Hebrew date, or None offline."""
    today = today or dt.date.today()
    now = g2h(today)
    if not now:
        return None
    for hy in (now['hy'], now['hy'] + 1):
        when = h2g(hy, hm, hd)
        if when and when >= today:
            return when
    return None
