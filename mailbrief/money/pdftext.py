"""Text out of a PDF receipt — standard library only, no AI: inflate the content streams, read the text operators,
and map glyph codes back to letters with the PDF's own ToUnicode tables (that is how ₪ and Hebrew come out right).
Enough to find the total of the usual invoice PDFs; scanned (image-only) PDFs have no text to find."""
import re
import zlib

from mailbrief.mail.classify import CURRENCY


OBJ = re.compile(rb'(\d+)\s+\d+\s+obj(.*?)endobj', re.S)
STREAM = re.compile(rb'stream\r?\n(.*?)\r?\nendstream', re.S)
NUMBER = r'(?<![\d.,/-])\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?(?![\d/-])'   # never the tail of a date or a longer number
TOTAL = re.compile(                    # Hebrew PDFs often store the line visually: the currency may come first, even "ח"ש"
    rf'(?P<c1>₪|ש"ח|ש״ח|ח"ש|ח״ש|ILS|NIS|\$|USD|€|EUR)\s?(?P<a1>{NUMBER})'
    rf'|(?P<a2>{NUMBER})\s?(?P<c2>₪|ש"ח|ש״ח|ח"ש|ח״ש|ILS|NIS|USD|EUR|€)')
CURRENCY_ALSO = {'ח"ש': '₪', 'ח״ש': '₪'}


def _streams(data):
    for _, body in OBJ.findall(data):
        found = STREAM.search(body)
        if not found:
            continue
        raw, head = found.group(1), body[:found.start()]
        if b'/FlateDecode' in head:
            try:
                raw = zlib.decompressobj().decompress(raw)
            except zlib.error:
                continue
        elif b'/Filter' in head:
            continue                                   # images and other encodings carry no text for us
        yield raw


def _hex(s):
    return bytes.fromhex(s.decode('latin-1')) if len(s) % 2 == 0 else bytes.fromhex(s.decode('latin-1') + '0')


def _cmap(stream, table):
    """ToUnicode: bfchar <code> <unicode> and bfrange <lo> <hi> <unicode> (or [..]) entries."""
    for block in re.findall(rb'beginbfchar(.*?)endbfchar', stream, re.S):
        for code, uni in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', block):
            table[_hex(code)] = _hex(uni).decode('utf-16-be', 'ignore')
    for block in re.findall(rb'beginbfrange(.*?)endbfrange', stream, re.S):
        for lo, hi, rest in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])', block):
            start, end, width = int(lo, 16), int(hi, 16), len(lo) // 2
            if end - start > 5000:
                continue
            targets = re.findall(rb'<([0-9A-Fa-f]+)>', rest)
            if rest.startswith(b'['):
                for i, uni in enumerate(targets):
                    table[(start + i).to_bytes(width, 'big')] = _hex(uni).decode('utf-16-be', 'ignore')
            else:
                base = int(targets[0], 16)
                for i in range(end - start + 1):
                    try:
                        table[(start + i).to_bytes(width, 'big')] = chr(base + i)
                    except (ValueError, OverflowError):
                        break


def _literal(s):
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):             # backslash escapes
            n = s[i + 1]
            simple = {ord('n'): 10, ord('r'): 13, ord('t'): 9, ord('b'): 8, ord('f'): 12}
            if n in simple:
                out.append(simple[n]); i += 2
            elif 0x30 <= n <= 0x37:
                digits = re.match(rb'[0-7]{1,3}', s[i + 1:i + 4]).group(0)
                out.append(int(digits, 8) & 0xFF); i += 1 + len(digits)
            elif n in (10, 13):
                i += 2
            else:
                out.append(n); i += 2
        else:
            out.append(c); i += 1
    return bytes(out)


def _decode(code, table, widths):
    if not table:
        return code.decode('latin-1')
    out, i = [], 0
    while i < len(code):
        for w in widths:
            piece = code[i:i + w]
            if piece in table:
                out.append(table[piece]); i += w
                break
        else:
            out.append(chr(code[i]) if 32 <= code[i] < 127 else ''); i += 1
    return ''.join(out)


TOKENS = re.compile(rb'\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>|-?\d*\.?\d+|\bT[JjdDm*]\b|\'|"', re.S)


def pdf_text(data):
    """All the text a PDF shows, roughly in reading order (one line per text block)."""
    if not data.startswith(b'%PDF'):
        return ''
    table, contents = {}, []
    for stream in _streams(data):
        if b'begincmap' in stream:
            _cmap(stream, table)
        elif b'BT' in stream:
            contents.append(stream)
    widths = sorted({len(k) for k in table}, reverse=True) or [1]
    lines, current, numbers, y = [], [], [], None

    def new_line():
        if current:
            lines.append(''.join(current))
            current.clear()
    for stream in contents:
        for token in TOKENS.findall(stream):
            if token.startswith(b'('):
                current.append(_decode(_literal(token[1:-1]), table, widths))
            elif token.startswith(b'<'):
                current.append(_decode(_hex(re.sub(rb'\s', b'', token[1:-1])), table, widths))
            elif token[:1].isdigit() or token[:1] in b'-.':
                numbers = (numbers + [float(token)])[-6:]
                continue
            elif token in (b'Td', b'TD'):
                # many PDFs (Chrome, Word) place every letter with its own small move: only a vertical move is a new line
                if len(numbers) >= 2 and abs(numbers[-1]) > 0.01:
                    new_line()
            elif token == b'Tm':
                if len(numbers) >= 6:
                    if y is not None and abs(numbers[-1] - y) > 0.5:
                        new_line()
                    y = numbers[-1]
            elif token in (b'T*', b"'", b'"'):
                new_line()
            numbers = []
    new_line()
    return '\n'.join(line.strip() for line in lines if line.strip())


def total_from_pdf(data):
    """'₪1,250.00' — the largest amount with a currency (an invoice's total is its largest line), or ''."""
    try:
        text = pdf_text(data)
    except Exception:
        return ''
    best = None
    for found in TOTAL.finditer(text):
        number = found.group('a1') or found.group('a2')
        currency = found.group('c1') or found.group('c2')
        value = float(number.replace(',', ''))
        if best is None or value > best[0]:
            best = (value, number, CURRENCY_ALSO.get(currency) or CURRENCY.get(currency, currency))
    return f'{best[2]}{best[1]}' if best else ''


def amount_from_attachments(msg):
    for part in msg.iter_attachments():
        name = (part.get_filename() or '').lower()
        if part.get_content_type() == 'application/pdf' or name.endswith('.pdf'):
            data = part.get_payload(decode=True) or b''
            if len(data) < 15_000_000:
                amount = total_from_pdf(data)
                if amount:
                    return amount
    return ''
