"""Deduplicated background refreshes; rendering a page never waits for optional I/O."""
import logging
import threading
import time

from mailbrief import config

_GUARD = threading.Lock()
_RUNNING = set()
_STARTED = {}


def submit(key, work, cooldown=60):
    identity = (config.DATA, key)
    with _GUARD:
        if identity in _RUNNING or time.monotonic() - _STARTED.get(identity, float('-inf')) < cooldown:
            return
        _RUNNING.add(identity)
        _STARTED[identity] = time.monotonic()

    def run():
        try:
            work()
        except Exception:
            logging.getLogger('mailbrief').debug('background refresh failed: %s', key, exc_info=True)
        finally:
            with _GUARD:
                _RUNNING.discard(identity)
    threading.Thread(target=run, daemon=True, name='refresh-' + key).start()


def pending():
    with _GUARD:
        return any(root == config.DATA for root, _ in _RUNNING)
