"""Outbound HTTPS for public data (weather, calendar, rates) and the safety check for links found in emails."""
import datetime as dt
import ipaddress
import json
import socket
import ssl
import urllib.request
from urllib.parse import urlparse

from mailbrief import config
from mailbrief.storage import load_json, save_json


_PUBLIC_TLS = ssl.create_default_context()


_PUBLIC_TLS.verify_flags &= ~getattr(ssl, 'VERIFY_X509_STRICT', 0)   # still verified; just not the 3.13+ strict extras


def cached_json(key, url, max_age_min):
    cache = load_json(config.CACHE_FILE, {})
    hit = cache.get(key)
    if hit and hit.get('url') == url and (dt.datetime.now().timestamp() - hit['at']) < max_age_min * 60:
        return hit['data']
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MailBrief/1.0'})
        with urllib.request.urlopen(req, timeout=8, context=_PUBLIC_TLS) as resp:
            data = json.load(resp)
    except Exception:
        return hit['data'] if hit else None     # offline: show the last known value
    cache[key] = {'url': url, 'at': dt.datetime.now().timestamp(), 'data': data}
    save_json(config.CACHE_FILE, cache)
    return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def safe_public_https(url):
    """Links come from emails (untrusted): allow only https to public internet hosts."""
    parts = urlparse(url)
    if parts.scheme != 'https' or not parts.hostname:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, 443)}
    except OSError:
        return False
    return all(ipaddress.ip_address(a.split('%')[0]).is_global for a in addresses)
