"""Hebrew dates without a library: ה׳ בחשוון תשפ״ז (the arithmetic of the fixed Hebrew calendar, as in Calendrical Calculations)."""
EPOCH = -1373427                    # 1 Tishrei of year 1, as a date.toordinal() day number

DAYS = ('שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון')     # date.weekday(): Monday = 0
_ONES = 'אבגדהוזחט'
_TENS = 'יכלמנסעפצ'
_HUNDREDS = 'קרשת'


def leap(year):
    return (7 * year + 1) % 19 < 7


def _elapsed(year):
    months = (235 * year - 234) // 19
    day = months * 29 + (12084 + 13753 * months) // 25920
    return day + 1 if (3 * (day + 1)) % 7 < 3 else day


def _new_year(year):
    ny0, ny1, ny2 = _elapsed(year - 1), _elapsed(year), _elapsed(year + 1)
    fix = 2 if ny2 - ny1 == 356 else 1 if ny1 - ny0 == 382 else 0
    return EPOCH + ny1 + fix


def _months(year):
    """[(name, days)] from Tishrei to Elul."""
    length = _new_year(year + 1) - _new_year(year)
    adar = [('אדר א׳', 30), ('אדר ב׳', 29)] if leap(year) else [('אדר', 29)]
    return ([('תשרי', 30), ('חשוון', 30 if length % 10 == 5 else 29), ('כסלו', 29 if length % 10 == 3 else 30),
             ('טבת', 29), ('שבט', 30)] + adar +
            [('ניסן', 30), ('אייר', 29), ('סיוון', 30), ('תמוז', 29), ('אב', 30), ('אלול', 29)])


def from_date(day):
    """(year, month name, day of month) of a civil date (a sunset-to-sunset day is the caller's business)."""
    rd = day.toordinal()
    year = (rd - EPOCH) * 98496 // 35975351 + 1
    while _new_year(year) > rd:
        year -= 1
    while _new_year(year + 1) <= rd:
        year += 1
    left = rd - _new_year(year)
    for name, days in _months(year):
        if left < days:
            return year, name, left + 1
        left -= days
    raise ValueError(day)


def gematria(n):
    """15 -> ט״ו, 787 -> תשפ״ז (the thousands are dropped, as usual)."""
    n %= 1000
    out = ''
    while n >= 100:
        h = min(n // 100, 4)
        out += _HUNDREDS[h - 1]
        n -= h * 100
    if n in (15, 16):
        out += 'ט' + _ONES[n - 10]
    else:
        out += (_TENS[n // 10 - 1] if n >= 10 else '') + (_ONES[n % 10 - 1] if n % 10 else '')
    return out[:-1] + '״' + out[-1] if len(out) > 1 else out + '׳'


def text(day, year=False):
    """ה׳ בחשוון (or ה׳ בחשוון תשפ״ז)."""
    y, month, d = from_date(day)
    return f'{gematria(d)} ב{month}' + (f' {gematria(y)}' if year else '')
