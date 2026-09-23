"""The hourly check: alerts, automations, forwarding, vacation replies and the "My day" snapshot."""
import datetime as dt
from urllib.parse import quote

from mailbrief import config
from mailbrief.features import notify
from mailbrief.mail import imap
from mailbrief.features.automations import run_schedule_workflows, run_workflows, workflows_need_write
from mailbrief.features.forwarding import process_forwards
from mailbrief.features.replies import vacation_replies
from mailbrief.mail.classify import classify, demote_automated
from mailbrief.mail.imap import fetch_recent, is_gmail, mark_unanswered
from mailbrief.money.ledger import find_duplicate, item_key, parse_amount, vendor_key
from mailbrief.storage import load_json, save_json


def save_snapshot(per_account):
    """per_account: [(email, items)] — what the "My day" page shows about mail, without a slow live scan."""
    waiting, urgent, due = [], [], []
    for address, items in per_account:
        for it in items:
            row = {'account': address, 'from': it['sender_name'], 'subject': it['subject'], 'link': it.get('link', ''),
                   'message_id': it.get('message_id', '')}
            if it.get('due'):
                due.append(row | {'due': it['due'], 'amount': it.get('amount', '')})
            if it.get('answered') is False:
                waiting.append(row | {'days': it.get('waiting_days', 0)})
            if it['unusual'] or 'urgent' in it['cats'] or 'phishing' in it['cats']:
                why = '🎣 חשד לפישינג' if 'phishing' in it['cats'] else 'חריג באבטחה' if it['unusual'] else 'דחוף'
                urgent.append(row | {'why': why, 'date': it['date']})
    save_json(config.SNAPSHOT_FILE, {'at': dt.datetime.now().strftime('%d/%m %H:%M'),
                              'waiting': sorted(waiting, key=lambda w: -w['days']), 'urgent': urgent, 'due': due})


def upcoming_payments(days=14):
    """Payment deadlines from the receipts ledger and from the latest check, soonest first."""
    today, seen, rows = dt.date.today(), set(), []
    sources = [{'from': r['vendor'], 'subject': r['subject'], 'link': r.get('link', ''), 'due': r['due'],
                'amount': f"{r['currency']}{r['amount']}" if r['amount'] is not None else ''}
               for r in load_json(config.LEDGER_FILE, {}).values() if r.get('due')] + load_json(config.SNAPSHOT_FILE, {}).get('due', [])
    for r in sources:
        key = (r['subject'], r['due'])
        if key in seen:
            continue
        seen.add(key)
        left = (dt.date.fromisoformat(r['due']) - today).days
        if -3 <= left <= days:
            rows.append(r | {'left': left})
    return sorted(rows, key=lambda r: r['due'])


def check_alerts():
    """Quick look at the last 2 days; pop a Windows notification only for new urgent / unusual / flagged mail."""
    accounts = load_json(config.ACCOUNTS_FILE, [])
    state = load_json(config.STATE_FILE, {})
    rules = load_json(config.RULES_FILE, [])
    seen = set(state.get('_alerted', []))
    ledger = load_json(config.LEDGER_FILE, {})
    known_vendors = {r['vendor_key'] for r in ledger.values()}
    now = dt.datetime.now().astimezone()
    alerts = []                                  # (reason, item)
    snapshot = []
    budget = [config.MAX_WORKFLOW_RUNS]                 # shared across mailboxes: at most this many automation runs per check
    for acc in accounts:
        try:
            m = imap.connect(acc)
            try:
                items, pending, pairs = [], [], []
                for uid, gid, msg in fetch_recent(m, is_gmail(acc), days=7, readonly=not workflows_need_write()):
                    it = classify(msg, acc['email'], rules)
                    it['uid'] = uid
                    it['message_id'] = (msg.get('Message-ID') or '').strip()
                    it['link'] = f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{gid:x}" if gid else ''
                    items.append(it)
                    pairs.append((it, msg))
                    if it['forward']:
                        pending.append((it, msg))
                demote_automated(items, [a['email'] for a in accounts])
                mark_unanswered(m, items)
                run_workflows(m, acc, pairs, state, ledger, budget)
                vacation_replies(acc, pairs, state)
            finally:
                m.logout()
            if pending:
                process_forwards(acc, pending, state)
            snapshot.append((acc['email'], items))
        except Exception:
            continue
        for it in items:
            fresh = (now - dt.datetime.fromisoformat(it['iso'])).days <= 2
            reasons = [
                ('phish', '🎣 חשד לפישינג — לא ללחוץ', fresh and 'phishing' in it['cats']),
                ('unusual', 'חריג באבטחה', fresh and it['unusual']),
                ('urgent', 'דחוף', fresh and 'urgent' in it['cats']),
                ('rule', ' · '.join(it['rules']), fresh and it['notify']),
                ('vendor', 'חיוב מספק חדש', fresh and 'receipts' in it['cats'] and bool(known_vendors)
                 and vendor_key(it['sender']) not in known_vendors),
                ('waiting', f'ממתין לתשובה {it.get("waiting_days", 0)} ימים', it.get('waiting_days', 0) >= config.WAIT_DAYS),
                ('due', f'לתשלום עד {it.get("due", "")[8:10]}/{it.get("due", "")[5:7]}',
                 bool(it.get('due')) and 0 <= (dt.date.fromisoformat(it['due']) - now.date()).days <= 2),
                ('double', 'ייתכן חיוב כפול', fresh and 'receipts' in it['cats'] and bool(find_duplicate(
                    ledger, item_key(acc['email'], it), vendor_key(it['sender']), parse_amount(it.get('amount'))[0],
                    it['iso'][:10], it['subject']))),
            ]
            for kind, text, hit in reasons:
                key = f"{item_key(acc['email'], it)}|{kind}"
                if hit and key not in seen:
                    seen.add(key)
                    alerts.append((text, it))
    if snapshot:
        save_snapshot(snapshot)
    run_schedule_workflows(state, accounts)
    state['_alerted'] = sorted(seen)[-3000:]
    save_json(config.STATE_FILE, state)
    save_json(config.ACCOUNTS_FILE, accounts)          # keep rotated refresh tokens
    if not alerts:
        return 0
    why, first = alerts[0]
    title = f'📬 MailBrief — {why}' if len(alerts) == 1 else f'📬 MailBrief — {len(alerts)} הודעות דורשות תשומת לב'
    notify.toast(title, [f'{first["subject"]} ({first["sender_name"]})'] + [f'{t}: {a["subject"]}' for t, a in alerts[1:2]],
          first.get('link') or f'http://127.0.0.1:{config.PORT}/')
    return len(alerts)
