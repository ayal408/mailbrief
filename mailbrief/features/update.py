"""Updates from GitHub Releases: check, download, and swap MailBrief.exe (the new copy replaces the old one after it closes)."""
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from mailbrief import __version__, config, net
from mailbrief.net import _PUBLIC_TLS
from mailbrief.storage import load_json

log = logging.getLogger(__name__)


REPO = 'ayal408/mailbrief'
NEW_EXE = 'MailBrief.new.exe'


def version_tuple(text):
    parts = []
    for p in text.lstrip('vV').split('.'):
        digits = ''.join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))


_FAILED = [0.0]     # when the last check failed — offline / blocked: don't slow every page down with retries


def latest_release():
    """{'version', 'url', 'size', 'sha256', 'notes', 'page'} of the newest release with MailBrief.exe, or None (offline)."""
    if time.time() - _FAILED[0] < 30 * 60:
        return None
    data = net.cached_json('release', f'https://api.github.com/repos/{REPO}/releases/latest', 30)   # GitHub allows 60 an hour
    if not data or not data.get('tag_name'):
        _FAILED[0] = time.time()
        return None
    assets = {a.get('name', '').lower(): a for a in data.get('assets', [])}
    asset = assets.get('mailbrief-setup.exe') if config.INSTALLED else assets.get('mailbrief.exe')
    if not asset:
        return None
    digest = asset.get('digest') or ''
    return {'version': data['tag_name'].lstrip('vV'), 'url': asset['browser_download_url'], 'size': asset.get('size', 0),
            'sha256': digest.split(':', 1)[1] if digest.startswith('sha256:') else '', 'notes': (data.get('body') or '')[:1500],
            'page': data.get('html_url', f'https://github.com/{REPO}/releases/latest'), 'setup': config.INSTALLED}


def update_available():
    rel = latest_release()
    return rel if rel and version_tuple(rel['version']) > version_tuple(__version__) else None


def can_self_update():
    """A winget install is updated by winget (`winget upgrade mailbrief`); an installed copy by its new setup; a loose EXE by swapping it."""
    return bool(getattr(sys, 'frozen', False)) and (config.INSTALLED or not config.MANAGED)


def download(rel, dest):
    req = urllib.request.Request(rel['url'], headers={'User-Agent': f'MailBrief/{__version__}'})
    sha, size = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=120, context=_PUBLIC_TLS) as resp, open(dest, 'wb') as out:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            if size == 0 and not chunk.startswith(b'MZ'):
                raise RuntimeError('הקובץ שהורד אינו תוכנת Windows — העדכון בוטל')
            sha.update(chunk)
            out.write(chunk)
            size += len(chunk)
    if (rel['size'] and size != rel['size']) or (rel['sha256'] and sha.hexdigest() != rel['sha256'].lower()):
        os.remove(dest)
        raise RuntimeError('ההורדה לא הושלמה כמו שצריך — העדכון בוטל, אפשר לנסות שוב')


def _detached(args, **kw):
    """Start a process that outlives MailBrief: detached, and out of MailBrief's job when Windows allows it."""
    flags = 0x00000008 | 0x00000200                  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(args, creationflags=flags | 0x01000000, **kw)   # | CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        return subprocess.Popen(args, creationflags=flags, **kw)


def start_update(rel):
    """Download next to the program and start it with --replace; the caller then closes this copy."""
    if not can_self_update():
        raise RuntimeError('MailBrief רץ מקוד המקור — לעדכון: git pull')
    if rel.get('setup'):
        setup = os.path.join(tempfile.gettempdir(), f'MailBrief-Setup-{rel["version"]}.exe')
        download(rel, setup)
        log_file = os.path.join(tempfile.gettempdir(), 'MailBrief-Setup.log')
        _detached([setup, '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/RELAUNCH=1', f'/LOG={log_file}'])
        return
    new = os.path.join(config.APP_DIR, NEW_EXE)
    download(rel, new)
    _detached([new, '--replace', sys.executable], cwd=config.APP_DIR)


def finish_update(target):
    """Runs in the downloaded copy: wait for the old MailBrief (and any scheduled run) to close, copy over it, start it."""
    for _ in range(240):
        try:
            shutil.copyfile(sys.executable, target)
            break
        except OSError:
            time.sleep(0.5)
    else:
        return
    _detached([target], cwd=os.path.dirname(target))


def cleanup():
    """In the updated program: remove the leftover download."""
    path = os.path.join(config.APP_DIR, NEW_EXE)
    if os.path.exists(path) and os.path.abspath(sys.executable) != os.path.abspath(path):
        for _ in range(20):
            try:
                os.remove(path)
                return
            except OSError:
                time.sleep(0.5)


# ---- automatic updates ---------------------------------------------------------------------------------------------------

STATUS = {'version': '', 'state': ''}       # what the update banner says: 'ready' = downloaded, waiting for a quiet moment


def auto_enabled():
    return load_json(config.SETTINGS_FILE, {}).get('auto_update', True)


def _idle_seconds():
    """Seconds since the last mouse / keyboard input anywhere in Windows."""
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000


def _window_hidden():
    import ctypes
    from mailbrief import window
    win = window.APP.get('window')
    try:
        return not win or not ctypes.windll.user32.IsWindowVisible(win.native.Handle.ToInt64())
    except Exception:
        return False


def quiet_moment():
    """Nobody is using MailBrief: its window is closed to the tray, or no mouse / keyboard for 10 minutes."""
    return _window_hidden() or _idle_seconds() > 10 * 60


def _install_now(rel):
    from mailbrief import window
    from mailbrief.tray import close_tray
    log.info('auto update: installing %s', rel['version'])
    start_update(rel)
    if not rel.get('setup'):                # a loose MailBrief.exe: the new copy waits for this one to close
        close_tray()
        window.quit_app()


def watch_auto():
    """🔄 In the background, every half hour: a new version is installed by itself at a quiet moment — MailBrief
    closes and opens again on the new version (drafts are saved as you write). Off in Settings → "עדכונים אוטומטיים"."""
    def loop():
        time.sleep(90)                          # let MailBrief finish starting first
        while True:
            try:
                rel = update_available() if auto_enabled() and can_self_update() else None
                if rel:
                    STATUS.update(version=rel['version'], state='ready')
                    from mailbrief.features.calendar import is_holy_time
                    if quiet_moment() and not is_holy_time():
                        _install_now(rel)
                        return
                    time.sleep(60)              # waiting for a quiet moment: look again in a minute
                    continue
            except Exception:
                log.exception('auto update')
            time.sleep(30 * 60)
    threading.Thread(target=loop, daemon=True, name='auto-update').start()
