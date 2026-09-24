"""Tidying up: "clean the inbox" (archive what is old, not starred and not waiting for an answer — nothing is deleted)
and newsletters that are never opened (to unsubscribe from all of them together)."""
import datetime as dt
import email
import re
from email.policy import default as default_policy

from mailbrief import config
from mailbrief.features.unsubscribe import unsub_id, unsubscribe
from mailbrief.mail import imap
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.classify import classify, demote_automated
from mailbrief.mail.imap import is_gmail, special_folder
from mailbrief.storage import load_json, save_json


MAX_ARCHIVE = 5000          # per mailbox, per click


def _before(days):
    return (dt.date.today() - dt.timedelta(days=days)).strftime('%d-%b-%Y')


def _keep_ids():
    """Message-IDs that must stay in the inbox: mail from people still waiting for an answer, and snoozed mail."""
    snap = load_json(config.SNAPSHOT_FILE, {})
    ids = {(r.get('message_id') or '').strip() for r in snap.get('waiting', []) + snap.get('urgent', [])}
    return {i for i in ids if i}


def _old_uids(m, days, keep):
    m.select('INBOX', readonly=True)
    typ, data = m.uid('SEARCH', None, 'BEFORE', _before(days), 'UNFLAGGED')
    uids = data[0].split() if typ == 'OK' and data and data[0] else []
    if keep and uids:
        drop = set()
        for i in range(0, len(uids), 200):
            typ, rows = m.uid('FETCH', b','.join(uids[i:i + 200]), '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
            for row in rows or []:
                if isinstance(row, tuple):
                    uid = re.search(rb'UID (\d+)', row[0])
                    mid = email.message_from_bytes(row[1], policy=default_policy).get('Message-ID', '').strip()
                    if uid and mid in keep:
                        drop.add(uid.group(1))
        uids = [u for u in uids if u not in drop]
    return uids[:MAX_ARCHIVE]


def inbox_preview(days=30, only=None):
    """[(address, how many would be archived, error)] — reads only, changes nothing."""
    accounts, keep, out = load_json(config.ACCOUNTS_FILE, []), _keep_ids(), []
    for acc in accounts:
        if only and acc['email'].lower() != only.lower():
            continue
        try:
            m = imap.connect(acc)
            try:
                out.append((acc['email'], len(_old_uids(m, days, keep)), ''))
            finally:
                m.logout()
        except Exception as exc:
            out.append((acc['email'], 0, friendly_error(exc, acc)))
    save_json(config.ACCOUNTS_FILE, accounts)
    return out


def _archive_folder(m):
    found = special_folder(m, r'\Archive')
    if found:
        return found
    m.create('Archive')                           # fails harmlessly when it exists
    return 'Archive'


def clean_inbox(days=30, only=None):
    """Archives old inbox mail. Gmail: removes the Inbox label (the mail stays in "All mail"). Other servers: moves
    it to the Archive folder. Starred mail and mail waiting for your answer stay. Returns (moved, errors)."""
    accounts, keep, moved, errors = load_json(config.ACCOUNTS_FILE, []), _keep_ids(), 0, []
    for acc in accounts:
        if only and acc['email'].lower() != only.lower():
            continue
        try:
            m = imap.connect(acc)
            try:
                uids = _old_uids(m, days, keep)
                if not uids:
                    continue
                gmail = is_gmail(acc)
                target = None if gmail else _archive_folder(m)
                m.select('INBOX')
                for i in range(0, len(uids), 200):
                    chunk = b','.join(uids[i:i + 200])
                    if gmail:
                        ok = m.uid('STORE', chunk, '-X-GM-LABELS', r'(\Inbox)')[0] == 'OK'
                    else:
                        ok = m.uid('MOVE', chunk, f'"{target}"')[0] == 'OK'
                        if not ok and m.uid('COPY', chunk, f'"{target}"')[0] == 'OK':
                            m.uid('STORE', chunk, '+FLAGS', r'(\Deleted)')
                            ok = 'UIDPLUS' in m.capabilities and m.uid('EXPUNGE', chunk)[0] == 'OK'
                    if ok:
                        moved += len(uids[i:i + 200])
            finally:
                m.logout()
        except Exception as exc:
            errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
    save_json(config.ACCOUNTS_FILE, accounts)
    return moved, errors


# ---- newsletters nobody reads -----------------------------------------------------------------------------------------

def never_opened(days=60, min_count=3):
    """Newsletters with at least min_count issues in the last `days` days, none of them opened.
    [{'id', 'name', 'sender', 'account', 'count', 'one_click'}] — the unsubscribe entries must already be known."""
    accounts, rules, unsubs = load_json(config.ACCOUNTS_FILE, []), load_json(config.RULES_FILE, []), load_json(config.UNSUBS_FILE, {})
    own, stats = [a['email'] for a in accounts], {}
    since = (dt.date.today() - dt.timedelta(days=days)).strftime('%d-%b-%Y')
    for acc in accounts:
        try:
            m = imap.connect(acc)
        except Exception:
            continue
        try:
            folder = special_folder(m, r'\All') if is_gmail(acc) else None
            m.select(f'"{folder}"' if folder else 'INBOX', readonly=True)
            typ, data = m.uid('SEARCH', None, 'SINCE', since, 'HEADER', 'List-Unsubscribe', '""')
            uids = data[0].split()[-3000:] if typ == 'OK' and data and data[0] else []
            items = []
            for i in range(0, len(uids), 50):
                typ, rows = m.uid('FETCH', b','.join(uids[i:i + 50]), '(FLAGS BODY.PEEK[HEADER])')
                for row in rows or []:
                    if isinstance(row, tuple):
                        it = classify(email.message_from_bytes(row[1], policy=default_policy), acc['email'], rules)
                        it['seen'] = b'\\Seen' in row[0]
                        items.append(it)
            demote_automated(items, own)
            for it in items:
                if 'newsletters' in it['cats']:
                    s = stats.setdefault(unsub_id(acc['email'], it['sender']), {'count': 0, 'opened': 0})
                    s['count'] += 1
                    s['opened'] += it['seen']
        except Exception:
            pass
        finally:
            try:
                m.logout()
            except Exception:
                pass
    save_json(config.ACCOUNTS_FILE, accounts)
    out = []
    for key, s in stats.items():
        entry = unsubs.get(key)
        if entry and not entry.get('done') and s['count'] >= min_count and not s['opened']:
            out.append({'id': key, 'name': entry.get('name') or entry['sender'], 'sender': entry['sender'],
                        'account': entry['account'], 'count': s['count'], 'one_click': bool(entry.get('one_click'))})
    out.sort(key=lambda r: -r['count'])
    cache = load_json(config.CACHE_FILE, {})
    cache['never_opened'] = {'at': dt.date.today().isoformat(), 'rows': out}
    save_json(config.CACHE_FILE, cache)
    return out


def unsubscribe_many(ids):
    """One-click unsubscribes are done here; the rest need the sender's page. Returns (done, need_page, messages)."""
    unsubs, done, pages = load_json(config.UNSUBS_FILE, {}), 0, []
    for key in ids:
        entry = unsubs.get(key)
        if not entry or entry.get('done'):
            continue
        kind, value = unsubscribe(entry)
        if kind == 'done' and value.startswith('✓'):
            entry['done'] = dt.date.today().strftime('%d/%m')
            done += 1
        elif kind == 'open':
            pages.append((entry.get('name') or entry['sender'], value))
    save_json(config.UNSUBS_FILE, unsubs)
    return done, pages
