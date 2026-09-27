"""📦 Everything a client sent in the last year, in one ZIP: the files attached to their emails (every mailbox) and the
receipts MailBrief already keeps for them. Saved in Downloads; nothing changes in the mailbox."""
import datetime as dt
import email
import hashlib
import os
import zipfile
from email.policy import default as default_policy
from email.utils import parsedate_to_datetime

from mailbrief import config
from mailbrief.features.history import client_groups
from mailbrief.mail import imap
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.imap import is_gmail, special_folder
from mailbrief.mail.message import decode
from mailbrief.storage import load_json, save_json
from mailbrief.util import safe_name


MAX_MESSAGES = 300


def _unique(names, name):
    base, ext = os.path.splitext(name)
    n, out = 2, name
    while out in names:
        out, n = f'{base} ({n}){ext}', n + 1
    names.add(out)
    return out


def _mail_files(acc, g, since):
    """(date, file name, bytes) of every attachment from this client in one mailbox, since the date."""
    senders = sorted({h['sender'] for h in g['emails'] if h.get('sender')})
    m = imap.connect(acc)
    try:
        m.select(f'"{special_folder(m, chr(92) + "All") or "INBOX"}"', readonly=True)
        if is_gmail(acc):
            m.literal = f'({g["query"]}) has:attachment after:{since:%Y/%m/%d}'.encode('utf-8')
            typ, data = m.uid('SEARCH', 'CHARSET', 'UTF-8', 'X-GM-RAW')
            uids = data[0].split() if typ == 'OK' and data and data[0] else []
        else:
            uids = []
            for s in senders[:10]:
                typ, data = m.uid('SEARCH', None, 'SINCE', since.strftime('%d-%b-%Y'), 'FROM', f'"{s}"')
                uids += data[0].split() if typ == 'OK' and data and data[0] else []
        for uid in sorted(set(uids), key=int)[-MAX_MESSAGES:]:
            typ, rows = m.uid('FETCH', uid, '(BODY.PEEK[])')
            if typ != 'OK' or not rows or not isinstance(rows[0], tuple):
                continue
            msg = email.message_from_bytes(rows[0][1], policy=default_policy)
            try:
                day = parsedate_to_datetime(msg.get('Date')).astimezone().strftime('%Y-%m-%d')
            except Exception:
                day = ''
            for part in msg.iter_attachments():
                blob = part.get_payload(decode=True)
                if blob and len(blob) > 2000:                     # not the tiny logos in signatures
                    yield day, safe_name(decode(part.get_filename()) or 'file') or 'file', blob
    finally:
        m.logout()


def client_zip(key, days=365):
    """Returns (path, files, errors). One file per content — the same PDF sent twice is kept once."""
    g = client_groups().get(key)
    if not g:
        raise RuntimeError('הלקוח לא נמצא')
    since = dt.date.today() - dt.timedelta(days=days)
    accounts = load_json(config.ACCOUNTS_FILE, [])
    seen, names, errors, count = set(), set(), [], 0
    os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
    path = os.path.join(config.DOWNLOADS_DIR, safe_name(f'{g["name"].lstrip("🏷️ ")} — מסמכים {dt.date.today():%Y-%m-%d}')[:90] + '.zip')
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for r in g['invoices']:                                   # receipts already on the computer
            if r['date'] < since.isoformat():
                continue
            for rel in r.get('files', []):
                src = os.path.join(config.RECEIPTS_DIR, rel)
                if not os.path.isfile(src):
                    continue
                with open(src, 'rb') as f:
                    blob = f.read()
                digest = hashlib.sha1(blob).hexdigest()
                if digest not in seen:
                    seen.add(digest)
                    z.writestr('קבלות/' + _unique(names, f'{r["date"]} {os.path.basename(rel)}'), blob)
                    count += 1
        for acc in accounts:
            try:
                for day, name, blob in _mail_files(acc, g, since):
                    digest = hashlib.sha1(blob).hexdigest()
                    if digest not in seen:
                        seen.add(digest)
                        z.writestr('מהמייל/' + _unique(names, f'{day} {name}'.strip()), blob)
                        count += 1
            except Exception as exc:
                errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
    save_json(config.ACCOUNTS_FILE, accounts)
    if not count:
        os.remove(tmp)
        return '', 0, errors
    os.replace(tmp, path)
    return path, count, errors
