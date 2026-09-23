"""Search across all mailboxes and bulk attachment download."""
import datetime as dt
import email
import imaplib
import os
import re
from email.policy import default as default_policy
from email.utils import parseaddr
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.imap import is_gmail, special_folder
from mailbrief.mail.message import decode
from mailbrief.storage import load_json, save_json
from mailbrief.util import safe_name, write_once


def search_mail(query):
    accounts, found, errors = load_json(config.ACCOUNTS_FILE, []), [], []
    for acc in accounts:
        try:
            m = imap.connect(acc)
            try:
                gmail = is_gmail(acc)
                m.select(f'"{special_folder(m, chr(92) + "All") or "INBOX"}"', readonly=True)
                m.literal = query.encode('utf-8')
                try:
                    typ, data = m.uid('SEARCH', 'CHARSET', 'UTF-8', 'X-GM-RAW' if gmail else 'TEXT')
                except imaplib.IMAP4.error:
                    if not query.isascii():
                        raise
                    typ, data = m.uid('SEARCH', None, 'TEXT', f'"{query}"')
                uids = data[0].split()[-40:] if typ == 'OK' and data[0] else []
                what = '(X-GM-MSGID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])' if gmail else '(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])'
                typ, rows = m.uid('FETCH', b','.join(uids), what) if uids else ('OK', [])
                for row in rows or []:
                    if not isinstance(row, tuple):
                        continue
                    msg = email.message_from_bytes(row[1], policy=default_policy)
                    gid = re.search(r'X-GM-MSGID (\d+)', row[0].decode(errors='replace'))
                    name, addr = parseaddr(decode(msg.get('From')))
                    try:
                        when = parsedate_to_datetime(msg.get('Date')).astimezone()
                    except Exception:
                        when = None
                    found.append({'account': acc['email'], 'from': name or addr, 'subject': decode(msg.get('Subject')) or '(ללא נושא)',
                                  'when': when, 'link': f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{int(gid.group(1)):x}" if gid else ''})
            finally:
                m.logout()
        except Exception as exc:
            errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
    save_json(config.ACCOUNTS_FILE, accounts)
    found.sort(key=lambda r: r['when'].timestamp() if r['when'] else 0, reverse=True)
    return found, errors


def download_search_attachments(query, limit=100):
    accounts, saved, errors = load_json(config.ACCOUNTS_FILE, []), 0, []
    folder = os.path.join(config.DOWNLOADS_DIR, f'{dt.date.today()} {safe_name(query)[:50]}')
    for acc in accounts:
        try:
            m = imap.connect(acc)
            try:
                gmail = is_gmail(acc)
                m.select(f'"{special_folder(m, chr(92) + "All") or "INBOX"}"', readonly=True)
                m.literal = f'{query} has:attachment'.encode('utf-8') if gmail else query.encode('utf-8')
                typ, data = m.uid('SEARCH', 'CHARSET', 'UTF-8', 'X-GM-RAW' if gmail else 'TEXT')
                for uid in (data[0].split()[-limit:] if typ == 'OK' and data[0] else []):
                    typ, rows = m.uid('FETCH', uid, '(BODY.PEEK[])')
                    msg = email.message_from_bytes(rows[0][1], policy=default_policy)
                    try:
                        day = parsedate_to_datetime(msg.get('Date')).astimezone().strftime('%Y-%m-%d')
                    except Exception:
                        day = 'no-date'
                    who = safe_name(parseaddr(decode(msg.get('From')))[0] or parseaddr(decode(msg.get('From')))[1])[:30]
                    for part in msg.iter_attachments():
                        blob = part.get_payload(decode=True)
                        if blob and len(blob) > 2000:          # skip tiny inline logos
                            write_once(os.path.join(folder, safe_name(acc['email'])),
                                       f'{day} {who} - {safe_name(decode(part.get_filename()) or "file")}', blob)
                            saved += 1
            finally:
                m.logout()
        except Exception as exc:
            errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
    save_json(config.ACCOUNTS_FILE, accounts)
    return folder, saved, errors
