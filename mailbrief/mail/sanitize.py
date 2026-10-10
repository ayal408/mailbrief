"""Showing an email's HTML safely. An email is untrusted content, so it passes three walls:
1. this allow-list cleaner — only known-harmless tags and attributes survive; no scripts, forms, frames or event handlers;
2. the page that shows it is served with a Content-Security-Policy "sandbox" (no scripts at all, its own null origin —
   it cannot reach MailBrief even if something slipped through);
3. pictures from the internet are blocked until the user asks for them (a hidden picture tells the sender you opened it)."""
import base64
import html
import re
from html.parser import HTMLParser


ALLOWED = {
    'a', 'abbr', 'address', 'article', 'aside', 'b', 'bdi', 'bdo', 'big', 'blockquote', 'br', 'caption', 'center', 'cite',
    'code', 'col', 'colgroup', 'dd', 'del', 'details', 'dfn', 'div', 'dl', 'dt', 'em', 'figcaption', 'figure', 'font', 'footer',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'i', 'img', 'ins', 'kbd', 'label', 'li', 'main', 'mark', 'nav', 'ol', 'p',
    'pre', 'q', 's', 'samp', 'section', 'small', 'span', 'strike', 'strong', 'sub', 'summary', 'sup', 'table', 'tbody', 'td',
    'tfoot', 'th', 'thead', 'time', 'tr', 'tt', 'u', 'ul', 'var', 'wbr', 'style'}
VOID = {'br', 'col', 'hr', 'img', 'wbr'}
DROP_WITH_CONTENT = {'script', 'noscript', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet', 'template', 'svg',
                     'math', 'title', 'head', 'select', 'textarea', 'button', 'audio', 'video', 'canvas', 'xml'}
ATTRS = {'align', 'alt', 'bgcolor', 'border', 'cellpadding', 'cellspacing', 'class', 'color', 'colspan', 'dir', 'face',
         'height', 'hspace', 'id', 'lang', 'nowrap', 'rowspan', 'size', 'span', 'start', 'style', 'summary', 'title', 'type',
         'valign', 'vspace', 'width', 'open', 'datetime', 'cite'}
SAFE_LINK = re.compile(r'(?i)^(https?:|mailto:|tel:|#)')
DATA_IMAGE = re.compile(r'(?i)^data:image/(png|jpe?g|gif|webp|bmp);base64,[a-z0-9+/=\s]+$')
BAD_CSS = re.compile(r'(?i)expression\s*\(|javascript:|vbscript:|behavior\s*:|-moz-binding|@import|@charset|</')
CSS_URL = re.compile(r'(?i)url\(\s*([\'"]?)(.*?)\1\s*\)')
CSS_ESCAPE = re.compile(r'\\([0-9a-fA-F]{1,6})\s?|\\(.)', re.S)
REMOTE = re.compile(r'(?i)(?:https?:)?//[^\s\'")]+')


def _unescape_css(css):
    """u\\72l( and url\\28 are url( to a browser: decode the escapes before looking, so the rules can't be dodged."""
    def char(m):
        if m.group(1):
            code = int(m.group(1), 16)
            return chr(code) if 0 < code < 0x110000 and not 0xD800 <= code <= 0xDFFF else ''
        return m.group(2) if m.group(2) not in '\r\n\f' else ''
    return CSS_ESCAPE.sub(char, css)


def clean_css(css, images):
    css = re.sub(r'/\*.*?(\*/|$)', '', _unescape_css(css), flags=re.S)    # comments can split words: exp/**/ression
    css = BAD_CSS.sub('', css)

    def url(match):
        target = match.group(2).strip()
        if DATA_IMAGE.match(target) or (images and re.match(r'(?i)^https?://', target)):
            return f'url("{target.replace(chr(34), "").replace(chr(92), "")}")'
        return 'none'
    css = CSS_URL.sub(url, css)
    if not images:                                       # image-set('https://…'), @font-face src: '…' — any address
        css = re.sub(r'(?i)url\("(?!data:)[^"]*"\)', 'none', css)
        parts = re.split(r'(url\("data:[^"]*"\))', css)          # base64 may hold "//": leave the data: pictures whole
        css = ''.join(p if p.startswith('url("data:') else REMOTE.sub('', p) for p in parts)
    return css


class _Cleaner(HTMLParser):
    def __init__(self, inline, images, collapse=False):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip = [], [], 0
        self.inline, self.images, self.blocked = inline, images, 0
        self.collapse, self.quote_until, self.quote_inside = collapse, None, False  # the fold closes when the stack gets shorter

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self.skip += 1
            return
        if self.skip or tag not in ALLOWED:
            return
        kept = []
        for name, value in attrs:
            name, value = name.lower(), value or ''
            if name == 'style':
                kept.append((name, clean_css(value, self.images)))
            elif name == 'background':
                if self.images and re.match(r'(?i)^https?://', value):
                    kept.append((name, value))
                elif value:
                    self.blocked += 1
            elif name in ATTRS:
                kept.append((name, value))
            elif name == 'href' and tag == 'a':
                if SAFE_LINK.match(value.strip()):
                    kept.append((name, value.strip()))
            elif name == 'src' and tag == 'img':
                src = self._image(value.strip())
                if src:
                    kept.append((name, src))
        if tag == 'a':
            kept += [('target', '_blank'), ('rel', 'noopener noreferrer')]
        if tag == 'img' and not any(n == 'src' for n, _ in kept):
            kept.append(('data-blocked', '1'))
        if self.collapse and self.quote_until is None and tag not in VOID:    # earlier messages under a reply: folded (•••)
            found = dict(attrs)
            if tag == 'blockquote' or re.search(r'gmail_quote|yahoo_quoted|moz-cite-prefix', found.get('class') or ''):
                self.out.append(QUOTE_OPEN)
                self.quote_until = len(self.stack) + 1
            elif tag == 'div' and (found.get('id') or '') in ('divRplyFwdMsg', 'appendonsend'):   # Outlook: the rest of its parent
                self.out.append(QUOTE_OPEN)
                self.quote_until, self.quote_inside = len(self.stack), True
        attrs_html = ''.join(f' {n}="{html.escape(v, quote=True)}"' for n, v in kept)
        self.out.append(f'<{tag}{attrs_html}>')
        if tag not in VOID:
            self.stack.append(tag)

    def _image(self, src):
        if src.lower().startswith('cid:'):
            return self.inline.get(src[4:].strip('<>').lower(), '')
        if DATA_IMAGE.match(src):
            return src
        if re.match(r'(?i)^https?://', src):
            if self.images:
                return src
            self.blocked += 1
        return ''

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() in self.stack[-1:] and tag.lower() not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DROP_WITH_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED or tag in VOID or tag not in self.stack:
            return
        while self.stack:
            top = self.stack.pop()
            if self.quote_inside:                          # Outlook: the fold closes inside its parent, before </parent>
                self._end_quote()
            self.out.append(f'</{top}>')
            self._end_quote()
            if top == tag:
                break

    def _end_quote(self):
        if self.quote_until is not None and len(self.stack) < self.quote_until:
            self.out.append('</details>')
            self.quote_until, self.quote_inside = None, False

    def handle_data(self, data):
        if self.skip:
            return
        if self.stack and self.stack[-1] == 'style':
            self.out.append(clean_css(data, self.images).replace('<', ''))
        else:
            self.out.append(html.escape(data, quote=False))

    def close(self):
        super().close()
        while self.stack:
            top = self.stack.pop()
            if self.quote_inside:
                self._end_quote()
            self.out.append(f'</{top}>')
            self._end_quote()
        if self.quote_until is not None:
            self.out.append('</details>')


QUOTE_OPEN = '<details class="mb-q"><summary title="הצגת ההודעות הקודמות">•••</summary>'


def inline_images(msg, limit=4_000_000):
    """cid: pictures of the body as data: addresses (the shown page can't load anything from MailBrief itself)."""
    out, total = {}, 0
    for part in msg.walk():
        cid = (part.get('Content-ID') or '').strip().strip('<>').lower()
        if not cid or not part.get_content_type().startswith('image/'):
            continue
        data = part.get_payload(decode=True) or b''
        if not data or total + len(data) > limit:
            continue
        total += len(data)
        subtype = part.get_content_subtype() if part.get_content_subtype() in ('png', 'jpeg', 'jpg', 'gif', 'webp', 'bmp') else 'png'
        out[cid] = f'data:image/{subtype};base64,' + base64.b64encode(data).decode()
    return out


def clean_html(raw, inline=None, images=False, collapse=False):
    """(safe html, number of blocked internet pictures). collapse: fold the quoted earlier messages (for reading)."""
    raw = re.sub(r'(?is)<!--.*?-->', '', raw or '')
    cleaner = _Cleaner(inline or {}, images, collapse)
    cleaner.feed(raw)
    cleaner.close()
    return ''.join(cleaner.out), cleaner.blocked


LINK = re.compile(r'(https?://[^\s<>"\'()]+[^\s<>"\'().,;:!?])')


def text_to_html(text, collapse=False):
    """A plain-text email: kept as written, links clickable, quoted lines (>) grey — and folded when reading."""
    lines, quoted = [], False
    for line in (text or '').splitlines():
        safe = LINK.sub(lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>',
                        html.escape(line, quote=False))
        is_quote = line.startswith('>')
        if collapse and quoted and not is_quote:
            lines[-1] += '</details>'
        if collapse and is_quote and not quoted:
            safe = QUOTE_OPEN + f'<span class="q">{safe}</span>'
        elif is_quote:
            safe = f'<span class="q">{safe}</span>'
        quoted = is_quote
        lines.append(safe)
    if collapse and quoted:
        lines[-1] += '</details>'
    return '<div dir="auto" style="white-space:pre-wrap;font-family:inherit">' + '\n'.join(lines) + '</div>'


def message_html(msg, images=False, collapse=False):
    """(the body as safe HTML, blocked pictures)."""
    part = msg.get_body(preferencelist=('html', 'plain'))
    if part is None:
        return '<p style="color:#888">(ההודעה ריקה)</p>', 0
    try:
        content = part.get_content()
    except Exception:
        content = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
    if part.get_content_type() == 'text/html':
        return clean_html(content, inline_images(msg), images, collapse)
    return text_to_html(content, collapse), 0


def csp(images, nonce=''):
    """nonce: only MailBrief's own few lines that report the page's height may run — still a null origin, so even they
    can't reach MailBrief; everything the email itself carries stays blocked."""
    scripts = f" allow-scripts; script-src 'nonce-{nonce}'" if nonce else ''
    return (f"sandbox allow-popups allow-popups-to-escape-sandbox{scripts}; default-src 'none'; style-src 'unsafe-inline'; "
            f"img-src data:{' https: http:' if images else ''}; font-src data:{' https:' if images else ''}; form-action 'none'")


FRAME_STYLE = ('<style>html{background:#fff;color:#1d1a24;color-scheme:light}body{margin:0;padding:18px 20px;font:15px/1.55 Arial,'
               'Rubik,system-ui,sans-serif;overflow-wrap:anywhere}img{max-width:100%;height:auto}img[data-blocked]{display:none}'
               'table{max-width:100%}pre{white-space:pre-wrap}.q{color:#7a7385}blockquote{margin:8px 0;padding-inline-start:12px;'
               'border-inline-start:3px solid #ddd;color:#555}a{color:#7c3aed}'
               '.mb-q>summary{display:inline-block;list-style:none;cursor:pointer;background:#eee;color:#555;border-radius:8px;'
               'padding:0 9px;margin:6px 0;font-size:12px;letter-spacing:2px;white-space:normal}.mb-q>summary::-webkit-details-marker'
               '{display:none}.mb-q[open]>summary{background:#e3dcf7}</style>')


# The reading pane grows the frame to the whole email (one scroll for the pane, nothing cut off): the height goes up by
# postMessage — a number and nothing else. The email's own CSS can't pin the page to the frame's height.
FIT_STYLE = '<style>html,body{height:auto!important;min-height:0!important;max-height:none!important;overflow-y:visible!important}</style>'
FIT_SCRIPT = ('(function(){var last=0;function send(){var b=document.body,d=document.documentElement;if(!b)return;'
              'var h=Math.ceil(Math.max(b.scrollHeight,b.getBoundingClientRect().height))+(d.scrollWidth>d.clientWidth?18:0);'
              'if(h!==last){last=h;parent.postMessage({mbHeight:h},"*");}}'
              'addEventListener("load",send);addEventListener("resize",send);document.addEventListener("toggle",send,true);'
              'if(window.ResizeObserver)new ResizeObserver(send).observe(document.body);send();})();')


def frame_document(body_html, nonce=''):
    fit = f'{FIT_STYLE}' if nonce else ''
    script = f'<script nonce="{nonce}">{FIT_SCRIPT}</script>' if nonce else ''
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
            f'<base target="_blank">{FRAME_STYLE}</head><body dir="auto">{body_html}{fit}{script}</body></html>')
