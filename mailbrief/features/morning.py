"""☀️ The morning summary at Windows sign-in: one short notification ("2 urgent · 3 waiting · 1 payment · meeting 10:00")
with a button to open "My day" — for those who don't want the whole page every morning."""
from mailbrief import config
from mailbrief.address import link
from mailbrief.features import notify
from mailbrief.profile import profile
from mailbrief.storage import load_json


def morning_lines():
    snap = load_json(config.SNAPSHOT_FILE, {})
    parts = []
    for key, label in (('urgent', 'דחופים'), ('waiting', 'מחכים לתשובה')):
        if snap.get(key):
            parts.append(f'{len(snap[key])} {label}')
    try:
        from mailbrief.features.alerts import upcoming_payments
        due = upcoming_payments(days=2)
        if due:
            parts.append(f'{len(due)} לתשלום')
    except Exception:
        pass
    events = []
    try:
        from mailbrief.features import google_apps
        overview = google_apps.today_overview()
        events = (overview or {}).get('events', [])
    except Exception:
        pass
    first = next((ev for ev in events if ev.get('time') and ev['time'] != 'כל היום'), None)
    line = ' · '.join(parts) or 'אין היום משהו דחוף ✨'
    return line, (f"📅 {first['time']} {first['title']}" + (f' (ועוד {len(events) - 1})' if len(events) > 1 else '')) if first else ''


def morning_toast():
    name = profile().get('name', '')
    line, meeting = morning_lines()
    notify.toast(f'☀️ בוקר טוב{", " + name if name else ""}!', [line] + ([meeting] if meeting else []), link('today'),
                 actions=[('☀️ פתיחת היום שלי', link('today'))])
