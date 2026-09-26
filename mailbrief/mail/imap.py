"""IMAP: connecting, folders, fetching mail, and "did I reply?"."""
import base64
import datetime as dt
import email
import imaplib
import re
from email.policy import default as default_policy

from mailbrief import config
from mailbrief.net import TLS
from mailbrief.mail.oauth import access_token, PROVIDERS
from mailbrief.storage import decrypt


def utf7(name: str) -> str:
    """IMAP modified UTF-7 (RFC 3501) for folder / label names."""
    out, buf = [], []

    def flush():
        if buf:
            b64 = base64.b64encode(''.join(buf).encode('utf-16-be')).decode().rstrip('=').replace('/', ',')
            out.append(f'&{b64}-')
            buf.clear()
    for ch in name:
        if 0x20 <= ord(ch) <= 0x7e:
            flush()
            out.append('&-' if ch == '&' else ch)
        else:
            buf.append(ch)
    flush()
    return ''.join(out)


def connect(acc):
    m = imaplib.IMAP4_SSL(acc['host'], int(acc.get('port', 993)), ssl_context=TLS, timeout=60)
    if acc.get('auth') in PROVIDERS:
        token = access_token(acc)
        m.authenticate('XOAUTH2', lambda _: f"user={acc['user']}\x01auth=Bearer {token}\x01\x01".encode())
    else:
        m.login(acc['user'], decrypt(acc['password']))
    return m


def is_gmail(acc):
    return acc['host'].lower() == 'imap.gmail.com'


def delimiter(m):
    typ, data = m.list('""', '""')
    if typ == 'OK' and data and data[0]:
        found = re.search(rb'\) "(.)"', data[0])
        if found:
            return found.group(1).decode()
    return '/'


def special_folder(m, flag):
    """Find a folder by its special-use flag (\\Sent, \\All) — names are localized, e.g. Hebrew Gmail."""
    typ, data = m.list()
    for line in data or []:
        if isinstance(line, bytes) and flag.encode() in line:
            found = re.search(rb'"([^"]*)"\s*$', line) or re.search(rb' (\S+)$', line)
            if found:
                return found.group(1).decode()
    return None


def fetch_recent(m, gmail, days=config.DAYS, readonly=False, folder='INBOX', gmail_raw=None, limit=config.MAX_MESSAGES,
                 headers_only=False):
    m.select(f'"{folder}"', readonly=readonly)
    since = (dt.date.today() - dt.timedelta(days=days)).strftime('%d-%b-%Y')
    if gmail and gmail_raw:
        m.literal = gmail_raw.encode('utf-8')
        typ, data = m.uid('SEARCH', 'CHARSET', 'UTF-8', 'SINCE', since, 'X-GM-RAW')
    else:
        typ, data = m.uid('SEARCH', None, 'SINCE', since)
    uids = data[0].split()[-limit:] if typ == 'OK' and data[0] else []
    part = 'BODY.PEEK[HEADER]' if headers_only else 'BODY.PEEK[]'
    what = f'(X-GM-MSGID {part})' if gmail else f'({part})'
    for i in range(0, len(uids), 25):
        typ, rows = m.uid('FETCH', b','.join(uids[i:i + 25]), what)
        for row in rows or []:
            if not isinstance(row, tuple):
                continue
            meta = row[0].decode(errors='replace')
            uid = re.search(r'UID (\d+)', meta)
            gid = re.search(r'X-GM-MSGID (\d+)', meta)
            yield (uid.group(1) if uid else None,
                   int(gid.group(1)) if gid else None,
                   email.message_from_bytes(row[1], policy=default_policy))


def mark_unanswered(m, items):
    """For mail from people: did the owner reply? Looks in the Sent folder for In-Reply-To / References."""
    people = [i for i in items if 'people' in i['cats'] and i.get('message_id')]
    sent = special_folder(m, r'\Sent') if people else None
    if not sent:
        return
    m.select(f'"{sent}"', readonly=True)
    now = dt.datetime.now().astimezone()
    for it in people:
        mid = it['message_id'].replace('"', '')
        typ, data = m.uid('SEARCH', None, 'OR', 'HEADER', 'In-Reply-To', f'"{mid}"', 'HEADER', 'References', f'"{mid}"')
        it['answered'] = bool(typ == 'OK' and data and data[0].strip())
        it['waiting_days'] = 0 if it['answered'] else (now - dt.datetime.fromisoformat(it['iso'])).days


def fetch_uids(m, uids, gmail):
    what = '(X-GM-MSGID BODY.PEEK[])' if gmail else '(BODY.PEEK[])'
    for i in range(0, len(uids), 25):
        typ, rows = m.uid('FETCH', b','.join(uids[i:i + 25]), what)
        for row in rows or []:
            if isinstance(row, tuple):
                meta = row[0].decode(errors='replace')
                uid, gid = re.search(r'UID (\d+)', meta), re.search(r'X-GM-MSGID (\d+)', meta)
                yield (uid.group(1) if uid else None, int(gid.group(1)) if gid else None,
                       email.message_from_bytes(row[1], policy=default_policy))
