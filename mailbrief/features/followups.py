"""Conversations I started that nobody answered yet ("waiting on them")."""
import datetime as dt
import email.utils
from urllib.parse import quote

from mailbrief import config
from mailbrief.mail.imap import fetch_recent, is_gmail, special_folder
from mailbrief.mail.message import decode


MAX_CHECKED = 40        # sent messages looked up per mailbox per check


def replied(m, message_id):
    mid = message_id.replace('"', '')
    typ, data = m.uid('SEARCH', None, 'OR', 'HEADER', 'In-Reply-To', f'"{mid}"', 'HEADER', 'References', f'"{mid}"')
    return bool(typ == 'OK' and data and data[0].strip())


def awaiting_replies(m, acc, own, min_days=None, max_days=14):
    """Messages I sent to people min_days..max_days ago with no reply in the mailbox, oldest wait first."""
    min_days = config.FOLLOWUP_DAYS if min_days is None else min_days
    sent = special_folder(m, r'\Sent')
    if not sent:
        return []
    gmail = is_gmail(acc)
    now = dt.datetime.now().astimezone()
    candidates = []
    for _, gid, msg in fetch_recent(m, gmail, days=max_days, readonly=True, folder=sent, headers_only=True, limit=200):
        if msg.get('X-MailBrief-Forwarded') or msg.get('X-MailBrief-Auto') or msg.get('Auto-Submitted'):
            continue
        if msg.get('In-Reply-To'):
            continue                                 # an answer I gave — only conversations I started wait for "them"
        to = [a.lower() for _, a in email.utils.getaddresses([str(msg.get('To', '')), str(msg.get('Cc', ''))]) if a]
        people = [a for a in to if a not in own and not a.split('@')[0].startswith(('noreply', 'no-reply', 'donotreply'))]
        message_id = (msg.get('Message-ID') or '').strip()
        try:
            when = email.utils.parsedate_to_datetime(msg['Date']).astimezone()
        except Exception:
            continue
        days = (now - when).days
        if not people or not message_id or days < min_days:
            continue
        name = email.utils.getaddresses([str(msg.get('To', ''))])
        candidates.append({'account': acc['email'], 'to': (name[0][0] or name[0][1]) if name else people[0],
                           'to_email': people[0], 'subject': decode(msg.get('Subject')) or '(בלי נושא)', 'days': days,
                           'message_id': message_id, 'sent': when.isoformat(),
                           'link': f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{gid:x}" if gid else ''})
    candidates = sorted(candidates, key=lambda c: c['sent'], reverse=True)[:MAX_CHECKED]
    everywhere = special_folder(m, r'\All') if gmail else 'INBOX'   # Gmail: replies may be archived
    if not everywhere:
        return []
    m.select(f'"{everywhere}"', readonly=True)
    waiting, answered_threads = [], set()
    for c in candidates:
        key = (c['to_email'], c['subject'].lower().removeprefix('re: ').removeprefix('fwd: '))
        if key in answered_threads or replied(m, c['message_id']):
            answered_threads.add(key)                # a later follow-up in the same thread got an answer
            continue
        if key not in {(w['to_email'], w['subject'].lower().removeprefix('re: ').removeprefix('fwd: ')) for w in waiting}:
            waiting.append(c)
    return sorted(waiting, key=lambda w: -w['days'])
