"""Stage verified official installers; apply only on the next app startup."""
import hashlib
import os
import re
import subprocess
import urllib.request

from mailbrief import __version__, config, net
from mailbrief.features.update import REPO, update_available, version_tuple
from mailbrief.storage import file_lock, load_json, save_json


MAX_INSTALLER = 200 * 1024 * 1024


def enabled():
    return bool(config.INSTALLED and load_json(config.SETTINGS_FILE, {}).get('auto_update', True))


def installer_path(version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version or ''):
        raise ValueError('מספר גרסת העדכון אינו תקין')
    return os.path.join(config.DATA, 'updates', version, 'MailBrief-Setup.exe')


def verify(path, digest, size):
    if not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest) or not isinstance(size, int) or not 500_000 <= size <= MAX_INSTALLER:
        raise ValueError('פרטי האימות של העדכון חסרים או אינם תקינים')
    if os.path.getsize(path) != size:
        raise ValueError('גודל קובץ העדכון אינו תואם')
    checksum = hashlib.sha256()
    with open(path, 'rb') as source:
        if source.read(2) != b'MZ':
            raise ValueError('הקובץ אינו מתקין Windows')
        source.seek(0)
        for chunk in iter(lambda: source.read(256 * 1024), b''):
            checksum.update(chunk)
    if checksum.hexdigest().lower() != digest.lower():
        raise ValueError('אימות קובץ העדכון נכשל')


def stage_latest():
    if not enabled():
        return False
    with file_lock(config.UPDATE_STATE_FILE):
        try:
            release = update_available()
            if not release:
                return False
            path = installer_path(release['version'])
            expected = f'https://github.com/{REPO}/releases/download/v{release["version"]}/MailBrief-Setup.exe'
            if release['url'] != expected:
                raise ValueError('כתובת העדכון אינה ההפצה הרשמית')
            digest, size = release.get('sha256', ''), release.get('size', 0)
            if not re.fullmatch(r'[a-fA-F0-9]{64}', digest) or not isinstance(size, int) or not 500_000 <= size <= MAX_INSTALLER:
                raise ValueError('העדכון זמין להורדה ידנית בלבד: חסרים פרטי אימות')
            state = read_state()
            if state.get('version') == release['version'] and os.path.isfile(path):
                verify(path, digest, size)
                return True
            os.makedirs(os.path.dirname(path), exist_ok=True)
            partial = path + '.part'
            try:
                request = urllib.request.Request(expected, headers={'User-Agent': 'MailBrief/' + __version__})
                with urllib.request.urlopen(request, timeout=30, context=net.TLS) as response, open(partial, 'wb') as target:
                    downloaded = 0
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > size:
                            raise ValueError('הורדת העדכון חרגה מהגודל הצפוי')
                        target.write(chunk)
                verify(partial, digest, size)
                os.replace(partial, path)
            finally:
                if os.path.exists(partial):
                    os.remove(partial)
            save_json(config.UPDATE_STATE_FILE, {'version': release['version'], 'sha256': digest, 'size': size, 'launched': False})
            return True
        except Exception as exc:
            state = read_state()
            state['error'] = net.explain(exc)[:300]
            save_json(config.UPDATE_STATE_FILE, state)
            return False


def launch_staged():
    """Called after the single-instance lock, before any window or server starts."""
    if not enabled():
        return False
    with file_lock(config.UPDATE_STATE_FILE):
        state = read_state()
        version = state.get('version', '')
        if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version) or state.get('launched') or version_tuple(version) <= version_tuple(__version__):
            return False
        try:
            path = installer_path(version)
            verify(path, state.get('sha256', ''), state.get('size', 0))
            # Recheck the opt-out immediately before launching an installer.
            if not enabled():
                return False
            state['launched'] = True
            state.pop('error', None)
            save_json(config.UPDATE_STATE_FILE, state)
            subprocess.Popen([path, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/AUTOUPDATE=1',
                              '/DIR=' + config.APP_DIR, '/LOG=' + os.path.join(config.DATA, 'update-install.log')],
                             close_fds=True)
            return True
        except Exception as exc:
            state.update(launched=False, error=net.explain(exc)[:300])
            save_json(config.UPDATE_STATE_FILE, state)
            return False


def schedule_check():
    if enabled():
        from mailbrief.background import submit
        submit('auto-update', stage_latest, cooldown=30 * 60)


def read_state():
    state = load_json(config.UPDATE_STATE_FILE, {})
    return state if isinstance(state, dict) else {}
