"""📆 Yearly renewals: a supplier that charged about a year ago (domain, insurance, software licence) will probably charge
again — a reminder a month before, while there is still time to cancel or compare. From the receipts on this computer."""
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json


def yearly_renewals(ledger=None, today=None, ahead=45):
    """[{'vendor', 'key', 'amount', 'currency', 'last', 'next', 'days'}] — last charged 10–13 months ago and not since;
    the next charge within `ahead` days (or up to a week late)."""
    ledger = load_json(config.LEDGER_FILE, {}) if ledger is None else ledger
    today = today or dt.date.today()
    groups = {}
    for r in ledger.values():
        if r.get('duplicate') or not r.get('date'):
            continue
        groups.setdefault(r['vendor_key'], []).append(r)
    out = []
    for key, rows in groups.items():
        rows.sort(key=lambda r: r['date'])
        last = dt.date.fromisoformat(rows[-1]['date'])
        age = (today - last).days
        if not 300 <= age <= 400:                                 # nothing since ~a year ago, so not a monthly charge
            continue
        nxt = last.replace(year=last.year + 1) if not (last.month == 2 and last.day == 29) else last + dt.timedelta(days=365)
        left = (nxt - today).days
        if -7 <= left <= ahead:
            out.append({'vendor': rows[-1].get('vendor', key), 'key': key, 'amount': rows[-1].get('amount'),
                        'currency': rows[-1].get('currency', ''), 'last': rows[-1]['date'], 'next': nxt, 'days': left})
    return sorted(out, key=lambda r: r['next'])
