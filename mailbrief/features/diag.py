"""The error log and the "problem report": what went wrong and where — never mail content, passwords or tokens."""
import datetime as dt
import glob
import logging
import logging.handlers
import os
import platform
import re
import sys
import threading
import zipfile

from mailbrief import __version__, config
from mailbrief.storage import load_json


def log_dir():
    return os.path.join(config.DATA, 'logs')


def log_file():
    return os.path.join(log_dir(), 'mailbrief.log')


def setup_logging():
    """Errors from anywhere in the program (the page, the timers, the tray) go to data/logs/mailbrief.log (3 × 512KB)."""
    root = logging.getLogger()
    if any(getattr(h, '_mailbrief', False) for h in root.handlers):
        return
    try:
        os.makedirs(log_dir(), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(log_file(), maxBytes=512_000, backupCount=3, encoding='utf-8')
    except OSError:
        return
    handler._mailbrief = True
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S'))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    sys.excepthook = lambda kind, exc, tb: logging.getLogger('mailbrief').error('uncaught', exc_info=(kind, exc, tb))
    threading.excepthook = lambda a: logging.getLogger('mailbrief').error(
        f'uncaught in thread {a.thread.name if a.thread else "?"}', exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def log_error(where):
    """Call inside an except block."""
    logging.getLogger('mailbrief').exception(where)


EMAIL = re.compile(r'([\w.+-])[\w.+-]*@([\w-]+(?:\.[\w-]+)+)')
SECRET = re.compile(r'\b[\w\-/+=]{32,}\b')


def redact(text):
    """Addresses keep their first letter and domain (a***@gmail.com); long tokens / keys are removed."""
    return SECRET.sub('[…]', EMAIL.sub(r'\1***@\2', text))


def _about():
    accounts = load_json(config.ACCOUNTS_FILE, [])
    kinds = {}
    for a in accounts:
        kind = a.get('auth') or a.get('host', '?').split('.', 1)[-1]
        kinds[kind] = kinds.get(kind, 0) + 1
    lines = [
        f'MailBrief {__version__}',
        f'Created: {dt.datetime.now():%Y-%m-%d %H:%M}',
        f'Windows: {platform.platform()} ({platform.machine()})',
        f'Python: {sys.version.split()[0]} · packaged: {bool(getattr(sys, "frozen", False))} · installed: {config.INSTALLED} · managed: {config.MANAGED}',
        f'Data folder: {config.HERE}',
        f'Mailboxes: {len(accounts)} ' + (', '.join(f'{k}×{v}' for k, v in sorted(kinds.items())) if kinds else ''),
    ]
    try:
        from mailbrief.features.maintenance import health_checks
        lines += ['', 'Health check:'] + [f'  {"OK " if ok else "!! "} {area}: {detail}' for area, ok, detail in health_checks()]
    except Exception as exc:
        lines += ['', f'Health check failed: {exc!r}']
    return redact('\n'.join(lines))


def _desktop():
    path = os.path.join(os.path.expanduser('~'), 'Desktop')
    return path if os.path.isdir(path) else config.HERE


def problem_report(folder=None):
    """A zip with the version, Windows, the health check and the error logs — addresses masked, no mail content.
    Returns its path; the user decides whether to send it."""
    folder = folder or _desktop()
    path = os.path.join(folder, f'MailBrief-דוח-תקלה-{dt.datetime.now():%Y-%m-%d-%H%M}.zip')
    logs = sorted(glob.glob(os.path.join(log_dir(), 'mailbrief.log*'))) + [
        p for p in (os.path.join(config.DATA, n) for n in ('setup.log', 'tray.log', 'last-run.log', 'last-check.log', 'skipped.log'))
        if os.path.isfile(p)]
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('about.txt', _about())
        for p in logs:
            try:
                with open(p, encoding='utf-8', errors='replace') as f:
                    z.writestr('logs/' + os.path.basename(p) + ('' if p.endswith('.log') else '.txt'), redact(f.read()[-400_000:]))
            except OSError:
                pass
    return path
