"""Mail history for statistics and client cards."""
import collections
import datetime as dt
from urllib.parse import quote

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.classify import classify, demote_automated
from mailbrief.mail.imap import fetch_recent, is_gmail, mark_unanswered
from mailbrief.money.ledger import item_key, vendor_key
from mailbrief.storage import load_json, save_json


def update_history(results):
    history = load_json(config.HISTORY_FILE, {})
    for res in results:
        for it in res['items']:
            history[item_key(res['email'], it)] = {'date': it['iso'][:10], 'hour': it['iso'][11:13], 'account': res['email'],
                                                   'cats': it['cats'], 'rules': it.get('rules', []), 'sender': it['sender'],
                                                   'name': it['sender_name'], 'answered': it.get('answered'),
                                                   'subject': it['subject'][:150], 'link': it.get('link', '')}
    cutoff = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    save_json(config.HISTORY_FILE, {k: v for k, v in history.items() if v['date'] >= cutoff})


def build_history(days=30):
    """Fast statistics backfill: headers only (no bodies), no tagging, nothing changes in the mailbox."""
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
    save_json(config.ACCOUNTS_FILE, accounts)
    update_history(results)
    return sum(len(r['items']) for r in results), [f"{r['email']}: {r['error']}" for r in results if r['error']]


def client_groups():
    """Clients = the user's rule labels, plus people / companies they actually correspond with (2+ personal emails in 90 days)."""
    history, rules = load_json(config.HISTORY_FILE, {}), load_json(config.RULES_FILE, [])
    since = (dt.date.today() - dt.timedelta(days=90)).isoformat()
    rows = sorted((h for h in history.values() if h['date'] >= since), key=lambda h: h['date'])
    groups = {}
    for label in sorted({r['label'] for r in rules} | {l for h in rows for l in h.get('rules', [])}):
        queries = [r['contains'] for r in rules if r['label'] == label]
        groups[f'label:{label}'] = {'name': f'🏷️ {label}', 'emails': [h for h in rows if label in h.get('rules', [])],
                                   'match': lambda r, label=label: label in r.get('rules', []),
                                   'query': ' OR '.join(queries) or label}
    personal = collections.Counter(vendor_key(h['sender']) for h in rows if 'people' in h['cats'])
    for key, count in personal.items():
        if count < 2 or any(key in q['query'] for q in groups.values()):
            continue
        emails = [h for h in rows if vendor_key(h['sender']) == key]
        groups[f'sender:{key}'] = {'name': emails[-1].get('name') or key, 'emails': emails,
                                   'match': lambda r, key=key: r['vendor_key'] == key, 'query': f'from:{key}' if '@' not in key else f'from:{key}'}
    ledger = load_json(config.LEDGER_FILE, {})
    for g in groups.values():
        g['invoices'] = sorted((r for r in ledger.values() if g['match'](r)), key=lambda r: r['date'])
        g['last'] = g['emails'][-1]['date'] if g['emails'] else ''
        g['waiting'] = sum(1 for h in g['emails'] if h.get('answered') is False)
    return dict(sorted(groups.items(), key=lambda kv: kv[1]['last'], reverse=True))
