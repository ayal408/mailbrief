"""Manage every reminder without loading a huge list on My day."""
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.view import current_account, mine
from mailbrief.web.layout import page, heading
from mailbrief.web.token import TOKEN


def reminders_page(number=0):
    account = current_account()
    items = sorted((r for r in load_json(config.REMINDERS_FILE, []) if mine(r, current=account)), key=lambda r: r['due'])
    number = min(max(0, number), max(0, (len(items) - 1) // 50))
    rows = ''.join(f'<tr><td dir="auto">{e(r["subject"])}<div class="muted">{e(r.get("note", ""))}</div></td>'
                   f'<td>{dt.datetime.fromisoformat(r["due"]):%d/%m %H:%M}</td><td>'
                   f'<form method="post" action="/reminder_delete"><input type="hidden" name="t" value="{TOKEN}">'
                   f'<input type="hidden" name="id" value="{e(r["id"])}"><input type="hidden" name="back" value="/reminders?p={number}">'
                   '<button class="ghost">לא להזכיר שוב</button></form></td></tr>' for r in items[number * 50:(number + 1) * 50])
    previous = f'<a href="/reminders?p={number-1}">הקודמים</a>' if number else ''
    following = f'<a href="/reminders?p={number+1}">הבאים</a>' if len(items) > (number + 1) * 50 else ''
    return page('תזכורות', heading('⏰', 'התזכורות שלי') + f'<p>{len(items)} תזכורות · <a href="/?s=me#reminderprefs">🔕 הגדרות וכיבוי</a></p>'
                + (f'<table><tbody>{rows}</tbody></table><p>{previous} {following}</p>' if rows else '<p>אין תזכורות</p>')
                + f'<form method="post" action="/reminders_clear"><input type="hidden" name="t" value="{TOKEN}">'
                '<input type="hidden" name="back" value="/reminders"><button class="ghost">ביטול כל התזכורות</button></form>')
