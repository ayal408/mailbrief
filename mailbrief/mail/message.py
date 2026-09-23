"""Reading an email: headers, readable body text, links."""
import html
import re
from email.header import decode_header
from email.header import make_header


def decode(value) -> str:
    if not value:
        return ''
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _part_text(part):
    if part is None:
        return ''
    try:
        text = part.get_content()
    except Exception:
        return ''
    if part.get_content_type() == 'text/html':
        text = re.sub(r'(?is)<(script|style).*?</\1>', ' ', text)
        text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
    return re.sub(r'\s+', ' ', text).strip()


def body_text(msg) -> str:
    """Plain text, unless it's just a "view this as HTML" placeholder (common with banks and card companies)."""
    try:
        plain = _part_text(msg.get_body(preferencelist=('plain',)))
        placeholder = re.search(r'view(?:ed)? (?:it )?(?:as|in) HTML|designed to be viewed as HTML', plain, re.I)
        if len(plain) >= 200 and not placeholder:
            return plain
        rich = _part_text(msg.get_body(preferencelist=('html',)))
        if placeholder and rich:
            return rich
        return rich if len(rich) > len(plain) else plain
    except Exception:
        return ''


def html_links(msg):
    part = msg.get_body(preferencelist=('html',))
    try:
        raw = part.get_content() if part is not None else ''
    except Exception:
        return []
    return [(href, html.unescape(re.sub(r'<[^>]+>', '', text)).strip())
            for href, text in re.findall(r'(?is)<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw)[:200]]
