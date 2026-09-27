"""🔒 A PIN for opening MailBrief: a privacy screen against someone sitting at your computer. It locks again after a
while without use. (It is not encryption — whoever controls the Windows user can still reach the data folder.)"""
import hashlib
import hmac
import secrets
import time

from mailbrief import config
from mailbrief.storage import load_json, save_json


COOKIE = 'mb_unlock'
_FAILS = {'count': 0, 'until': 0.0}


def cfg():
    return load_json(config.SETTINGS_FILE, {}).get('pin') or {}


def enabled():
    return bool(cfg().get('hash'))


def idle_minutes():
    return int(cfg().get('idle', 15))


def _hash(pin, salt):
    return hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex()


def set_pin(pin, idle=15):
    if not pin.isdigit() or not 4 <= len(pin) <= 8:
        raise ValueError('הקוד צריך להיות 4 עד 8 ספרות')
    salt = secrets.token_hex(16)
    settings = load_json(config.SETTINGS_FILE, {})
    settings['pin'] = {'hash': _hash(pin, salt), 'salt': salt, 'idle': max(1, min(int(idle), 240))}
    save_json(config.SETTINGS_FILE, settings)


def clear_pin():
    settings = load_json(config.SETTINGS_FILE, {})
    settings.pop('pin', None)
    save_json(config.SETTINGS_FILE, settings)


def check(pin):
    """True when right. After 5 wrong tries, waits 30 seconds before the next one. Raises RuntimeError while waiting."""
    if time.monotonic() < _FAILS['until']:
        raise RuntimeError(f'יותר מדי ניסיונות — אפשר לנסות שוב בעוד {int(_FAILS["until"] - time.monotonic()) + 1} שניות')
    c = cfg()
    ok = bool(c.get('hash')) and hmac.compare_digest(_hash(pin or '', c['salt']), c['hash'])
    if ok:
        _FAILS['count'] = 0
    else:
        _FAILS['count'] += 1
        if _FAILS['count'] >= 5:
            _FAILS.update(count=0, until=time.monotonic() + 30)
    return ok


def _sign(stamp, key):
    return hmac.new(key.encode(), f'unlock|{stamp}'.encode(), hashlib.sha256).hexdigest()[:32]


def ticket(key, now=None):
    """The cookie value after unlocking — renewed on every page, so it only runs out after `idle` minutes without use."""
    stamp = int(now or time.time())
    return f'{stamp}.{_sign(stamp, key)}'


def valid(value, key, now=None):
    try:
        stamp, sig = (value or '').split('.', 1)
        stamp = int(stamp)
    except ValueError:
        return False
    now = now or time.time()
    return hmac.compare_digest(sig, _sign(stamp, key)) and 0 <= now - stamp <= idle_minutes() * 60
