"""Reply templates, one-click drafts and vacation mode."""
import datetime as dt
import email
import imaplib
from email.policy import default as default_policy
from urllib.parse import quote

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.mail import smtp
from mailbrief.features.automations import fill, wf_context
from mailbrief.mail.classify import classify, is_bulk, RX
from mailbrief.mail.imap import is_gmail, special_folder
from mailbrief.mail.smtp import build_reply
from mailbrief.storage import load_json, save_json


DEFAULT_TEMPLATES = [
    {'id': 't1', 'name': 'קיבלתי, אחזור בהקדם', 'text': 'שלום {from_name},\nקיבלתי את ההודעה ואחזור בהקדם.\nתודה!'},
    {'id': 't2', 'name': 'בקשת חשבונית', 'text': 'שלום {from_name},\nאשמח לקבל חשבונית מס / קבלה על התשלום.\nתודה רבה!'},
    {'id': 't3', 'name': 'תזכורת תשלום', 'text': 'שלום {from_name},\nרציתי להזכיר בעדינות לגבי התשלום שעדיין פתוח.\nאשמח לעדכון, תודה!'},
]


VACATION_DEFAULT = 'שלום {from_name},\nתודה על הפנייה. אני מחוץ למשרד עד {to} ואחזור בהקדם אחרי כן.\n\nבברכה'


def reply_templates():
    return load_json(config.SETTINGS_FILE, {}).get('templates') or DEFAULT_TEMPLATES


def _original(m, message_id):
    m.select(f'"{special_folder(m, chr(92) + "All") or "INBOX"}"', readonly=True)
    typ, data = m.uid('SEARCH', None, 'HEADER', 'Message-ID', f'"{message_id.replace(chr(34), "")}"')
    uids = data[0].split() if typ == 'OK' and data[0] else []
    if not uids:
        raise RuntimeError('ההודעה לא נמצאה בתיבה')
    typ, rows = m.uid('FETCH', uids[-1], '(BODY.PEEK[])')
    return email.message_from_bytes(rows[0][1], policy=default_policy)


def reply_now(account, message_id, text, attachments=()):
    """Answers an email right away from MailBrief (quick sorting). Gmail keeps the reply in "Sent" by itself."""
    accounts = load_json(config.ACCOUNTS_FILE, [])
    acc = next((a for a in accounts if a['email'] == account), None)
    if not acc or not message_id or not text.strip():
        raise RuntimeError('חסר נוסח או הודעה')
    m = imap.connect(acc)
    try:
        msg = _original(m, message_id)
    finally:
        m.logout()
    reply = build_reply(msg, acc, fill(text, wf_context(acc, classify(msg, acc['email']))), auto=False)
    del reply['X-MailBrief-Auto']                     # a person answered: it may still wait for their reply
    for name, data in attachments:
        reply.add_attachment(data, maintype='application', subtype='octet-stream', filename=name)
    smtp.send_mail(acc, reply)
    save_json(config.ACCOUNTS_FILE, accounts)
    return reply['To']


def reply_details(account, message_id):
    """To, subject and threading headers of a reply — to schedule it for later."""
    accounts = load_json(config.ACCOUNTS_FILE, [])
    acc = next((a for a in accounts if a['email'] == account), None)
    if not acc:
        raise RuntimeError('התיבה לא נמצאה')
    m = imap.connect(acc)
    try:
        msg = _original(m, message_id)
    finally:
        m.logout()
    shell = build_reply(msg, acc, '', auto=False)
    return {'to': shell['To'], 'subject': shell['Subject'], 'in_reply_to': shell.get('In-Reply-To', ''),
            'references': shell.get('References', '')}


def create_draft_reply(account, message_id, text):
    """Find the original email by Message-ID and put a reply draft in the account's Drafts folder."""
    accounts = load_json(config.ACCOUNTS_FILE, [])
    acc = next((a for a in accounts if a['email'] == account), None)
    if not acc or not message_id:
        raise RuntimeError('ההודעה לא נמצאה')
    m = imap.connect(acc)
    try:
        msg = _original(m, message_id)
        ctx = wf_context(acc, classify(msg, acc['email']))
        drafts = special_folder(m, r'\Drafts')
        if not drafts:
            raise RuntimeError('לא נמצאה תיקיית טיוטות')
        m.append(f'"{drafts}"', r'(\Draft)', imaplib.Time2Internaldate(dt.datetime.now().timestamp()),
                 build_reply(msg, acc, fill(text, ctx), auto=False).as_bytes())
    finally:
        m.logout()
        save_json(config.ACCOUNTS_FILE, accounts)
    return f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#drafts" if is_gmail(acc) else ''


def vacation_active():
    v = load_json(config.SETTINGS_FILE, {}).get('vacation') or {}
    today = dt.date.today().isoformat()
    return v if v.get('from') and v.get('to') and v['from'] <= today <= v['to'] else None


def vacation_replies(acc, pairs, state):
    """Out-of-office: one reply per real person per vacation. Same protections as automatic replies."""
    vac = vacation_active()
    if not vac:
        return 0
    start = dt.datetime.fromisoformat(vac['from']).astimezone()
    own = {a['email'].lower() for a in load_json(config.ACCOUNTS_FILE, [])}
    done = set(state.get('_vacation', []))
    today = dt.date.today().isoformat()
    count_today = state.setdefault('_vacation_budget', {}).get(today, 0)
    sent = 0
    for it, msg in pairs:
        sender = it['sender'].lower()
        key = f"{vac['from']}|{sender}"
        if ('people' not in it['cats'] or key in done or sender in own or not sender or is_bulk(msg)
                or RX['robot_sender'].search(sender) or dt.datetime.fromisoformat(it['iso']) < start
                or msg.get('X-MailBrief-Auto') or count_today + sent >= config.MAX_VACATION_REPLIES):
            continue
        back = dt.date.fromisoformat(vac['to']) + dt.timedelta(days=1)
        text = fill(vac.get('message') or VACATION_DEFAULT, wf_context(acc, it) | {'to': f'{back:%d/%m}'})
        try:
            smtp.send_mail(acc, build_reply(msg, acc, text, auto=True))
            done.add(key)
            sent += 1
        except Exception:
            continue
    state['_vacation'] = sorted(done)[-3000:]
    state['_vacation_budget'] = {today: count_today + sent}
    return sent
