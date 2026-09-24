"""The weekly scan of every mailbox."""
import datetime as dt
import os
from urllib.parse import quote

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.features.alerts import save_snapshot
from mailbrief.features.archive import archive_messages, archive_old_newsletters
from mailbrief.features.forwarding import process_forwards
from mailbrief.features.history import update_history
from mailbrief.features.report import write_report
from mailbrief.features.unsubscribe import remember_unsubs
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.classify import classify, demote_automated
from mailbrief.mail.imap import fetch_recent, is_gmail, mark_unanswered, special_folder
from mailbrief.mail.labels import apply_tags
from mailbrief.money.pdftext import amount_from_attachments
from mailbrief.money.ledger import BOI_CODES, find_subscriptions, item_key, save_attachments, update_ledger
from mailbrief.storage import load_json, save_json


def scan_account(acc, state, rules=(), days=config.DAYS, receipts_only=False):
    result = {'email': acc['email'], 'items': [], 'tagged': 0, 'error': None}
    try:
        m = imap.connect(acc)
        try:
            gmail = is_gmail(acc)
            if receipts_only:                    # history import: all mail, receipts only, no tagging
                source = dict(folder=special_folder(m, r'\All') or 'INBOX', readonly=True, limit=1500,
                              gmail_raw='receipt OR invoice OR חשבונית OR קבלה OR payment OR billing OR חיוב OR subscription')
            else:
                source = {}
            pending = []
            for uid, gid, msg in fetch_recent(m, gmail, days=days, **source):
                it = classify(msg, acc['email'], rules)
                if receipts_only and 'receipts' not in it['cats']:
                    continue
                if it['forward'] and not receipts_only:
                    pending.append((it, msg))
                it['uid'] = uid
                it['message_id'] = (msg.get('Message-ID') or '').strip()
                if gid:
                    it['link'] = f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{gid:x}"
                if 'receipts' in it['cats']:
                    try:
                        it['files'] = save_attachments(msg, it)
                    except OSError:
                        it['files'] = []
                    if not it.get('amount'):             # the total only inside the attached PDF
                        it['amount'] = amount_from_attachments(msg)
                result['items'].append(it)
                if not receipts_only:
                    result.setdefault('_keep', []).append((it, msg))   # for the local archive, after demote_automated
            demote_automated(result['items'], [a['email'] for a in load_json(config.ACCOUNTS_FILE, [])] + [acc['email']])
            if acc.get('tag', True) and not receipts_only:
                result['tagged'] = apply_tags(m, acc, result['items'], state)
            if not receipts_only:
                mark_unanswered(m, result['items'])
                result['forwarded'] = process_forwards(acc, pending, state) if pending else 0
        finally:
            try:
                m.logout()
            except Exception:
                pass
    except Exception as exc:
        result['error'] = friendly_error(exc, acc)
    return result


def run_all(open_report=True, only=None):
    """The brief for every mailbox — or, with only=address, for that one mailbox (the others' data stays as it was)."""
    accounts = load_json(config.ACCOUNTS_FILE, [])
    state = load_json(config.STATE_FILE, {})
    rules = load_json(config.RULES_FILE, [])
    targets = [a for a in accounts if not only or a['email'].lower() == only.lower()]
    results = [scan_account(a, state, rules) for a in targets]
    save_json(config.STATE_FILE, state)
    for res in results:
        try:
            archive_messages(res['email'], res.pop('_keep', []))
        except OSError:
            pass
    if load_json(config.SETTINGS_FILE, {}).get('auto_archive_news'):
        archive_old_newsletters(3)
    remember_unsubs(results)
    ledger = update_ledger(results)
    for res in results:                          # bring rate / double-charge info back into the report items
        for it in res['items']:
            row = ledger.get(item_key(res['email'], it)) if 'receipts' in it['cats'] else None
            if row:
                it['duplicate'] = row.get('duplicate', '')
                if row['currency'] in BOI_CODES and row.get('amount_ils') is not None:
                    it['amount'] = f"{it.get('amount', '')} (≈₪{row['amount_ils']:,.2f})"
    update_history(results)
    save_snapshot([(r['email'], r['items']) for r in results if not r['error']], only=only)
    path = write_report(results, find_subscriptions(ledger))
    for acc, res in zip(targets, results):
        acc['last'] = {'at': dt.datetime.now().strftime('%d/%m %H:%M'), 'error': res['error'],
                       'count': len(res['items']), 'tagged': res['tagged']}
    save_json(config.ACCOUNTS_FILE, accounts)
    if open_report:
        os.startfile(path)
    return path, results


def import_receipts(days=90):
    accounts, rules = load_json(config.ACCOUNTS_FILE, []), load_json(config.RULES_FILE, [])
    results = [scan_account(a, {}, rules, days=days, receipts_only=True) for a in accounts]
    save_json(config.ACCOUNTS_FILE, accounts)
    update_ledger(results)
    return sum(len(r['items']) for r in results), [f"{r['email']}: {r['error']}" for r in results if r['error']]
