"""Quick sorting: emails waiting for an answer, one at a time. "Done" hides one from here and from "My day"."""
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json, save_json


def triage_key(row):
    return f"{row.get('account', '')}|{row.get('message_id') or row.get('subject', '')}"


def dismissed():
    return load_json(config.TRIAGE_FILE, {})


def dismiss(key):
    done = dismissed()
    done[key] = dt.date.today().isoformat()
    cutoff = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    save_json(config.TRIAGE_FILE, {k: v for k, v in done.items() if v >= cutoff})


def undo(key):
    done = dismissed()
    done.pop(key, None)
    save_json(config.TRIAGE_FILE, done)


def queue():
    """Waiting-for-me first (oldest wait first), then conversations waiting on others."""
    from mailbrief.view import current_account, mine as in_view
    snap, done, box = load_json(config.SNAPSHOT_FILE, {}), dismissed(), current_account()
    mine = [r | {'kind': 'mine'} for r in snap.get('waiting', []) if triage_key(r) not in done and in_view(r, current=box)]
    theirs = [r | {'kind': 'theirs', 'from': r.get('to', '')} for r in snap.get('awaiting', [])
              if triage_key(r) not in done and in_view(r, current=box)]
    return mine + theirs
