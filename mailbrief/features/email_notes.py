"""📝 A short personal note on an email ("spoke on the phone, waiting for approval") — kept on this computer and shown
next to the email in My day for as long as it's there."""
import datetime as dt
import os

from mailbrief import config
from mailbrief.storage import load_json, save_json


def _path():
    return os.path.join(config.DATA, 'email-notes.json')


def notes():
    return load_json(_path(), {})


def set_note(key, text):
    rows = notes()
    text = (text or '').strip()[:500]
    if text:
        rows[key] = {'text': text, 'at': dt.date.today().isoformat()}
    else:
        rows.pop(key, None)
    cutoff = (dt.date.today() - dt.timedelta(days=180)).isoformat()      # old notes go by themselves
    save_json(_path(), {k: v for k, v in rows.items() if v['at'] >= cutoff})
    return text
