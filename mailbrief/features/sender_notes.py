"""Local notes per sender and mailbox, with optimistic concurrency control."""
import datetime as dt

from mailbrief import config
from mailbrief.mail import mailbox
from mailbrief.storage import file_lock, load_json, save_json


def identity(address, sender):
    account = mailbox.account(address)['email'].lower()
    sender = (sender or '').strip().lower()
    if '@' not in sender or len(sender) > 320 or any(ord(c) < 33 for c in sender):
        raise ValueError('כתובת השולח אינה תקינה')
    return account + '\x01' + sender


def get_note(address, sender):
    return load_json(config.SENDER_NOTES_FILE, {}).get(identity(address, sender), {'text': '', 'revision': 0, 'updated': ''})


def save_note(address, sender, text, revision):
    key = identity(address, sender)
    if len(text) > 3000:
        raise ValueError('אפשר לשמור עד 3000 תווים בהערה')
    with file_lock(config.SENDER_NOTES_FILE):
        rows = load_json(config.SENDER_NOTES_FILE, {})
        previous = rows.get(key, {'revision': 0})
        if revision != previous['revision']:
            raise ValueError('ההערה עודכנה בחלון אחר. העתיקי את הטקסט שלך ופתחי את הפרופיל מחדש לפני שמירה')
        note = {'text': text, 'revision': revision + 1, 'updated': dt.datetime.now().astimezone().isoformat(timespec='seconds')}
        rows[key] = note
        save_json(config.SENDER_NOTES_FILE, rows)
    return note
