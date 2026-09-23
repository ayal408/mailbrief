"""Plain rules (no AI) that sort an email into categories, amounts and due dates."""
import datetime as dt
import re
from email.utils import parseaddr
from email.utils import parsedate_to_datetime

from mailbrief.mail.domains import FREE_MAIL
from mailbrief.mail.message import body_text, decode
from mailbrief.mail.phishing import phishing_score


CATS = {
    'urgent':     ('🔥', 'דחוף'),
    'people':     ('👤', 'מאנשים'),
    'receipts':   ('🧾', 'קבלות'),
    'security':   ('🔐', 'אבטחה'),
    'signins':    ('🔑', 'התחברויות'),
    'newsletters': ('📰', 'ניוזלטרים'),
    'phishing':   ('🎣', 'חשד לפישינג'),
}


TAG_PREFIX = 'אוטומטי'


TAGGED = ('receipts', 'security', 'signins', 'newsletters', 'phishing')


PHISH_THRESHOLD = 4


RX = {k: re.compile(v, re.I) for k, v in {
    'signins': r'מסרת לאפליקציה|נתת לאפליקציה|sign in with google|signed in (?:to|with)|access to (?:some of )?your google account|new app connected|granted access',
    'security': r'security alert|התראת אבטחה|new sign-?in|כניסה חדשה|verification code|קוד (?:אימות|אישור)|one-time (?:code|password)|password|סיסמ|2-step|two-factor|דו-שלבי|passkey|מפתח גישה|recovery|שחזור|suspicious|חשוד|login attempt|confirm your email|אשר(?:ו)? את (?:כתובת )?הדוא',
    'unusual': r'recovery (?:phone|email|number)|(?:טלפון|מספר|כתובת) (?:ה)?(?:אימייל )?לשחזור|שוחזר|passkey (?:was )?(?:removed|deleted)|הוסר מפתח גישה|מפתח גישה הוסר|password (?:was )?(?:changed|reset)|הסיסמה (?:שלך )?שונתה|suspicious|חשוד|blocked (?:a )?sign-?in|ניסיון כניסה נחסם',
    'receipts': r'receipt|invoice|חשבונית|קבלה|payment (?:received|confirmation|successful|failed)|אישור (?:תשלום|הזמנה)|order (?:confirmation|#)|your order|subscription (?:renewed|canceled|cancelled|confirmed)|billing|חיוב|הוראת קבע|renewal',
    'receipt_sender': r'invoice|billing|receipt|payments?@|statements',
    'urgent': r'expire|expiring|ends in|trial ends|final notice|last chance to keep|overdue|due (?:date|on|by)|payment failed|action required|פג תוקף|יפוג|יפקע|מסתיים|תזכורת אחרונה|לתשלום עד|נכשל|דחוף|immediately',
    'newsletter_sender': r'substack\.com|newsletter|news@|marketing|mailchimp|hubspot|campaign|digest',
    'subscription': r'subscription|מנוי|renew|monthly|חודשי|recurring|הוראת קבע|\bplan\b',
    'robot_sender': r'no-?reply|do-?not-?reply|notifications?@|mailer|bounce|alerts?@|info@|support@|team@|hello@|updates?@|admin@|jobs?@|system@|service@|tashlumim@|payments?@|billing@|invoices?@|accounts?@|security@',
}.items()}


AMOUNT = re.compile(
    r'(?P<c1>₪|ILS|NIS|\$|USD|€|EUR)\s?(?P<a1>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)'
    r'|(?P<a2>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s?(?P<c2>₪|ש"ח|ש״ח|ILS|NIS|USD|EUR|€)')


CURRENCY = {'₪': '₪', 'ILS': '₪', 'NIS': '₪', 'ש"ח': '₪', 'ש״ח': '₪', '$': '$', 'USD': '$', '€': '€', 'EUR': '€'}


BOOK_CATS = [
    ('רכב', r'דלק|תדלוק|fuel|פז|סונול|דור ?אלון|\bten\b|parking|חניה|חניון|כביש 6|מוסך|garage|רישיון רכב|car insurance|ביטוח רכב'),
    ('תוכנה ומנויים', r'subscription|מנוי|anthropic|openai|claude|chatgpt|github|google|adobe|microsoft|apple|dropbox|canva|domain|דומיין|hosting|אחסון|cloud|ענן|saas|license|רישיון|zoom|notion|figma|lovable|base44'),
    ('משרד ואחזקה', r'חשמל|electric|ארנונה|\brent\b|שכירות|שכר דירה|בזק|bezeq|internet|אינטרנט|סלולר|cellular|\bpartner\b|cellcom|\bhot\b|\byes\b|water|חשבון מים|ניקיון|cleaning'),
    ('רכוש קבוע', r'laptop|מחשב נייד|monitor|מסך|printer|מדפסת|chair|כיסא|desk|שולחן'),
]


DUE_RX = re.compile(
    r'(?:לתשלום\s+(?:עד|ב)(?:\s*ה?-?)?|יש\s+לשלם\s+עד|מועד\s+(?:ה)?(?:תשלום|פירעון)|תאריך\s+(?:ה)?(?:תשלום|פירעון)(?:\s+האחרון)?|'
    r'payment\s+(?:is\s+)?due(?:\s+(?:on|by|date))?|due\s+(?:date|on|by)|pay\s+by)[\s:–-]*'
    r'(?P<date>\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|[A-Z][a-z]{2,8}\.? \d{1,2},? \d{4}|\d{1,2} [A-Z][a-z]{2,8}\.? \d{4})', re.I)


MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}


def find_due_date(text):
    """A payment deadline written in the email ("לתשלום עד 15/10/2026", "Payment due Oct 15, 2026")."""
    found = DUE_RX.search(text or '')
    if not found:
        return ''
    raw = found.group('date')
    try:
        if raw[0].isdigit() and not re.search(r'[A-Za-z]', raw):
            d, m, y = (int(x) for x in re.split(r'[./-]', raw))       # Israeli order: day / month / year
            day = dt.date(y + 2000 if y < 100 else y, m, d)
        else:
            words = re.findall(r'[A-Za-z]+|\d+', raw)
            month = MONTHS[next(w for w in words if w.isalpha())[:3].lower()]
            nums = [int(w) for w in words if w.isdigit()]
            day = dt.date(max(nums), month, min(nums))
    except (ValueError, KeyError, StopIteration):
        return ''
    today = dt.date.today()
    return day.isoformat() if today - dt.timedelta(days=60) <= day <= today + dt.timedelta(days=365) else ''


def is_bulk(msg):
    """Mailing lists, marketing platforms and auto-replies — never mail that needs an answer."""
    if msg.get('List-Unsubscribe') or msg.get('List-Id') or msg.get('Feedback-ID') or msg.get('X-Campaign'):
        return True
    if str(msg.get('Precedence') or '').strip().lower() in ('bulk', 'list', 'junk'):
        return True
    if str(msg.get('Auto-Submitted') or 'no').strip().lower() != 'no':
        return True
    local = parseaddr(str(msg.get('Return-Path') or ''))[1].lower().split('@')[0]
    return bool(local) and ('bounce' in local or '=' in local or re.match(r'^[0-9a-f]{16,}', local) is not None)


def demote_automated(items, own_addresses):
    """Second pass over "people": drop mail between the owner's own mailboxes, and treat a company address
    that sent 3+ messages this week as automated (job alerts, notifications...)."""
    own = {a.lower() for a in own_addresses}
    counts = {}
    for it in items:
        if 'people' in it['cats'] and it['sender'].rsplit('@', 1)[-1].lower() not in FREE_MAIL:
            counts[it['sender'].lower()] = counts.get(it['sender'].lower(), 0) + 1
    for it in items:
        if 'people' not in it['cats']:
            continue
        sender = it['sender'].lower()
        if sender in own:
            it['cats'] = [c for c in it['cats'] if c != 'people']
        elif counts.get(sender, 0) >= 3:
            it['cats'] = sorted({c for c in it['cats'] if c != 'people'} | {'newsletters'})


def classify(msg, own_address, rules=()):
    sender_name, sender = parseaddr(decode(msg.get('From')))
    subject = decode(msg.get('Subject')) or '(ללא נושא)'
    text = body_text(msg)
    head = f'{subject} {text[:1500]}'
    sender_l = sender.lower()
    cats = set()

    if RX['signins'].search(head):
        cats.add('signins')
    elif RX['security'].search(subject) or (RX['robot_sender'].search(sender_l) and RX['security'].search(text[:600])):
        cats.add('security')
    if RX['receipts'].search(subject) or RX['receipt_sender'].search(sender_l):
        cats.add('receipts')
    bulk = is_bulk(msg)
    auto_reply = str(msg.get('Auto-Submitted') or 'no').strip().lower() != 'no'
    if not cats & {'receipts', 'security', 'signins'} and not auto_reply and (
            bulk or RX['newsletter_sender'].search(sender_l)):
        cats.add('newsletters')
    if RX['urgent'].search(head) and 'newsletters' not in cats:
        cats.add('urgent')
    if not cats and not bulk and sender_l != own_address.lower() and not RX['robot_sender'].search(sender_l):
        cats.add('people')
    phish, phish_why = phishing_score(msg, sender_name, sender, text)
    if phish >= PHISH_THRESHOLD:                 # never suggest answering / paying a likely phish
        cats = (cats - {'people', 'urgent'}) | {'phishing'}

    item = {
        'subject': subject,
        'sender': sender,
        'sender_name': sender_name or sender,
        'snippet': text[:220],
        'body': text[:5000],
        'attachments': [decode(p.get_filename()) or '' for p in msg.iter_attachments()],
        'phish': phish, 'phish_why': phish_why,
        'cats': sorted(cats),
        'unusual': 'security' in cats and bool(RX['unusual'].search(head)),
    }
    try:
        when = parsedate_to_datetime(msg.get('Date')).astimezone()
        item['date'], item['iso'] = when.strftime('%d/%m %H:%M'), when.isoformat()
    except Exception:
        item['date'], item['iso'] = '', dt.datetime.now().astimezone().isoformat()
    if 'receipts' in cats:
        found = AMOUNT.search(f'{subject} {text[:4000]}')
        if found:
            cur = found.group('c1') or found.group('c2')
            item['amount'] = f"{CURRENCY.get(cur, cur)}{found.group('a1') or found.group('a2')}"
        blob = f'{sender} {subject} {text[:1500]}'
        item['book'] = next((name for name, rx in BOOK_CATS if re.search(rx, blob, re.I)), 'אחר')
    due = find_due_date(f'{subject} {text[:6000]}')
    if due:
        item['due'] = due

    # Official unsubscribe (RFC 2369), one-click when the sender supports RFC 8058
    lu = str(msg.get('List-Unsubscribe') or '')
    web = re.search(r'<(https://[^>\s]+)>', lu)
    mailto = re.search(r'<(mailto:[^>\s]+)>', lu)
    if web or mailto:
        item['unsub'] = {'url': web.group(1) if web else '', 'mailto': mailto.group(1) if mailto else '',
                         'one_click': bool(web) and 'one-click' in str(msg.get('List-Unsubscribe-Post') or '').lower()}

    # The user's own rules: plain "contains" matching
    fields = {'from': f'{sender_name} {sender}'.lower(), 'subject': subject.lower()}
    fields['any'] = f"{fields['from']} {head.lower()}"
    hits = [r for r in rules if r.get('contains') and r['contains'].lower() in fields.get(r.get('field'), fields['any'])]
    item['rules'] = sorted({r['label'] for r in hits})
    item['notify'] = any(r.get('notify') for r in hits)
    item['forward'] = [(r['forward_to'], r.get('created', '')) for r in hits if r.get('forward_to')]
    return item
