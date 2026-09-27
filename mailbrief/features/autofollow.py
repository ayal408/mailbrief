"""⏰ Automatic follow-up: "no answer within 3 days? send a polite reminder". Set when writing a scheduled email; after
it goes out, MailBrief checks for a reply when the days pass — a reply cancels it, otherwise the reminder goes out in
the same thread (through the outbox, so never on Shabbat / Yom Tov)."""
import datetime as dt
import secrets

from mailbrief import config
from mailbrief.storage import load_json, save_json


DEFAULT_TEXT = 'שלום{first},\n\nרציתי לוודא שההודעה הקודמת שלי הגיעה אלייך — אשמח לתשובה כשיתאפשר.\n\nתודה!'


def items():
    return load_json(config.AUTOFOLLOW_FILE, [])


def register(sent_item, now=None):
    """Called right after a scheduled email with a follow-up went out."""
    now = now or dt.datetime.now().astimezone()
    f = sent_item.get('follow') or {}
    if not f.get('days') or not sent_item.get('message_id'):
        return None
    row = {'id': secrets.token_hex(4), 'account': sent_item['account'], 'to': sent_item['to'], 'subject': sent_item['subject'],
           'message_id': sent_item['message_id'], 'sent': now.isoformat(timespec='minutes'),
           'due': (now + dt.timedelta(days=int(f['days']))).isoformat(timespec='minutes'),
           'text': f.get('text') or DEFAULT_TEXT.replace('{first}', ''), 'status': 'waiting'}
    save_json(config.AUTOFOLLOW_FILE, items() + [row])
    return row


def cancel(row_id):
    rows = items()
    for r in rows:
        if r['id'] == row_id and r['status'] == 'waiting':
            r['status'] = 'cancelled'
    save_json(config.AUTOFOLLOW_FILE, rows)


def check_due(now=None, accounts=None):
    """For every follow-up whose day came: a reply? -> done. None -> the reminder is queued. Returns how many were queued."""
    from mailbrief import net
    from mailbrief.features import outbox
    from mailbrief.features.followups import replied
    from mailbrief.mail import imap
    from mailbrief.mail.imap import special_folder
    now = now or dt.datetime.now().astimezone()
    rows = items()
    due = [r for r in rows if r['status'] == 'waiting' and dt.datetime.fromisoformat(r['due']) <= now]
    if not due or not net.online():
        return 0
    accounts = load_json(config.ACCOUNTS_FILE, []) if accounts is None else accounts
    queued = 0
    for acc_email in {r['account'] for r in due}:
        acc = next((a for a in accounts if a['email'].lower() == acc_email.lower()), None)
        mine = [r for r in due if r['account'] == acc_email]
        if not acc:
            for r in mine:
                r['status'] = 'cancelled'
            continue
        try:
            m = imap.connect(acc)
        except Exception:
            continue                                         # try again next round
        try:
            m.select(f'"{special_folder(m, chr(92) + "All") or "INBOX"}"', readonly=True)
            for r in mine:
                if replied(m, r['message_id']):
                    r['status'] = 'answered'
                    continue
                subject = r['subject'] if r['subject'].lower().startswith(('re:', 'השב:')) else f'Re: {r["subject"]}'
                outbox.schedule(r['account'], ', '.join(r['to']) if isinstance(r['to'], list) else r['to'], subject, r['text'],
                                outbox.out_of_holy(now), thread={'in_reply_to': r['message_id'], 'references': r['message_id']})
                r['status'], r['followed'] = 'sent', now.isoformat(timespec='minutes')
                queued += 1
        finally:
            try:
                m.logout()
            except Exception:
                pass
    save_json(config.AUTOFOLLOW_FILE, rows[-300:])
    return queued
