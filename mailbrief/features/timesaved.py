"""⏱️ What MailBrief did for you this week, and roughly how much time that saved: emails that went out by themselves
(scheduled, reminders, greetings, follow-ups), automations that ran, forwards, and receipts filed. The minutes per
action are a modest estimate — shown as "about"."""
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json


MINUTES = {'sent': 2, 'automation': 1, 'forward': 1, 'receipt': 2}
LABELS = {'sent': '✉️ מיילים שיצאו לבד (מתוזמנים, תזכורות, ברכות)', 'automation': '⚡ אוטומציות שרצו',
          'forward': '↪️ העברות אוטומטיות', 'receipt': '🧾 קבלות שנשמרו ומוינו'}


def _when(stamp, today):
    """'27/09 14:05' (no year) -> a date; a date "in the future" belongs to last year."""
    try:
        day = dt.datetime.strptime(f'{stamp[:5]}/{today.year}', '%d/%m/%Y').date()
    except (ValueError, TypeError):
        return None
    return day.replace(year=today.year - 1) if day > today else day


def week_counts(today=None):
    today = today or dt.date.today()
    since = today - dt.timedelta(days=7)
    inside = lambda day: day is not None and since <= day <= today
    counts = {'sent': sum(1 for m in load_json(config.OUTBOX_FILE, []) if m.get('status') == 'sent'
                          and inside(dt.date.fromisoformat(m.get('sent', '1900-01-01')[:10]))),
              'automation': sum(1 for r in load_json(config.WF_LOG, []) if inside(_when(r.get('at', ''), today))),
              'forward': sum(1 for r in load_json(config.FORWARD_LOG, []) if r.get('ok') and inside(_when(r.get('at', ''), today))),
              'receipt': sum(1 for r in load_json(config.LEDGER_FILE, {}).values()
                             if not r.get('duplicate') and inside(dt.date.fromisoformat(r.get('date', '1900-01-01')[:10])))}
    return counts, sum(MINUTES[k] * v for k, v in counts.items())


def saved_lines(today=None):
    """Short lines for the Sunday summary and the stats page; [] when nothing happened."""
    counts, minutes = week_counts(today)
    if not minutes:
        return []
    time = f'כ-{minutes} דקות' if minutes < 90 else f'כ-{round(minutes / 60, 1):g} שעות'
    return [f'⏱️ MailBrief חסך לך השבוע {time}'] + [f'   {LABELS[k]}: {v}' for k, v in counts.items() if v]
