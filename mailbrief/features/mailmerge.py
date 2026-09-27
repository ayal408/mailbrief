"""📨 One email to many people, each with their own name: recipients from the address book or from an Excel / CSV file
(a column of addresses, and a column of names if there is one). Everything goes through the scheduled outbox — in small
rounds, never on Shabbat / Yom Tov."""
import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET

from mailbrief.features import outbox
from mailbrief.features.greetings import first_name


MAX_RECIPIENTS = 300
NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
EMAIL_HEAD = re.compile(r'^(e-?mail|מייל|אימייל|דוא"?ל|דוא״ל|כתובת)', re.I)
NAME_HEAD = re.compile(r'^(name|full name|שם|שם מלא|לקוח|איש קשר)', re.I)


def _col_index(ref):
    n = 0
    for ch in re.match(r'[A-Z]+', ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(data):
    """The first sheet of an .xlsx as rows of text (no Excel needed)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('x:si', NS):
                shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % NS['x'])))
        sheets = sorted(n for n in z.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', n))
        root = ET.fromstring(z.read(sheets[0]))
    rows = []
    for row in root.iter('{%s}row' % NS['x']):
        cells = {}
        for c in row.findall('x:c', NS):
            v = c.find('x:v', NS)
            if c.get('t') == 'inlineStr':
                text = ''.join(t.text or '' for t in c.iter('{%s}t' % NS['x']))
            elif v is None:
                continue
            else:
                text = shared[int(v.text)] if c.get('t') == 's' else v.text or ''
            cells[_col_index(c.get('r', 'A1'))] = text.strip()
        if cells:
            rows.append([cells.get(i, '') for i in range(max(cells) + 1)])
    return rows


def read_table(name, data):
    if name.lower().endswith(('.xlsx', '.xlsm')):
        return read_xlsx(data)
    text = next(data.decode(enc) for enc in ('utf-8-sig', 'cp1255', 'latin-1') if _decodes(data, enc))
    return [row for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]


def _decodes(data, enc):
    try:
        data.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def recipients_from_table(rows):
    """[(email, name)] — the address column is found by its header or by its content; the name column by its header,
    else the first column that isn't the address."""
    if not rows:
        return []
    head = rows[0]
    email_col = next((i for i, h in enumerate(head) if EMAIL_HEAD.match(h or '')), None)
    name_col = next((i for i, h in enumerate(head) if NAME_HEAD.match(h or '')), None)
    body = rows[1:] if email_col is not None or name_col is not None else rows
    if email_col is None:
        counts = {}
        for row in body:
            for i, c in enumerate(row):
                if outbox.EMAIL.fullmatch((c or '').strip()):
                    counts[i] = counts.get(i, 0) + 1
        email_col = max(counts, key=counts.get) if counts else None
    if email_col is None:
        return []
    if name_col is None:
        name_col = next((i for i in range(len(head)) if i != email_col), None)
    out, seen = [], set()
    for row in body:
        address = (row[email_col] if email_col < len(row) else '').strip()
        if outbox.EMAIL.fullmatch(address) and address.lower() not in seen:
            seen.add(address.lower())
            out.append((address, (row[name_col] if name_col is not None and name_col < len(row) else '').strip()))
    return out


def fill(text, address, name):
    first = first_name(name) if name else ''
    return (text.replace('{שם_פרטי}', first or name or '').replace('{first_name}', first or name or '')
            .replace('{שם}', name or '').replace('{name}', name or '').replace('{מייל}', address))


def send_merge(account, recipients, subject, body, when, files=()):
    """Queues one personal copy per recipient. Returns how many were queued."""
    if not recipients:
        raise ValueError('אין נמענים')
    if len(recipients) > MAX_RECIPIENTS:
        raise ValueError(f'עד {MAX_RECIPIENTS} נמענים בפעם אחת')
    if not subject.strip():
        raise ValueError('צריך נושא')
    for address, name in recipients:
        outbox.schedule(account, address, fill(subject, address, name), fill(body, address, name), when, files=files)
    return len(recipients)
