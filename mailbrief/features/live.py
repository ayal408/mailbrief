"""🔴 Live mail: one quiet connection per mailbox waits on the inbox (IMAP IDLE). The moment a message arrives (or one
is read / deleted elsewhere), the open inbox page refreshes itself, and the usual alert check runs for that mailbox —
so an urgent email gets its notification within seconds instead of at the next hourly round."""
import contextlib
import threading
import time

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.storage import load_json


STATE = {'version': 0, 'running': {}, 'last_check': {}}
_LOCK = threading.Lock()
IDLE_MINUTES = 25                     # servers drop an IDLE after ~29 minutes; Microsoft tokens last an hour
ALERT_GAP = 180                       # seconds: at most one alert check per mailbox in this time


def bump():
    with _LOCK:
        STATE['version'] += 1
    return STATE['version']


def version():
    return STATE['version']


def _alerts(address):
    now = time.monotonic()
    if now - STATE['last_check'].get(address, -ALERT_GAP) < ALERT_GAP:
        return
    STATE['last_check'][address] = now
    try:
        from mailbrief.features.alerts import check_alerts
        check_alerts(only=address)
    except Exception:
        pass


def _watch(acc_id):
    delay = 30
    while True:
        acc = next((a for a in load_json(config.ACCOUNTS_FILE, []) if a.get('id') == acc_id), None)
        if not acc:                                      # the mailbox was disconnected
            STATE['running'].pop(acc_id, None)
            return
        try:
            m = imap.connect(acc)
            try:
                m.select('INBOX', readonly=True)
                delay = 30
                while True:
                    changed, new = False, False
                    with m.idle(duration=IDLE_MINUTES * 60) as idler:
                        for typ, _ in idler:
                            if typ in ('EXISTS', 'EXPUNGE', 'FETCH', b'EXISTS', b'EXPUNGE', b'FETCH'):
                                changed = True
                                new |= typ in ('EXISTS', b'EXISTS')
                                break
                    if changed:                              # the page's next list selects the folder again: fresh
                        bump()
                        if new:
                            threading.Thread(target=_alerts, args=(acc['email'],), daemon=True).start()
                    else:
                        break                                # the IDLE time ended: reconnect (fresh token)
            finally:
                with contextlib.suppress(Exception):
                    m.logout()
        except Exception:
            time.sleep(delay)                                # offline / signed out: try again a bit later
            delay = min(delay * 2, 900)


def start():
    """Start a watcher for every mailbox that has none; called on start and every few minutes (a new mailbox joins)."""
    if not hasattr(imap.imaplib.IMAP4, 'idle'):
        return
    for acc in load_json(config.ACCOUNTS_FILE, []):
        if acc.get('id') and acc['id'] not in STATE['running']:
            worker = threading.Thread(target=_watch, args=(acc['id'],), daemon=True)
            STATE['running'][acc['id']] = worker
            worker.start()
