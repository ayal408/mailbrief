"""An encrypted copy of the backup in Google Drive — for a computer that breaks or is replaced.
The file is locked with a password only the user knows (scrypt + HMAC-SHA256, standard library only): Google stores
a file it cannot read, and MailBrief keeps no copy of the password except, if asked, DPAPI-encrypted on this computer
for the weekly automatic upload. Uses the drive.file permission: MailBrief sees only the files it created itself."""
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.request
from urllib.parse import urlencode

from mailbrief import config
from mailbrief.features.google_apps import _token
from mailbrief.features.maintenance import list_backups, make_backup
from mailbrief.net import _PUBLIC_TLS
from mailbrief.storage import decrypt, encrypt, load_json, save_json


SCOPE = 'https://www.googleapis.com/auth/drive.file'
MAGIC = b'MBK1'
FOLDER = 'MailBrief גיבויים'
KEEP = 8


# ---- the lock ---------------------------------------------------------------------------------------------------------

def _keys(password, salt):
    raw = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=64)
    return raw[:32], raw[32:]


def _stream(key, nonce, length):
    out, counter = bytearray(), 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, 'big'), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _xor(a, b):
    return (int.from_bytes(a, 'big') ^ int.from_bytes(b, 'big')).to_bytes(len(a), 'big') if a else b''


def seal(data, password):
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(16)
    enc, mac = _keys(password, salt)
    body = _xor(data, _stream(enc, nonce, len(data)))
    head = MAGIC + salt + nonce
    return head + body + hmac.new(mac, head + body, hashlib.sha256).digest()


def unseal(blob, password):
    if len(blob) < 68 or not blob.startswith(MAGIC):
        raise ValueError('זה לא קובץ גיבוי של MailBrief')
    head, body, tag = blob[:36], blob[36:-32], blob[-32:]
    enc, mac = _keys(password, head[4:20])
    if not hmac.compare_digest(tag, hmac.new(mac, head + body, hashlib.sha256).digest()):
        raise ValueError('הסיסמה שגויה (או שהקובץ נפגם)')
    return _xor(body, _stream(enc, head[20:36], len(body)))


# ---- settings ---------------------------------------------------------------------------------------------------------

def cloud_cfg():
    return load_json(config.SETTINGS_FILE, {}).get('cloud') or {}


def drive_account(accounts=None):
    accounts = load_json(config.ACCOUNTS_FILE, []) if accounts is None else accounts
    chosen = cloud_cfg().get('account', '').lower()
    linked = [a for a in accounts if a.get('drive')]
    return next((a for a in linked if a['email'].lower() == chosen), linked[0] if linked else None)


def save_cfg(auto, password=''):
    settings = load_json(config.SETTINGS_FILE, {})
    cfg = settings.setdefault('cloud', {})
    cfg['auto'] = bool(auto)
    if password:
        cfg['password'] = encrypt(password)       # only for the weekly automatic upload; DPAPI, this Windows user only
    if not auto:
        cfg.pop('password', None)
    save_json(config.SETTINGS_FILE, settings)


# ---- Google Drive -----------------------------------------------------------------------------------------------------

def _call(acc, method, url, data=None, ctype='application/json'):
    req = urllib.request.Request(url, method=method, data=data,
                                 headers={'Authorization': f'Bearer {_token(acc)}', 'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=60, context=_PUBLIC_TLS) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        if exc.code == 403 and ('accessNotConfigured' in detail or 'has not been used' in detail):
            raise RuntimeError('צריך להפעיל את Google Drive API בפרויקט ב-Google Cloud') from None
        if exc.code in (401, 403):
            raise RuntimeError('אין הרשאה ל-Google Drive — צריך ללחוץ שוב „חיבור ל-Google Drive”') from None
        raise RuntimeError(f'Google Drive: שגיאה {exc.code}') from None
    return raw


def _folder(acc):
    settings = load_json(config.SETTINGS_FILE, {})
    known = (settings.get('cloud') or {}).get('folder')
    if known:
        return known
    body = json.dumps({'name': FOLDER, 'mimeType': 'application/vnd.google-apps.folder'}).encode()
    folder = json.loads(_call(acc, 'POST', 'https://www.googleapis.com/drive/v3/files', body))['id']
    settings.setdefault('cloud', {})['folder'] = folder
    save_json(config.SETTINGS_FILE, settings)
    return folder


def remote_backups(acc):
    q = f"'{_folder(acc)}' in parents and trashed = false"
    url = 'https://www.googleapis.com/drive/v3/files?' + urlencode({'q': q, 'orderBy': 'createdTime desc',
                                                                     'fields': 'files(id,name,size,createdTime)'})
    return json.loads(_call(acc, 'GET', url)).get('files', [])


def upload(password, acc=None):
    """Makes a fresh backup, locks it and uploads it; keeps the newest 8 in Drive. Returns the file name."""
    acc = acc or drive_account()
    if not acc:
        raise RuntimeError('קודם צריך לחבר את Google Drive')
    if len(password) < 8:
        raise RuntimeError('הסיסמה צריכה להיות באורך 8 תווים לפחות')
    path = make_backup('cloud')
    with open(path, 'rb') as f:
        blob = seal(f.read(), password)
    name = os.path.basename(path)[:-4] + '.mbk'
    boundary = secrets.token_hex(12)
    meta = json.dumps({'name': name, 'parents': [_folder(acc)]}).encode()
    body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode() + meta +
            f'\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + blob + f'\r\n--{boundary}--'.encode())
    _call(acc, 'POST', 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart', body,
          f'multipart/related; boundary={boundary}')
    for old in remote_backups(acc)[KEEP:]:
        try:
            _call(acc, 'DELETE', f'https://www.googleapis.com/drive/v3/files/{old["id"]}')
        except RuntimeError:
            pass
    settings = load_json(config.SETTINGS_FILE, {})
    settings.setdefault('cloud', {})['last'] = dt.datetime.now().strftime('%d/%m/%Y %H:%M')
    save_json(config.SETTINGS_FILE, settings)
    return name


def download(file_id, password, acc=None):
    """Brings a backup back from Drive into the local backups folder (then "restore" works as usual). Returns its name."""
    acc = acc or drive_account()
    if not acc:
        raise RuntimeError('קודם צריך לחבר את Google Drive')
    files = {f['id']: f['name'] for f in remote_backups(acc)}
    if file_id not in files:
        raise RuntimeError('הגיבוי לא נמצא ב-Drive')
    data = unseal(_call(acc, 'GET', f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media'), password)
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    name = files[file_id][:-4] + '.zip'
    if not name.startswith('mailbrief-') or os.path.basename(name) != name:
        raise RuntimeError('שם קובץ לא צפוי')
    with open(os.path.join(config.BACKUP_DIR, name), 'wb') as f:
        f.write(data)
    return name if name in list_backups() else ''


def maybe_weekly(state):
    """With the weekly brief: an automatic upload, when turned on (and a password was saved for it)."""
    cfg = cloud_cfg()
    week = dt.date.today().strftime('%G-%V')
    if not cfg.get('auto') or not cfg.get('password') or state.get('_cloud_week') == week or not drive_account():
        return False
    upload(decrypt(cfg['password']))
    state['_cloud_week'] = week
    return True
