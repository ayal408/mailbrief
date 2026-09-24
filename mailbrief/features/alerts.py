"""The hourly check: alerts, automations, forwarding, vacation replies and the "My day" snapshot."""
import datetime as dt
from urllib.parse import quote

from mailbrief import config
from mailbrief.address import link
from mailbrief.features import notify
from mailbrief.mail import imap
from mailbrief.features.followups import awaiting_replies
from mailbrief.features.invites import find_invite, upcoming, when_text
from mailbrief.features.automations import run_schedule_workflows, run_workflows, workflows_need_write
from mailbrief.features.forwarding import process_forwards
from mailbrief.features.replies import vacation_replies
from mailbrief.mail.classify import classify, demote_automated
from mailbrief.mail.imap import fetch_recent, is_gmail, mark_unanswered
from mailbrief.money.ledger import find_duplicate, item_key, parse_amount, vendor_key
from mailbrief.storage import load_json, save_json


def save_snapshot(per_account, awaiting=None, only=None):
    """per_account: [(email, items)] — what the "My day" page shows about mail, without a slow live scan.
    awaiting: conversations I started that got no answer (features.followups). None (the weekly run, which
    doesn't look for them) keeps the ones from the last hourly check, and the invitations with them.
    only: a run of one mailbox — the other mailboxes' rows stay as they were."""
    previous = load_json(config.SNAPSHOT_FILE, {})
    waiting, urgent, due, invites = [], [], [], {}
    for address, items in per_account:
        for it in items:
            row = {'account': address, 'from': it['sender_name'], 'subject': it['subject'], 'link': it.get('link', ''),
                   'message_id': it.get('message_id', '')}
            if it.get('due'):
                due.append(row | {'due': it['due'], 'amount': it.get('amount', '')})
            if it.get('invite'):
                inv = it['invite']
                invites[inv['uid'] or (inv['start'], inv['title'])] = row | inv
            if it.get('answered') is False:
                waiting.append(row | {'days': it.get('waiting_days', 0)})
            if it['unusual'] or 'urgent' in it['cats'] or 'phishing' in it['cats']:
                why = '🎣 חשד לפישינג' if 'phishing' in it['cats'] else 'חריג באבטחה' if it['unusual'] else 'דחוף'
                urgent.append(row | {'why': why, 'date': it['date']})
    data = {'at': dt.datetime.now().strftime('%d/%m %H:%M'),
                              'waiting': sorted(waiting, key=lambda w: -w['days']), 'urgent': urgent, 'due': due,
                              'invites': sorted(invites.values(), key=lambda i: i['start']) if awaiting is not None
                              else [i for i in previous.get('invites', []) if upcoming(i)],
                              'awaiting': sorted(awaiting, key=lambda w: -w['days']) if awaiting is not None
                              else previous.get('awaiting', [])}
    if only:
        for key in ('waiting', 'urgent', 'due', 'invites', 'awaiting'):
            others = [r for r in previous.get(key, []) if (r.get('account') or '').lower() != only.lower()]
            fresh = [r for r in data[key] if (r.get('account') or '').lower() == only.lower()]
            data[key] = sorted(others + fresh, key=lambda r: -r.get('days', 0)) if key in ('waiting', 'awaiting') else others + fresh
    save_json(config.SNAPSHOT_FILE, data)


def upcoming_payments(days=14):
    """Payment deadlines from the receipts ledger and from the latest check, soonest first."""
    today, seen, rows = dt.date.today(), set(), []
    sources = [{'from': r['vendor'], 'subject': r['subject'], 'link': r.get('link', ''), 'due': r['due'], 'account': r.get('account', ''),
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


def check_alerts(only=None):
    """Quick look at the last 2 days; pop a Windows notification only for new urgent / unusual / flagged mail.
    only: check just this mailbox (the others, and the daily / monthly jobs, wait for the regular hourly check)."""
    accounts = load_json(config.ACCOUNTS_FILE, [])
    state = load_json(config.STATE_FILE, {})
    rules = load_json(config.RULES_FILE, [])
    seen = set(state.get('_alerted', []))
    ledger = load_json(config.LEDGER_FILE, {})
    known_vendors = {r['vendor_key'] for r in ledger.values()}
    now = dt.datetime.now().astimezone()
    alerts = []                                  # (reason, item)
    snapshot, awaiting = [], []
    budget = [config.MAX_WORKFLOW_RUNS]                 # shared across mailboxes: at most this many automation runs per check
    for acc in [a for a in accounts if not only or a['email'].lower() == only.lower()]:
        try:
            m = imap.connect(acc)
            try:
                items, pending, pairs = [], [], []
                for uid, gid, msg in fetch_recent(m, is_gmail(acc), days=7, readonly=not workflows_need_write()):
                    it = classify(msg, acc['email'], rules)
                    it['uid'] = uid
                    it['message_id'] = (msg.get('Message-ID') or '').strip()
                    it['link'] = f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{gid:x}" if gid else ''
                    invite = find_invite(msg)
                    if invite and upcoming(invite):
                        it['invite'] = invite
                    items.append(it)
                    pairs.append((it, msg))
                    if it['forward']:
                        pending.append((it, msg))
                demote_automated(items, [a['email'] for a in accounts])
                mark_unanswered(m, items)
                run_workflows(m, acc, pairs, state, ledger, budget)
                vacation_replies(acc, pairs, state)
                try:
                    awaiting += awaiting_replies(m, acc, {a['email'].lower() for a in accounts})
                except Exception:
                    pass                                 # a slow or odd Sent folder must not stop the check
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
                ('invite', f'📅 הזמנה לפגישה — {when_text(it["invite"])}' if it.get('invite') else '', fresh and bool(it.get('invite'))),
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
        save_snapshot(snapshot, awaiting, only=only)
    if not only:
        run_schedule_workflows(state, accounts)
    from mailbrief.features.daily import maybe_send_daily        # (imports this module)
    from mailbrief.features.outbox import send_due
    from mailbrief.money.accountant import maybe_send_monthly, price_change_text, price_changes
    from mailbrief.features.snooze import wake_due
    jobs = (lambda: maybe_send_daily(state, accounts), lambda: send_due(accounts), lambda: maybe_send_monthly(state, accounts), wake_due)
    for job in (jobs if not only else ()):
        try:
            job()
        except Exception:
            pass                                 # try again next hour
    for change in price_changes(ledger):
        key = f"price|{change['key']}|{change['date']}"
        if key not in seen:
            seen.add(key)
            alerts.append(('💳 התייקרות', {'subject': price_change_text(change), 'sender_name': change['vendor'], 'link': ''}))
    state['_alerted'] = sorted(seen)[-3000:]
    save_json(config.STATE_FILE, state)
    save_json(config.ACCOUNTS_FILE, accounts)          # keep rotated refresh tokens
    if not alerts:
        return 0
    why, first = alerts[0]
    title = f'📬 MailBrief — {why}' if len(alerts) == 1 else f'📬 MailBrief — {len(alerts)} הודעות דורשות תשומת לב'
    notify.toast(title, [f'{first["subject"]} ({first["sender_name"]})'] + [f'{t}: {a["subject"]}' for t, a in alerts[1:2]],
          first.get('link') or link())
    return len(alerts)
