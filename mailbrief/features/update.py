"""Updates from GitHub Releases: check, download, and swap MailBrief.exe (the new copy replaces the old one after it closes)."""
import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request

from mailbrief import __version__, config, net
from mailbrief.net import _PUBLIC_TLS


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
    data = net.cached_json('release', f'https://api.github.com/repos/{REPO}/releases/latest', 6 * 60)
    if not data or not data.get('tag_name'):
        _FAILED[0] = time.time()
        return None
    asset = next((a for a in data.get('assets', []) if a.get('name', '').lower() == 'mailbrief.exe'), None)
    if not asset:
        return None
    digest = asset.get('digest') or ''
    return {'version': data['tag_name'].lstrip('vV'), 'url': asset['browser_download_url'], 'size': asset.get('size', 0),
            'sha256': digest.split(':', 1)[1] if digest.startswith('sha256:') else '', 'notes': (data.get('body') or '')[:1500],
            'page': data.get('html_url', f'https://github.com/{REPO}/releases/latest')}


def update_available():
    rel = latest_release()
    return rel if rel and version_tuple(rel['version']) > version_tuple(__version__) else None


def can_self_update():
    """A winget install is updated by winget (`winget upgrade mailbrief`), not by swapping the file."""
    return bool(getattr(sys, 'frozen', False)) and not config.MANAGED


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


def start_update(rel):
    """Download next to the program and start it with --replace; the caller then closes this copy."""
    if not can_self_update():
        raise RuntimeError('MailBrief רץ מקוד המקור — לעדכון: git pull')
    new = os.path.join(config.APP_DIR, NEW_EXE)
    download(rel, new)
    subprocess.Popen([new, '--replace', sys.executable], cwd=config.APP_DIR, creationflags=0x00000008 | 0x00000200)   # detached


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
    subprocess.Popen([target], cwd=os.path.dirname(target), creationflags=0x00000008 | 0x00000200)


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
