"""Check GitHub Releases for new versions. Installation stays an explicit user action."""
import time

from mailbrief import __version__, net
from mailbrief.storage import load_json


REPO = 'ayal408/mailbrief'
_FAILED = [0.0]     # when the last check failed — offline / blocked: don't slow every page down with retries


def version_tuple(text):
    parts = []
    for part in text.lstrip('vV').split('.'):
        digits = ''.join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))


def latest_release():
    """Metadata for the newest release, or None when GitHub is unavailable."""
    if time.time() - _FAILED[0] < 30 * 60:
        return None
    data = net.cached_json('release', f'https://api.github.com/repos/{REPO}/releases/latest', 30)
    if not data or not data.get('tag_name'):
        _FAILED[0] = time.time()
        return None
    return _release_info(data)


def _release_info(data):
    if not data or not data.get('tag_name'):
        return None
    assets = {asset.get('name', '').lower(): asset for asset in data.get('assets', [])}
    asset = assets.get('mailbrief-setup.exe')
    if not asset:
        return None
    digest = asset.get('digest') or ''
    return {'version': data['tag_name'].lstrip('vV'), 'url': asset['browser_download_url'], 'size': asset.get('size', 0),
            'sha256': digest.split(':', 1)[1] if digest.startswith('sha256:') else '', 'notes': (data.get('body') or '')[:1500],
            'page': data.get('html_url', f'https://github.com/{REPO}/releases/latest')}


def update_available():
    rel = latest_release()
    return rel if rel and version_tuple(rel['version']) > version_tuple(__version__) else None


def cached_update():
    """Read the last release immediately and refresh it off the request thread."""
    from mailbrief import config
    from mailbrief.background import submit
    cache = load_json(config.CACHE_FILE, {})
    hit = cache.get('release')
    if not hit or time.time() - hit.get('at', 0) >= 30 * 60:
        submit('release', latest_release, cooldown=30 * 60)
    rel = _release_info(hit.get('data') if hit else None)
    return rel if rel and version_tuple(rel['version']) > version_tuple(__version__) else None
