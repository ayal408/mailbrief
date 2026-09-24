"""Every attachment from the last month, in one list: filter by type (PDF, images, Excel, Word) and by who sent it,
download one email's files in a click. Reads only the mail's structure (file names) — nothing is downloaded until asked."""
import datetime as dt
import email
import email.utils
import os
import re
from email.policy import default as default_policy
from urllib.parse import quote

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.imap import is_gmail, special_folder
from mailbrief.mail.message import decode
from mailbrief.storage import load_json, save_json
from mailbrief.util import safe_name, write_once


KINDS = {'pdf': ('📄', 'PDF', ('pdf',)), 'image': ('🖼️', 'תמונות', ('jpg', 'jpeg', 'png', 'gif', 'heic', 'webp', 'tif', 'tiff', 'bmp')),
         'excel': ('📊', 'Excel', ('xls', 'xlsx', 'xlsm', 'csv', 'ods')), 'word': ('📝', 'Word', ('doc', 'docx', 'odt', 'rtf')),
         'slides': ('📽️', 'מצגות', ('ppt', 'pptx', 'key', 'odp')), 'archive': ('🗜️', 'ארכיונים', ('zip', 'rar', '7z'))}
NOISE = re.compile(r'^(image\d{3}|outlook|signature|logo)[\w-]*\.(png|jpe?g|gif)$|\.ics$|\.vcf$|^noname', re.I)
NAME = re.compile(rb'"(?:name|filename)\*?" "((?:[^"\\]|\\.)*)"', re.I)
MAX_MESSAGES = 300


def kind_of(name):
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return next((k for k, (_, _, exts) in KINDS.items() if ext in exts), 'other')


def _names(structure):
    out = []
    for raw in NAME.findall(structure):
        name = decode(raw.decode('utf-8', 'replace').replace('\\"', '"'))
        if "''" in name:                                        # RFC 2231: utf-8''%D7%A7...
            from urllib.parse import unquote
            name = unquote(name.split("''", 1)[1])
        name = re.sub(r'\s+(\.[A-Za-z0-9]{1,5})$', r'\1', name)          # "=?..?=.pdf" decodes with a space before the extension
        if name and not NOISE.search(name) and name not in out:
            out.append(name)
    return out


def scan_files(days=30):
    """Refreshes the list (cache) and returns (rows, errors). rows: newest first."""
    accounts, rows, errors = load_json(config.ACCOUNTS_FILE, []), [], []
    since = (dt.date.today() - dt.timedelta(days=days)).strftime('%d-%b-%Y')
    for acc in accounts:
        try:
            m = imap.connect(acc)
        except Exception as exc:
            errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
            continue
        try:
            gmail = is_gmail(acc)
            folder = special_folder(m, r'\All') if gmail else None
            m.select(f'"{folder}"' if folder else 'INBOX', readonly=True)
            if gmail:
                m.literal = f'has:attachment newer_than:{days}d'.encode()
                typ, data = m.uid('SEARCH', 'CHARSET', 'UTF-8', 'X-GM-RAW')
            else:
                typ, data = m.uid('SEARCH', None, 'SINCE', since)
            uids = data[0].split()[-MAX_MESSAGES:] if typ == 'OK' and data and data[0] else []
            found = {}
            for i in range(0, len(uids), 100):
                typ, parts = m.uid('FETCH', b','.join(uids[i:i + 100]), '(BODYSTRUCTURE)')
                for part in parts or []:
                    raw = part[0] if isinstance(part, tuple) else part
                    uid = re.search(rb'UID (\d+)', raw or b'')
                    names = _names(raw or b'')
                    if uid and names:
                        found[uid.group(1)] = names
            keys = list(found)
            for i in range(0, len(keys), 50):
                what = '(X-GM-MSGID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])' if gmail else \
                       '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])'
                typ, parts = m.uid('FETCH', b','.join(keys[i:i + 50]), what)
                for part in parts or []:
                    if not isinstance(part, tuple):
                        continue
                    uid = re.search(rb'UID (\d+)', part[0])
                    gid = re.search(rb'X-GM-MSGID (\d+)', part[0])
                    head = email.message_from_bytes(part[1], policy=default_policy)
                    try:
                        when = email.utils.parsedate_to_datetime(head['Date']).astimezone().isoformat(timespec='minutes')
                    except Exception:
                        when = ''
                    sender = email.utils.parseaddr(str(head.get('From', '')))
                    for name in found.get(uid.group(1) if uid else b'', []):
                        rows.append({'account': acc['email'], 'from': decode(sender[0]) or sender[1], 'sender': sender[1].lower(),
                                     'subject': decode(head.get('Subject')) or '', 'date': when, 'name': name, 'kind': kind_of(name),
                                     'message_id': (head.get('Message-ID') or '').strip(),
                                     'link': f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{int(gid.group(1)):x}" if gid else ''})
        except Exception as exc:
            errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
        finally:
            try:
                m.logout()
            except Exception:
                pass
    save_json(config.ACCOUNTS_FILE, accounts)
    rows.sort(key=lambda r: r['date'], reverse=True)
    cache = load_json(config.CACHE_FILE, {})
    cache['files'] = {'at': dt.datetime.now().strftime('%d/%m %H:%M'), 'days': days, 'rows': rows}
    save_json(config.CACHE_FILE, cache)
    return rows, errors


def cached_files():
    return load_json(config.CACHE_FILE, {}).get('files') or {}


def save_message_files(account, message_id):
    """Downloads one email's attachments into הורדות\\<date> <sender>\\ — returns the folder."""
    from mailbrief.features.replies import _original
    accounts = load_json(config.ACCOUNTS_FILE, [])
    acc = next((a for a in accounts if a['email'] == account), None)
    if not acc or not message_id:
        raise RuntimeError('ההודעה לא נמצאה')
    m = imap.connect(acc)
    try:
        msg = _original(m, message_id)
    finally:
        m.logout()
    save_json(config.ACCOUNTS_FILE, accounts)
    sender = email.utils.parseaddr(str(msg.get('From', '')))
    folder = os.path.join(config.DOWNLOADS_DIR, safe_name(f"{dt.date.today():%Y-%m-%d} {decode(sender[0]) or sender[1]}")[:80])
    count = 0
    for part in msg.iter_attachments():
        name = decode(part.get_filename()) or 'file'
        data = part.get_payload(decode=True) or b''
        if data:
            write_once(folder, safe_name(name), data)
            count += 1
    if not count:
        raise RuntimeError('לא נמצאו קבצים מצורפים')
    return folder
