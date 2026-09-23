"""The first look: what the last 30 days of mail say — right after connecting, in a minute or two."""
import collections
import datetime as dt
from urllib.parse import quote

from mailbrief import config
from mailbrief.features.alerts import save_snapshot
from mailbrief.features.brief import import_receipts
from mailbrief.features.history import update_history
from mailbrief.features.unsubscribe import remember_unsubs, unsub_id
from mailbrief.mail import imap
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.classify import classify, demote_automated
from mailbrief.mail.imap import fetch_recent, is_gmail, mark_unanswered
from mailbrief.money.ledger import find_subscriptions, ils
from mailbrief.storage import load_json, save_json


DAYS = 30


def scan_headers(days=DAYS):
    """Headers only (fast, nothing changes in the mailbox): categories, newsletters with their unsubscribe links, replies."""
    accounts, rules = load_json(config.ACCOUNTS_FILE, []), load_json(config.RULES_FILE, [])
    own = [a['email'] for a in accounts]
    results = []
    for acc in accounts:
        res = {'email': acc['email'], 'items': [], 'error': None}
        try:
            m = imap.connect(acc)
            try:
                for _, gid, msg in fetch_recent(m, is_gmail(acc), days=days, readonly=True, limit=3000, headers_only=True):
                    it = classify(msg, acc['email'], rules)
                    it['message_id'] = (msg.get('Message-ID') or '').strip()
                    it['link'] = f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{gid:x}" if gid else ''
                    res['items'].append(it)
                demote_automated(res['items'], own)
                mark_unanswered(m, res['items'])
            finally:
                m.logout()
        except Exception as exc:
            res['error'] = friendly_error(exc, acc)
        results.append(res)
    save_json(config.ACCOUNTS_FILE, accounts)                 # keep rotated refresh tokens
    return results


def summarize(results, ledger, unsubs):
    items = [(r['email'], it) for r in results for it in r['items']]
    news = collections.Counter()
    for address, it in items:
        if 'newsletters' in it['cats']:
            news[unsub_id(address, it['sender'])] += 1
    letters = []
    for key, count in news.most_common():
        entry = unsubs.get(key)
        if entry and not entry.get('done'):
            letters.append({'id': key, 'name': entry.get('name') or entry['sender'], 'sender': entry['sender'],
                            'count': count, 'one_click': bool(entry.get('one_click'))})
    subs = []
    for s in find_subscriptions(ledger):
        rows = sorted((r for r in ledger.values() if r['vendor_key'] == s['key']), key=lambda r: r['date'])
        subs.append(s | {'ils': ils(rows[-1]) if rows else None})
    since = (dt.date.today() - dt.timedelta(days=DAYS)).isoformat()
    month_receipts = [r for r in ledger.values() if r['date'] >= since]
    waiting = sorted(({'account': a, 'from': it['sender_name'], 'subject': it['subject'], 'link': it.get('link', ''),
                       'days': it.get('waiting_days', 0)} for a, it in items if it.get('answered') is False),
                     key=lambda w: -w['days'])
    return {
        'at': dt.datetime.now().strftime('%d/%m/%Y %H:%M'), 'days': DAYS,
        'emails': len(items), 'senders': len({it['sender'] for _, it in items}),
        'people': sum(1 for _, it in items if 'people' in it['cats']),
        'newsletter_emails': sum(news.values()), 'newsletters': letters,
        'subs': subs, 'subs_month_ils': round(sum(s['ils'] for s in subs if s['ils'] is not None), 2),
        'receipts': len(month_receipts),
        'receipts_ils': round(sum(ils(r) for r in month_receipts if ils(r) is not None), 2),
        'waiting': waiting[:12], 'waiting_count': len(waiting),
        'security': sum(1 for _, it in items if 'security' in it['cats'] or 'phishing' in it['cats']),
        'errors': [f"{r['email']}: {r['error']}" for r in results if r['error']],
    }


def first_look():
    results = scan_headers()
    update_history(results)
    remember_unsubs(results)
    save_snapshot([(r['email'], r['items']) for r in results if not r['error']])
    import_receipts(90)                                        # subscriptions need a few months to show a pattern
    data = summarize(results, load_json(config.LEDGER_FILE, {}), load_json(config.UNSUBS_FILE, {}))
    save_json(config.INSIGHTS_FILE, data)
    return data
