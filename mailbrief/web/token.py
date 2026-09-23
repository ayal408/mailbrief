"""Anti-CSRF token for the local forms (stable across restarts)."""
import os
import secrets

from mailbrief import config


def _load_token():
    """Anti-CSRF token for the settings forms. Stable across restarts so an open tab keeps working."""
    path = os.path.join(config.DATA, 'token')
    try:
        with open(path, encoding='utf-8') as f:
            token = f.read().strip()
        if len(token) >= 20:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    os.makedirs(config.DATA, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(token)
    return token


TOKEN = _load_token()
