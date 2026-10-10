"""📥 The mailbox inside MailBrief: folders, the message list, reading a message, and the actions on it (read / star /
archive / delete / move / spam / draft) — straight over IMAP, one kept-open connection per mailbox.
A local cache (data/mailbox.db) keeps the list and the messages already read, so the inbox opens at once and still
shows the last known mail when the internet is down."""
import base64
import contextlib
import datetime as dt
import email
import imaplib
import json
import os
import quopri
import re
import sqlite3
import threading
import time
import zlib
from email.policy import default as default_policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.mail.message import decode
from mailbrief.storage import load_json


PER_PAGE = 50
ROLES = {'\\Inbox': 'inbox', '\\Sent': 'sent', '\\Drafts': 'drafts', '\\Trash': 'trash', '\\Junk': 'junk',
         '\\All': 'all', '\\Flagged': 'flagged', '\\Important': 'important', '\\Archive': 'archive'}
ROLE_NAMES = {'inbox': 'דואר נכנס', 'flagged': 'מסומן בכוכב', 'important': 'חשוב', 'sent': 'נשלח', 'drafts': 'טיוטות',
              'all': 'כל הדואר', 'archive': 'ארכיון', 'junk': 'ספאם', 'trash': 'אשפה'}
ROLE_ICONS = {'inbox': '📥', 'flagged': '⭐', 'important': '❗', 'sent': '📤', 'drafts': '📝', 'all': '🗂️', 'archive': '🗄️',
              'junk': '🚫', 'trash': '🗑️'}
ROLE_ORDER = list(ROLE_NAMES)
NAME_ROLES = {'sent': 'sent', 'sent items': 'sent', 'sent messages': 'sent', 'פריטים שנשלחו': 'sent', 'drafts': 'drafts',
              'טיוטות': 'drafts', 'trash': 'trash', 'deleted items': 'trash', 'deleted messages': 'trash', 'פריטים שנמחקו': 'trash',
              'junk': 'junk', 'spam': 'junk', 'junk email': 'junk', 'דואר זבל': 'junk', 'archive': 'archive', 'ארכיון': 'archive'}
HEADERS = 'FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES CONTENT-TYPE CONTENT-TRANSFER-ENCODING LIST-UNSUBSCRIBE'


# ---- folder names (IMAP modified UTF-7) --------------------------------------------------------------------------------

def utf7_decode(name: str) -> str:
    def part(match):
        chunk = match.group(1)
        if not chunk:
            return '&'
        b64 = chunk.replace(',', '/')
        return base64.b64decode(b64 + '=' * (-len(b64) % 4)).decode('utf-16-be', 'replace')
    return re.sub(r'&([^-]*)-', part, name)


def quoted(folder):
    return '"' + folder.replace('\\', '\\\\').replace('"', '\\"') + '"'


def astring(value):
    """A search value as an IMAP quoted string (a Message-ID may hold " % ] or spaces, which would break the command)."""
    return quoted(re.sub(r'[\r\n]', '', value))


def _parse_list(data):
    """LIST answers -> [(flags, delimiter, raw name)] — names may be quoted, bare or sent as a literal."""
    out, rows = [], list(data or [])
    for row in rows:
        if row is None:
            continue
        if isinstance(row, tuple):                       # the name came as a literal: (b'(\\flags) "/" {12}', b'name')
            head, name = row[0].decode('utf-8', 'replace'), row[1].decode('utf-8', 'replace')
            found = re.match(r'\((?P<f>[^)]*)\) (?P<d>"(?:\\.|[^"])*"|NIL)', head)
        else:
            line = row.decode('utf-8', 'replace')
            found = re.match(r'\((?P<f>[^)]*)\) (?P<d>"(?:\\.|[^"])*"|NIL) (?P<n>.+)$', line)
            if not found:
                continue
            name = found.group('n').strip()
            if name.startswith('"'):
                name = re.sub(r'\\(.)', r'\1', name[1:-1])
        if not found:
            continue
        sep = found.group('d')
        out.append((found.group('f').split(), '' if sep == 'NIL' else re.sub(r'\\(.)', r'\1', sep[1:-1]), name))
    return out


# ---- connections -------------------------------------------------------------------------------------------------------

_POOL, _LOCKS, _GUARD = {}, {}, threading.Lock()


def accounts():
    return load_json(config.ACCOUNTS_FILE, [])


def account(address):
    acc = next((a for a in accounts() if a['email'].lower() == (address or '').lower()), None)
    if not acc:
        raise LookupError('התיבה לא מחוברת')
    return acc


@contextlib.contextmanager
def session(acc, folder=None, readonly=False):
    """One IMAP connection per mailbox, kept open between clicks (a fresh one costs a second or two)."""
    with _GUARD:
        lock = _LOCKS.setdefault(acc['id'], threading.Lock())
    with lock:
        conn, used = _POOL.get(acc['id'], (None, 0))
        if conn and time.monotonic() - used > 60:        # quiet for a while: make sure it is still alive
            try:
                conn.noop()
            except Exception:
                conn = None
        if not conn:
            conn = imap.connect(acc)
        try:
            if folder:
                typ, data = conn.select(quoted(folder), readonly=readonly)
                if typ != 'OK':
                    raise RuntimeError('התיקייה לא נמצאה בתיבה')
            yield conn
            _POOL[acc['id']] = (conn, time.monotonic())
        except (imaplib.IMAP4.abort, OSError):
            _POOL.pop(acc['id'], None)
            raise


def drop(acc_id):
    """Close the kept connection — only when no request is using it (otherwise it is simply left for that request)."""
    with _GUARD:
        lock = _LOCKS.setdefault(acc_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return
    try:
        conn = _POOL.pop(acc_id, (None, 0))[0]
    finally:
        lock.release()
    if conn:
        with contextlib.suppress(Exception):
            conn.logout()


# ---- the local cache -----------------------------------------------------------------------------------------------------

_DB_LOCK = threading.Lock()
MAX_BODIES = 600


def _db():
    os.makedirs(config.DATA, exist_ok=True)
    db = sqlite3.connect(os.path.join(config.DATA, 'mailbox.db'), timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS heads (acc TEXT, folder TEXT, uid INTEGER, validity INTEGER, at TEXT, data TEXT, '
               'PRIMARY KEY (acc, folder, uid))')
    db.execute('CREATE TABLE IF NOT EXISTS bodies (acc TEXT, folder TEXT, uid INTEGER, validity INTEGER, raw BLOB, seen REAL, '
               'PRIMARY KEY (acc, folder, uid))')
    db.execute('CREATE TABLE IF NOT EXISTS folders (acc TEXT PRIMARY KEY, data TEXT)')
    return db


def _cache_heads(acc, folder, validity, rows, replace_from=None):
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        db.execute('DELETE FROM heads WHERE acc=? AND folder=? AND validity<>?', (acc, folder, validity))
        if replace_from is not None:                     # the newest page: whatever vanished from it was moved / deleted
            db.execute('DELETE FROM heads WHERE acc=? AND folder=? AND uid>=?', (acc, folder, replace_from))
        db.executemany('INSERT OR REPLACE INTO heads VALUES (?,?,?,?,?,?)',
                       [(acc, folder, r['uid'], validity, r['at'], json.dumps(r, ensure_ascii=False)) for r in rows])


def cached_list(acc, folder, page=0):
    with _DB_LOCK, contextlib.closing(_db()) as db:
        rows = db.execute('SELECT data FROM heads WHERE acc=? AND folder=? ORDER BY uid DESC LIMIT ? OFFSET ?',
                          (acc, folder, PER_PAGE, page * PER_PAGE)).fetchall()
    return [json.loads(r[0]) for r in rows]


def _forget(acc, folder, uids):
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        db.executemany('DELETE FROM heads WHERE acc=? AND folder=? AND uid=?', [(acc, folder, int(u)) for u in uids])
        db.executemany('DELETE FROM bodies WHERE acc=? AND folder=? AND uid=?', [(acc, folder, int(u)) for u in uids])


def _set_cached_flags(acc, folder, uids, flag, on):
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        for uid in uids:
            row = db.execute('SELECT data FROM heads WHERE acc=? AND folder=? AND uid=?', (acc, folder, int(uid))).fetchone()
            if row:
                data = json.loads(row[0])
                flags = set(data.get('flags', []))
                flags.add(flag) if on else flags.discard(flag)
                data['flags'] = sorted(flags)
                db.execute('UPDATE heads SET data=? WHERE acc=? AND folder=? AND uid=?',
                           (json.dumps(data, ensure_ascii=False), acc, folder, int(uid)))


def _cached_body(acc, folder, uid):
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        row = db.execute('SELECT raw FROM bodies WHERE acc=? AND folder=? AND uid=?', (acc, folder, int(uid))).fetchone()
        if row:
            db.execute('UPDATE bodies SET seen=? WHERE acc=? AND folder=? AND uid=?', (time.time(), acc, folder, int(uid)))
    return zlib.decompress(row[0]) if row else None


def _keep_body(acc, folder, uid, validity, raw):
    if len(raw) > 15_000_000:                            # huge attachments: read from the server each time
        return
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        db.execute('INSERT OR REPLACE INTO bodies VALUES (?,?,?,?,?,?)', (acc, folder, int(uid), validity, zlib.compress(raw, 6), time.time()))
        db.execute('DELETE FROM bodies WHERE rowid NOT IN (SELECT rowid FROM bodies ORDER BY seen DESC LIMIT ?)', (MAX_BODIES,))


# ---- folders -------------------------------------------------------------------------------------------------------------

def _role(flags, name):
    for flag in flags:
        if flag in ROLES:
            return ROLES[flag]
    if name.upper() == 'INBOX':
        return 'inbox'
    return NAME_ROLES.get(utf7_decode(name).rsplit('/', 1)[-1].lower())


def folders(address, fresh=True):
    """[{id, name, role, icon, unread, depth}] — the special folders first (in the usual order), then the user's own."""
    if not fresh:
        with _DB_LOCK, contextlib.closing(_db()) as db:
            row = db.execute('SELECT data FROM folders WHERE acc=?', (address.lower(),)).fetchone()
        if row:
            return json.loads(row[0])
    acc = account(address)
    out, seen_roles = [], set()
    with session(acc) as m:
        typ, data = m.list()
        for flags, sep, raw in _parse_list(data):
            if '\\Noselect' in flags or '\\NonExistent' in flags:
                continue
            role = _role(flags, raw)
            if role in seen_roles:
                role = None
            if role:
                seen_roles.add(role)
            parts = utf7_decode(raw).split(sep) if sep else [utf7_decode(raw)]
            if parts[0] == '[Gmail]' or parts[0] == '[Google Mail]':
                parts = parts[1:] or parts
            out.append({'id': raw, 'name': ROLE_NAMES.get(role) or parts[-1], 'path': '/'.join(parts), 'role': role or '',
                        'icon': ROLE_ICONS.get(role, '🏷️' if imap.is_gmail(acc) else '📁'), 'depth': len(parts) - 1, 'unread': 0})
        for f in out:
            if f['role'] in ('inbox', 'drafts', 'junk') or (not f['role'] and len(out) < 80):
                with contextlib.suppress(Exception):
                    typ, data = m.status(quoted(f['id']), '(UNSEEN)')
                    found = re.search(rb'UNSEEN (\d+)', data[0] or b'') if typ == 'OK' else None
                    f['unread'] = int(found.group(1)) if found else 0
    out.sort(key=lambda f: (ROLE_ORDER.index(f['role']) if f['role'] in ROLE_ORDER else 99, f['path'].lower()))
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        db.execute('INSERT OR REPLACE INTO folders VALUES (?,?)', (address.lower(), json.dumps(out, ensure_ascii=False)))
    return out


def folder_of(address, role):
    """The id of a special folder (sent / trash / junk / drafts / all / archive), or ''."""
    for fresh in (False, True):
        try:
            hit = next((f['id'] for f in folders(address, fresh=fresh) if f['role'] == role), '')
        except Exception:
            hit = ''
        if hit:
            return hit
    return ''


# ---- the message list ----------------------------------------------------------------------------------------------------

def _records(rows):
    """FETCH answers -> [(meta text, literal bytes)]; a FLAGS item may come after the literal, so it is joined to meta."""
    out = []
    for row in rows or []:
        if isinstance(row, tuple):
            out.append([row[0].decode('utf-8', 'replace'), row[1]])
        elif isinstance(row, bytes) and out:
            out[-1][0] += row.decode('utf-8', 'replace')
    return out


def _flags(meta):
    found = re.search(r'FLAGS \(([^)]*)\)', meta)
    return [f for f in (found.group(1).split() if found else []) if f.startswith('\\') or f.startswith('$')]


def _addr_list(value):
    return [{'name': decode(n).strip(' "'), 'email': a} for n, a in getaddresses([decode(value or '')]) if a]


def thread_key(msg_or_heads, gm_thread=None):
    if gm_thread:
        return f'g{gm_thread}'
    refs = re.findall(r'<[^>]+>', str(msg_or_heads.get('References') or ''))
    if refs:
        return refs[0]
    parent = re.findall(r'<[^>]+>', str(msg_or_heads.get('In-Reply-To') or ''))
    return parent[0] if parent else (str(msg_or_heads.get('Message-ID') or '').strip() or '')


def _iso(meta, heads):
    found = re.search(r'INTERNALDATE "([^"]+)"', meta)
    try:
        when = dt.datetime.strptime(found.group(1), '%d-%b-%Y %H:%M:%S %z') if found else parsedate_to_datetime(heads.get('Date'))
        return when.astimezone().isoformat(timespec='seconds')
    except Exception:
        return ''


def _decode_bytes(data, cte, charset):
    cte = (cte or '').lower()
    try:
        if cte == 'base64':
            clean = re.sub(rb'[^A-Za-z0-9+/]', b'', data)
            data = base64.b64decode(clean[:len(clean) - len(clean) % 4])
        elif cte == 'quoted-printable':
            data = quopri.decodestring(data)
    except Exception:
        return ''
    try:
        return data.decode(charset or 'utf-8', 'replace')
    except LookupError:
        return data.decode('utf-8', 'replace')


def snippet(heads_bytes, text_bytes):
    """The preview line, from the first few KB of the body (which may stop in the middle of a part)."""
    try:
        msg = email.message_from_bytes(heads_bytes + b'\r\n' + text_bytes, policy=default_policy)
        part = next((p for p in msg.walk() if p.get_content_type() == 'text/plain'), None) or \
            next((p for p in msg.walk() if p.get_content_type() == 'text/html'), None)
        if part is None:
            return ''
        raw = part.get_payload(decode=False)
        try:                                             # 8bit text comes back as str: the bytes again, to decode by charset
            raw = raw.encode('ascii', 'surrogateescape') if isinstance(raw, str) else (raw or b'')
        except UnicodeEncodeError:                       # ... unless the parser already decoded it
            pass
        text = raw if isinstance(raw, str) else _decode_bytes(raw, part.get('Content-Transfer-Encoding'), part.get_content_charset())
        if part.get_content_type() == 'text/html':
            import html as _html
            text = re.sub(r'(?is)<(script|style|head)\b.*?(</\1>|$)', ' ', text)
            text = _html.unescape(re.sub(r'<[^>]*>?', ' ', text))
        text = re.sub(r'(?m)^>.*$', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()[:180]
    except Exception:
        return ''


def _row(uid, meta, heads_bytes, gmail):
    heads = email.message_from_bytes(heads_bytes, policy=default_policy)
    thrid = re.search(r'X-GM-THRID (\d+)', meta)
    msgid = re.search(r'X-GM-MSGID (\d+)', meta)
    size = re.search(r'RFC822\.SIZE (\d+)', meta)
    labels = re.search(r'X-GM-LABELS \(([^)]*)\)', meta)
    ctype = str(heads.get('Content-Type') or '').lower()
    frm = (_addr_list(heads.get('From')) or [{'name': '', 'email': ''}])[0]
    return {'uid': int(uid), 'from': frm, 'to': _addr_list(heads.get('To')), 'cc': _addr_list(heads.get('Cc')),
            'subject': decode(heads.get('Subject')).strip(), 'at': _iso(meta, heads), 'flags': _flags(meta),
            'size': int(size.group(1)) if size else 0, 'message_id': str(heads.get('Message-ID') or '').strip(),
            'attach': bool(re.search(r'"attachment"', meta, re.I)) or ctype.startswith('multipart/mixed'),
            'thread': thread_key(heads, thrid.group(1) if thrid else None), 'gid': f'{int(msgid.group(1)):x}' if msgid else '',
            'labels': [utf7_decode(l.strip('"')) for l in re.findall(r'"(?:\\.|[^"])*"|\S+', labels.group(1))] if labels else [],
            'news': bool(heads.get('List-Unsubscribe')), 'snippet': '', '_heads': heads_bytes}


def _search(m, gmail, query, unread=False):
    crit = []
    if unread:
        crit.append('UNSEEN')
    if query and gmail:
        m.literal = query.encode('utf-8')
        typ, data = m.uid('SEARCH', 'CHARSET', 'UTF-8', *crit, 'X-GM-RAW')
    elif query:                                          # other servers: from: subject: has:attachment ... translated
        return _search_imap(m, query, unread)
    else:
        typ, data = m.uid('SEARCH', None, *(crit or ['ALL']))
    return sorted((int(u) for u in (data[0] or b'').split()), reverse=True) if typ == 'OK' and data else []


def _validity(m):
    found = m.response('UIDVALIDITY')[1]
    try:
        return int(found[0]) if found and found[0] else 0
    except (TypeError, ValueError):
        return 0


def list_messages(address, folder='INBOX', page=0, query='', unread=False):
    """One page of the folder, newest first: {'items': [...], 'total': n, 'offline': bool}."""
    acc = account(address)
    gmail = imap.is_gmail(acc)
    try:
        with session(acc, folder, readonly=True) as m:
            validity = _validity(m)
            uids = _search(m, gmail, query.strip(), unread)
            chosen = uids[page * PER_PAGE:(page + 1) * PER_PAGE]
            rows = []
            if chosen:
                ids = ','.join(map(str, chosen)).encode()
                extra = ' X-GM-THRID X-GM-MSGID X-GM-LABELS' if gmail else ''
                typ, data = m.uid('FETCH', ids, f'(UID FLAGS INTERNALDATE RFC822.SIZE BODYSTRUCTURE{extra} BODY.PEEK[HEADER.FIELDS ({HEADERS})])')
                for meta, lit in _records(data):
                    uid = re.search(r'UID (\d+)', meta)
                    if uid:
                        rows.append(_row(uid.group(1), meta, lit, gmail))
                typ, data = m.uid('FETCH', ids, '(UID BODY.PEEK[TEXT]<0.3072>)')
                texts = {}
                for meta, lit in _records(data):
                    uid = re.search(r'UID (\d+)', meta)
                    if uid:
                        texts[int(uid.group(1))] = lit
                for r in rows:
                    r['snippet'] = snippet(r['_heads'], texts.get(r['uid'], b''))
            for r in rows:
                r.pop('_heads', None)
            rows.sort(key=lambda r: -r['uid'])
        if not query and not unread:
            _cache_heads(address.lower(), folder, validity, rows, replace_from=rows[-1]['uid'] if page == 0 and rows else None)
            if page == 0 and folder == 'INBOX':
                prefetch(address, folder, rows)          # 📴 the newest messages also open with no internet
        return {'items': rows, 'total': len(uids), 'offline': False}
    except Exception as exc:                             # no internet / the server is down: the last known list
        rows = [] if query or unread else cached_list(address.lower(), folder, page)
        if not rows:
            raise
        return {'items': rows, 'total': len(rows), 'offline': True, 'error': str(exc)}


def unified(addresses, page=0, query='', unread=False):
    """📬 All the inboxes as one list, newest first."""
    items, errors, offline = [], [], False
    for address in addresses:
        try:
            got = list_messages(address, 'INBOX', 0, query, unread) if page == 0 else \
                {'items': sum((list_messages(address, 'INBOX', p, query, unread)['items'] for p in range(page + 1)), []), 'offline': False}
        except Exception as exc:
            errors.append(f'{address}: {exc}')
            continue
        offline |= got.get('offline', False)
        for r in got['items']:
            r['account'] = address
            items.append(r)
    items.sort(key=lambda r: r['at'], reverse=True)
    return {'items': items[page * PER_PAGE:(page + 1) * PER_PAGE], 'total': len(items), 'offline': offline, 'errors': errors}


# ---- one message ---------------------------------------------------------------------------------------------------------

def fetch_raw(address, folder, uid, mark_seen=True):
    """The whole message (bytes); from the cache when it was opened before. Opening it marks it read on the server."""
    acc = account(address)
    raw = _cached_body(address.lower(), folder, uid)
    if raw is not None:
        if mark_seen:
            with contextlib.suppress(Exception):
                set_flag(address, folder, [uid], '\\Seen', True)
        return raw
    with session(acc, folder, readonly=not mark_seen) as m:
        validity = _validity(m)
        typ, data = m.uid('FETCH', str(uid).encode(), '(UID BODY[])' if mark_seen else '(UID BODY.PEEK[])')
        recs = _records(data)
        if typ != 'OK' or not recs:
            raise LookupError('ההודעה כבר לא נמצאת בתיקייה (אולי הועברה או נמחקה)')
        raw = recs[0][1]
    _keep_body(address.lower(), folder, uid, validity, raw)
    if mark_seen:
        _set_cached_flags(address.lower(), folder, [uid], '\\Seen', True)
    return raw


def parse(raw):
    return email.message_from_bytes(raw, policy=default_policy)


def attachments(msg):
    """[(index, name, content type, size, part)] — files the sender attached (not the inline pictures of the body)."""
    out = []
    for n, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        disp = part.get_content_disposition()
        name = decode(part.get_filename())
        if disp == 'attachment' or (name and disp != 'inline') or (disp == 'inline' and name and not part.get('Content-ID')):
            data = part.get_payload(decode=True) or b''
            out.append((n, name or f'קובץ-{n}', part.get_content_type(), len(data), part))
    return out


def part_at(msg, index):
    for n, part in enumerate(msg.walk()):
        if n == index and not part.is_multipart():
            return part
    raise LookupError('הקובץ לא נמצא בהודעה')


def thread_messages(address, folder, row_thread, uid, message_id=''):
    """The other messages of the same conversation: on Gmail from "All Mail" (so your replies show too), elsewhere from
    this folder and Sent. [{folder, uid, from, at, subject, snippet}] oldest first, without the open message itself."""
    acc = account(address)
    found = []
    try:
        if row_thread.startswith('g') and imap.is_gmail(acc):
            where = folder_of(address, 'all') or folder
            with session(acc, where, readonly=True) as m:
                typ, data = m.uid('SEARCH', None, 'X-GM-THRID', row_thread[1:])
                uids = sorted(int(u) for u in (data[0] or b'').split())[-30:] if typ == 'OK' else []
                found += _thread_heads(m, where, uids, True)
        elif row_thread and row_thread.isascii():
            places = [folder] + [f for f in (folder_of(address, 'sent'),) if f and f != folder]
            for where in places:
                with session(acc, where, readonly=True) as m:
                    uids = set()
                    for header in ('Message-ID', 'References', 'In-Reply-To'):
                        typ, data = m.uid('SEARCH', None, 'HEADER', header, astring(row_thread))
                        if typ == 'OK':
                            uids |= {int(u) for u in (data[0] or b'').split()}
                    found += _thread_heads(m, where, sorted(uids)[-30:], False)
    except Exception:
        return []
    mine = [r for r in found if not (r['folder'] == folder and r['uid'] == int(uid))
            and not (message_id and r['message_id'] == message_id)]       # Gmail: its own copy in All Mail
    seen, out = set(), []
    for r in sorted(mine, key=lambda r: r['at']):
        key = r['message_id'] or f"{r['folder']}{r['uid']}"
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _thread_heads(m, where, uids, gmail):
    if not uids:
        return []
    rows = []
    typ, data = m.uid('FETCH', ','.join(map(str, uids)).encode(), f'(UID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS ({HEADERS})])')
    for meta, lit in _records(data):
        uid = re.search(r'UID (\d+)', meta)
        if uid:
            r = _row(uid.group(1), meta, lit, gmail)
            r.pop('_heads', None)
            r['folder'] = where
            rows.append(r)
    return rows


# ---- actions -------------------------------------------------------------------------------------------------------------

def _uidset(uids):
    clean = [str(int(u)) for u in uids]
    if not clean:
        raise ValueError('לא נבחרו הודעות')
    return ','.join(clean).encode()


def set_flag(address, folder, uids, flag, on):
    acc = account(address)
    with session(acc, folder) as m:
        typ, _ = m.uid('STORE', _uidset(uids), '+FLAGS.SILENT' if on else '-FLAGS.SILENT', f'({flag})')
    if typ != 'OK':
        raise RuntimeError('השרת לא אישר את השינוי')
    _set_cached_flags(address.lower(), folder, uids, flag, on)


def uid_list(text):
    """'3,5:7' -> [3, 5, 6, 7] (an IMAP sequence set)."""
    out = []
    for part in (text or '').split(','):
        a, _, b = part.partition(':')
        if a.isdigit() and (not b or b.isdigit()):
            out += list(range(int(a), int(b or a) + 1)) if not b or int(b) >= int(a) else list(range(int(b), int(a) + 1))
    return out


def _copyuid(m, data):
    """The new UIDs in the target folder (UIDPLUS: [COPYUID validity old new]), in the order of the old ones — or []."""
    texts = [d.decode('utf-8', 'replace') for d in (data or []) if isinstance(d, bytes)]
    texts += [d.decode('utf-8', 'replace') if isinstance(d, bytes) else str(d) for d in (m.response('COPYUID')[1] or []) if d]
    for text in texts:
        found = re.search(r'(?:COPYUID )?(\d+) ([\d:,]+) ([\d:,]+)', text)
        if found:
            old, new = uid_list(found.group(2)), uid_list(found.group(3))
            if len(old) == len(new):
                return [n for _, n in sorted(zip(old, new))]
    return []


def move(address, folder, uids, target):
    """MOVE when the server knows it (almost all do); otherwise COPY + delete.
    Returns the messages' new UIDs in the target folder (for ↩️ undo), or [] when the server doesn't say."""
    if not target or target == folder:
        raise ValueError('צריך לבחור תיקייה אחרת')
    acc = account(address)
    with session(acc, folder) as m:
        ids = _uidset(uids)
        m.response('COPYUID')                            # forget an old answer
        if 'MOVE' in m.capabilities:
            typ, data = m.uid('MOVE', ids, quoted(target))
        else:
            typ, data = m.uid('COPY', ids, quoted(target))
            if typ == 'OK':
                m.uid('STORE', ids, '+FLAGS.SILENT', '(\\Deleted)')
                if 'UIDPLUS' in m.capabilities:
                    m.uid('EXPUNGE', ids)
                else:
                    m.expunge()
        new = _copyuid(m, data) if typ == 'OK' else []
    if typ != 'OK':
        raise RuntimeError('השרת לא אישר את ההעברה')
    _forget(address.lower(), folder, uids)
    return new


def mark_all_read(address, folder):
    """✓ Everything in the folder as read."""
    acc = account(address)
    with session(acc, folder) as m:
        typ, data = m.uid('SEARCH', None, 'UNSEEN')
        uids = (data[0] or b'').split() if typ == 'OK' and data else []
        for i in range(0, len(uids), 500):
            m.uid('STORE', b','.join(uids[i:i + 500]), '+FLAGS.SILENT', r'(\Seen)')
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        rows = db.execute('SELECT uid, data FROM heads WHERE acc=? AND folder=?', (address.lower(), folder)).fetchall()
        for uid, raw in rows:
            data = json.loads(raw)
            data['flags'] = sorted(set(data.get('flags', [])) | {'\\Seen'})
            db.execute('UPDATE heads SET data=? WHERE acc=? AND folder=? AND uid=?', (json.dumps(data, ensure_ascii=False), address.lower(), folder, uid))
    return len(uids)


def empty(address, folder):
    """🗑️ Empty the trash or the spam folder — gone for good. Only those two."""
    role = next((f['role'] for f in folders(address, fresh=False) if f['id'] == folder), '')
    if role not in ('trash', 'junk'):
        raise ValueError('אפשר לרוקן רק את האשפה ואת הספאם')
    acc = account(address)
    with session(acc, folder) as m:
        typ, data = m.uid('SEARCH', None, 'ALL')
        uids = (data[0] or b'').split() if typ == 'OK' and data else []
        for i in range(0, len(uids), 500):
            m.uid('STORE', b','.join(uids[i:i + 500]), '+FLAGS.SILENT', r'(\Deleted)')
        m.expunge()
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        db.execute('DELETE FROM heads WHERE acc=? AND folder=?', (address.lower(), folder))
        db.execute('DELETE FROM bodies WHERE acc=? AND folder=?', (address.lower(), folder))
    return len(uids)


def archive(address, folder, uids):
    """Out of the inbox, still kept: Gmail -> All Mail (the labels stay); elsewhere -> the Archive folder."""
    target = folder_of(address, 'all' if imap.is_gmail(account(address)) else 'archive')
    if not target:
        raise RuntimeError('לא נמצאה תיקיית ארכיון בתיבה הזו — אפשר להעביר לתיקייה אחרת')
    return target, move(address, folder, uids, target)


def delete(address, folder, uids):
    """To the trash; from the trash (or spam) itself — gone for good."""
    trash = folder_of(address, 'trash')
    role = next((f['role'] for f in folders(address, fresh=False) if f['id'] == folder), '')
    if trash and folder != trash and role != 'junk':
        return trash, move(address, folder, uids, trash)
    acc = account(address)
    with session(acc, folder) as m:
        ids = _uidset(uids)
        m.uid('STORE', ids, '+FLAGS.SILENT', '(\\Deleted)')
        if 'UIDPLUS' in m.capabilities:
            m.uid('EXPUNGE', ids)
        else:
            m.expunge()
    _forget(address.lower(), folder, uids)
    return None, []


def spam(address, folder, uids, back=False):
    target = 'INBOX' if back else folder_of(address, 'junk')
    if not target:
        raise RuntimeError('לא נמצאה תיקיית ספאם בתיבה הזו')
    return target, move(address, folder, uids, target)


def append(address, role, message, flags=r'(\Seen)'):
    """Keep a copy in Sent / Drafts. Returns (folder, new uid or None); folder is '' when there is no such folder."""
    target = folder_of(address, role)
    if not target:
        return '', None
    acc = account(address)
    with session(acc) as m:
        typ, data = m.append(quoted(target), flags, imaplib.Time2Internaldate(time.time()), message.as_bytes())
    found = re.search(rb'APPENDUID \d+ (\d+)', (data or [b''])[0] or b'') if typ == 'OK' else None
    return (target if typ == 'OK' else ''), (int(found.group(1)) if found else None)


def save_draft(address, message, replace_uid=None):
    """📝 To the Drafts folder (the old copy of the same draft goes). Returns (folder, uid)."""
    target, uid = append(address, 'drafts', message, r'(\Seen \Draft)')
    if not target:
        raise RuntimeError('לא נמצאה תיקיית טיוטות בתיבה הזו')
    if replace_uid:
        with contextlib.suppress(Exception):
            delete_for_good(address, target, [replace_uid])
    return target, uid


def delete_for_good(address, folder, uids):
    acc = account(address)
    with session(acc, folder) as m:
        ids = _uidset(uids)
        m.uid('STORE', ids, '+FLAGS.SILENT', '(\\Deleted)')
        if 'UIDPLUS' in m.capabilities:
            m.uid('EXPUNGE', ids)
        else:
            m.expunge()
    _forget(address.lower(), folder, uids)


def keeps_sent_copy(acc):
    """Gmail and Outlook.com / Office 365 put sent mail in Sent by themselves; other servers need a copy."""
    return acc.get('auth') in ('google', 'microsoft') or imap.is_gmail(acc)


def recipients(msg):
    return [a for _, a in getaddresses([str(msg.get(h) or '') for h in ('To', 'Cc', 'Bcc')]) if a]


def sender(msg):
    name, addr = parseaddr(decode(msg.get('From')))
    return name.strip(' "'), addr


# ---- managing folders / labels -------------------------------------------------------------------------------------------

def _separator(m):
    typ, data = m.list('""', '""')
    found = _parse_list(data) if typ == 'OK' else []
    return (found[0][1] if found and found[0][1] else '/')


def create_folder(address, name, parent=''):
    """A new folder (Gmail: a new label). parent: the id of the folder it goes under, or '' for the top."""
    name = re.sub(r'[\\"\x00-\x1f]', '', (name or '').strip())[:80]
    if not name:
        raise ValueError('צריך שם לתיקייה')
    acc = account(address)
    with session(acc) as m:
        sep = _separator(m)
        if sep and sep in name:
            raise ValueError(f'אי אפשר להשתמש בתו „{sep}” בשם')
        full = f'{parent}{sep}{imap.utf7(name)}' if parent else imap.utf7(name)
        typ, _ = m.create(quoted(full))
    if typ != 'OK':
        raise RuntimeError('השרת לא יצר את התיקייה (אולי כבר קיימת בשם הזה)')
    folders(address)
    return full


def rename_folder(address, folder, new_name):
    new_name = re.sub(r'[\\"\x00-\x1f]', '', (new_name or '').strip())[:80]
    if not new_name:
        raise ValueError('צריך שם חדש')
    if any(f['id'] == folder and f['role'] for f in folders(address, fresh=False)):
        raise ValueError('את התיקיות הקבועות (דואר נכנס, נשלח…) אי אפשר לשנות')
    acc = account(address)
    with session(acc) as m:
        sep = _separator(m)
        if sep and sep in new_name:
            raise ValueError(f'אי אפשר להשתמש בתו „{sep}” בשם')
        parent = folder.rsplit(sep, 1)[0] + sep if sep and sep in folder else ''
        target = parent + imap.utf7(new_name)
        typ, _ = m.rename(quoted(folder), quoted(target))
    if typ != 'OK':
        raise RuntimeError('השרת לא שינה את השם')
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        db.execute('DELETE FROM heads WHERE acc=? AND folder=?', (address.lower(), folder))
    folders(address)
    return target


def delete_folder(address, folder):
    """Deletes the folder itself. On Gmail the mail in it stays (in All Mail); elsewhere it must be empty first."""
    if any(f['id'] == folder and f['role'] for f in folders(address, fresh=False)):
        raise ValueError('את התיקיות הקבועות אי אפשר למחוק')
    acc = account(address)
    with session(acc) as m:
        if not imap.is_gmail(acc):
            typ, data = m.status(quoted(folder), '(MESSAGES)')
            count = re.search(rb'MESSAGES (\d+)', data[0] or b'') if typ == 'OK' else None
            if count and int(count.group(1)):
                raise RuntimeError(f'בתיקייה יש עוד {int(count.group(1))} הודעות — קודם להעביר או למחוק אותן')
        typ, _ = m.delete(quoted(folder))
    if typ != 'OK':
        raise RuntimeError('השרת לא מחק את התיקייה')
    with _DB_LOCK, contextlib.closing(_db()) as db, db:
        db.execute('DELETE FROM heads WHERE acc=? AND folder=?', (address.lower(), folder))
    folders(address)


def can(address):
    """Which actions this mailbox supports — the page hides the rest (no Archive folder -> no archive button)."""
    try:
        roles = {f['role'] for f in folders(address, fresh=False)}
        gmail = imap.is_gmail(account(address))
    except Exception:
        return {'archive': True, 'spam': True, 'drafts': True}
    return {'archive': ('all' in roles) if gmail else ('archive' in roles), 'spam': 'junk' in roles, 'drafts': 'drafts' in roles}


# ---- Gmail-style search for every server ---------------------------------------------------------------------------------

OPERATOR = re.compile(r'(-?)(from|to|cc|subject|has|is|newer_than|older_than|after|before|larger|smaller):("[^"]*"|\S+)', re.I)


def imap_criteria(query):
    """from: to: subject: has:attachment is:unread is:starred newer_than:7d older_than:1m after:2026/01/31 before: larger:5M
    and free words -> IMAP SEARCH (for servers other than Gmail, which understands these itself).
    Returns (criteria, [(key, text)]) — text that is not plain English must go as a literal, one per SEARCH."""
    crit, literal = [], []
    for neg, op, value in OPERATOR.findall(query):
        op, value = op.lower(), value.strip('"').replace('"', '').replace('\\', '')
        part = []
        if op in ('from', 'to', 'cc', 'subject'):
            if not value.isascii():
                if not neg:
                    literal.append((op.upper(), value))
                continue
            part = [op.upper(), f'"{value}"']
        elif op == 'has' and value.lower() in ('attachment', 'attachments'):
            part = ['OR', 'HEADER', 'Content-Type', '"multipart/mixed"', 'HEADER', 'Content-Disposition', '"attachment"']
        elif op == 'is':
            part = {'unread': ['UNSEEN'], 'read': ['SEEN'], 'starred': ['FLAGGED'], 'flagged': ['FLAGGED'],
                    'answered': ['ANSWERED']}.get(value.lower(), [])
        elif op in ('newer_than', 'older_than'):
            found = re.fullmatch(r'(\d+)([dmy])', value.lower())
            if found:
                days = int(found.group(1)) * {'d': 1, 'm': 30, 'y': 365}[found.group(2)]
                part = ['SINCE' if op == 'newer_than' else 'BEFORE', (dt.date.today() - dt.timedelta(days=days)).strftime('%d-%b-%Y')]
        elif op in ('after', 'before'):
            try:
                day = dt.datetime.strptime(value.replace('-', '/'), '%Y/%m/%d').strftime('%d-%b-%Y')
                part = ['SINCE' if op == 'after' else 'BEFORE', day]
            except ValueError:
                pass
        elif op in ('larger', 'smaller'):
            found = re.fullmatch(r'(\d+)([kKmM]?)', value)
            if found:
                part = [op.upper(), str(int(found.group(1)) * {'': 1, 'k': 1024, 'm': 1048576}[found.group(2).lower()])]
        if part:
            crit += ['NOT', '(' + ' '.join(part) + ')'] if neg else part
    words = ' '.join(OPERATOR.sub(' ', query).split())
    if words:
        literal.append(('TEXT', words))
    return crit, literal


def _search_imap(m, query, unread):
    crit, literal = imap_criteria(query)
    if unread:
        crit.append('UNSEEN')
    found = None
    for key, text in literal or [None]:                  # one SEARCH per Hebrew term, then what all of them found
        if key:
            m.literal = text.encode('utf-8')
            typ, data = m.uid('SEARCH', 'CHARSET', 'UTF-8', *crit, key)
        else:
            typ, data = m.uid('SEARCH', None, *(crit or ['ALL']))
        hits = {int(u) for u in (data[0] or b'').split()} if typ == 'OK' and data else set()
        found = hits if found is None else found & hits
    return sorted(found or (), reverse=True)


# ---- the home overview ---------------------------------------------------------------------------------------------------

def overview(addresses):
    """🏠 Per mailbox: connected?, unread in the inbox, the newest unread, and how much mail came each day this week."""
    out, latest = [], []
    week = [dt.date.today() - dt.timedelta(days=n) for n in range(6, -1, -1)]
    for address in addresses:
        row = {'email': address, 'ok': True, 'unread': 0, 'newest': '', 'days': [0] * 7}
        try:
            acc = account(address)
            with session(acc, 'INBOX', readonly=True) as m:
                typ, data = m.uid('SEARCH', None, 'UNSEEN')
                unseen = sorted((int(u) for u in (data[0] or b'').split()), reverse=True) if typ == 'OK' else []
                row['unread'] = len(unseen)
                if unseen:
                    typ, data = m.uid('FETCH', ','.join(map(str, unseen[:8])).encode(),
                                      f'(UID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS ({HEADERS})])')
                    for meta, lit in _records(data):
                        uid = re.search(r'UID (\d+)', meta)
                        if uid:
                            r = _row(uid.group(1), meta, lit, False)
                            r.pop('_heads', None)
                            r['account'] = address
                            latest.append(r)
                    row['newest'] = max((r['at'] for r in latest if r['account'] == address), default='')
                typ, data = m.uid('SEARCH', None, 'SINCE', week[0].strftime('%d-%b-%Y'))
                uids = (data[0] or b'').split() if typ == 'OK' and data else []
                if uids:
                    typ, data = m.uid('FETCH', b','.join(uids[-1500:]), '(UID INTERNALDATE)')
                    for line in data or []:
                        text = line.decode('utf-8', 'replace') if isinstance(line, bytes) else ''
                        stamp = re.search(r'INTERNALDATE "([^"]+)"', text)
                        if stamp:
                            day = dt.datetime.strptime(stamp.group(1), '%d-%b-%Y %H:%M:%S %z').astimezone().date()
                            if day in week:
                                row['days'][week.index(day)] += 1
        except Exception as exc:
            row.update(ok=False, error=str(exc)[:160])
        out.append(row)
    latest.sort(key=lambda r: r['at'], reverse=True)
    return {'accounts': out, 'latest': latest[:10], 'week': [d.isoformat() for d in week]}


# ---- offline: the newest messages, read in advance -----------------------------------------------------------------------

_PREFETCHING = set()


def prefetch(address, folder, rows, limit=25, max_size=3_000_000):
    """In the background, on a connection of its own: the bodies of the newest messages go into the cache, so they open
    at once — and still open with no internet. BODY.PEEK: nothing is marked as read."""
    key = (address.lower(), folder)
    if key in _PREFETCHING:
        return
    with _DB_LOCK, contextlib.closing(_db()) as db:
        have = {r[0] for r in db.execute('SELECT uid FROM bodies WHERE acc=? AND folder=?', (address.lower(), folder))}
    wanted = [r['uid'] for r in rows if r['uid'] not in have and r.get('size', 0) <= max_size][:limit]
    if not wanted:
        return
    _PREFETCHING.add(key)

    def work():
        try:
            m = imap.connect(account(address))
            try:
                m.select(quoted(folder), readonly=True)
                validity = _validity(m)
                for uid in wanted:
                    typ, data = m.uid('FETCH', str(uid).encode(), '(UID BODY.PEEK[])')
                    recs = _records(data)
                    if typ == 'OK' and recs:
                        _keep_body(address.lower(), folder, uid, validity, recs[0][1])
            finally:
                with contextlib.suppress(Exception):
                    m.logout()
        except Exception:
            pass
        finally:
            _PREFETCHING.discard(key)
    threading.Thread(target=work, daemon=True).start()
