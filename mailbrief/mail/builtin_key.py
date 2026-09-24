"""MailBrief's own Google sign-in key (a "Desktop app" client of the MailBrief project), so users just click
"Connect with Google". Google treats a desktop app's client secret as not confidential (it ships inside every copy of
the program); it is kept scrambled here only so it is not readable at a glance. A user's own key in the settings wins."""
import base64

_PAD = b'MailBrief-desktop/2026'
_ID = 'dFlbWXFHWlZXGlxQXlNCDEFJAgICVzsOW18gEVFXFRwLChxSRFsZGFEJW18uTwgcMgFHAglCAwkWHgcKAkxdXkZTIxVHDy0f'
_SECRET = 'Ci4qPxIqRC8cazwnAl0yVghGV3t+AyUzWgl6MTMtKUEAEUo='


def _open(sealed):
    raw = base64.b64decode(sealed)
    return bytes(b ^ _PAD[i % len(_PAD)] for i, b in enumerate(raw)).decode()


def google():
    """(client_id, client_secret)"""
    return _open(_ID), _open(_SECRET)
