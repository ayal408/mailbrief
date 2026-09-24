"""Phishing signals -> a risk score with reasons."""
import re
from email.utils import parseaddr
from urllib.parse import urlparse

from mailbrief.mail.domains import FREE_MAIL
from mailbrief.mail.message import decode, html_links


BRANDS = {                                       # name that appears in the sender's display name -> its real domains
    'לאומי': ('leumi.co.il', 'isracard.co.il', 'max.co.il'), 'leumi': ('leumi.co.il',),
    'הפועלים': ('bankhapoalim.co.il', 'poalim.co.il'), 'poalim': ('bankhapoalim.co.il', 'poalim.co.il'),
    'דיסקונט': ('discountbank.co.il', 'dbank.co.il'), 'מזרחי': ('mizrahi-tefahot.co.il', 'umtb.co.il'),
    'ישראכרט': ('isracard.co.il',), 'isracard': ('isracard.co.il',), 'כאל': ('cal-online.co.il', 'icc.co.il'),
    'מקס': ('max.co.il',), 'paypal': ('paypal.com', 'paypal.co.il'), 'google': ('google.com', 'accounts.google.com', 'youtube.com'),
    'microsoft': ('microsoft.com', 'microsoftonline.com', 'outlook.com'), 'apple': ('apple.com', 'icloud.com'),
    'amazon': ('amazon.com', 'amazon.co.uk', 'amazon.de'), 'netflix': ('netflix.com',), 'facebook': ('facebookmail.com', 'meta.com', 'facebook.com'),
    'meta': ('meta.com', 'facebookmail.com', 'metamail.com'), 'דואר ישראל': ('israelpost.co.il',), 'israel post': ('israelpost.co.il',),
    'ביטוח לאומי': ('btl.gov.il',), 'רשות המסים': ('taxes.gov.il', 'gov.il'), 'dhl': ('dhl.com', 'dhl.co.il'), 'ups': ('ups.com',),
    'fedex': ('fedex.com',), 'bit': ('bit.co.il', 'bankhapoalim.co.il'), 'פייבוקס': ('payboxapp.com',), 'anthropic': ('anthropic.com',),
}


PRESSURE = re.compile(r'verify your (?:account|identity)|account (?:will be |has been )?(?:suspended|locked|closed)|confirm your (?:password|payment)|'
                      r'unusual activity|click (?:here )?(?:now|immediately)|update your (?:payment|billing)|'
                      r'אמת(?:ו)? את (?:החשבון|הפרטים)|החשבון (?:שלך )?(?:יושעה|ייחסם|ננעל)|חבילה ממתינה|דמי משלוח|עדכ(?:ן|נו) (?:את )?פרטי (?:התשלום|האשראי)|'
                      r'לחץ(?:\/י|ו)? (?:כאן )?(?:מיד|עכשיו)|זכית', re.I)


WEB_TLDS = {'com', 'net', 'org', 'io', 'ai', 'co', 'il', 'gov', 'edu', 'app', 'dev', 'me', 'info', 'biz', 'us', 'uk', 'de',
            'fr', 'ru', 'cn', 'top', 'xyz', 'site', 'online', 'store', 'shop', 'link', 'click', 'live', 'tech', 'cloud', 'page', 'ly'}


SHORTENERS = ('bit.ly', 'tinyurl.com', 'cutt.ly', 'rb.gy', 'is.gd', 't.ly', 'shorturl.at', 'ow.ly')


BAD_ATTACHMENTS = re.compile(r'\.(exe|scr|js|jse|vbs|vbe|bat|cmd|ps1|msi|iso|img|hta|lnk|html?|svg)$', re.I)


def _domain_ok(domain, allowed):
    return any(domain == a or domain.endswith('.' + a) for a in allowed)


def phishing_score(msg, sender_name, sender, text):
    score, why = 0, []
    domain = sender.rsplit('@', 1)[-1].lower()
    auth = str(msg.get('Authentication-Results') or '').lower()
    fails = [k for k in ('spf', 'dkim', 'dmarc') if re.search(rf'\b{k}=(?:fail|softfail)', auth)]
    if fails:
        score += 3 if 'dmarc' in fails or len(fails) > 1 else 2
        why.append(f'בדיקת אמינות נכשלה ({", ".join(fails).upper()})')
    name = (sender_name or '').lower()
    for brand, allowed in BRANDS.items():
        if re.search(rf'(?<![\w]){re.escape(brand)}(?![\w])', name) and not _domain_ok(domain, allowed):
            score += 3
            why.append(f'מתחזה ל„{brand}” אבל נשלח מ-{domain}')
            break
    reply_to = parseaddr(decode(msg.get('Reply-To')))[1].lower()
    if reply_to and reply_to.rsplit('@', 1)[-1] != domain and reply_to.rsplit('@', 1)[-1] in FREE_MAIL:
        score += 2
        why.append(f'תשובה מופנית לכתובת אחרת ({reply_to})')
    authenticated = 'dmarc=pass' in auth          # Gmail verified the sender: tracking redirects in its links are normal
    for href, label in html_links(msg):
        host = (urlparse(href).hostname or '').lower()
        if not host:
            continue
        shown = re.search(r'(?:https?://)?((?:[\w-]+\.)+([a-z]{2,}))\b', label.lower())
        if (shown and not authenticated and shown.group(2) in WEB_TLDS
                and not (host == shown.group(1) or host.endswith('.' + shown.group(1)) or shown.group(1).endswith('.' + host))):
            score += 2
            why.append(f'קישור מציג {shown.group(1)} אבל מוביל ל-{host}')
            break
        if re.fullmatch(r'[\d.]+', host) or host.startswith('xn--') or '.xn--' in host:
            score += 2
            why.append(f'קישור חשוד ({host})')
            break
        if host in SHORTENERS:
            score += 1
            why.append(f'קישור מקוצר ({host})')
            break
    bad = [n for n in (decode(p.get_filename()) or '' for p in msg.iter_attachments()) if BAD_ATTACHMENTS.search(n)]
    if bad:
        score += 3
        why.append(f'קובץ מצורף מסוכן ({bad[0]})')
    else:
        from mailbrief.features.security import attachment_risks     # macros, programs inside a ZIP, locked archives
        risks = attachment_risks(msg)
        if risks:                                 # a macro or a program inside a ZIP is enough on its own; a locked ZIP is only a hint
            score += 2 if all('נעול בסיסמה' in r for r in risks) else 4
            why += risks
    pressure = PRESSURE.findall(f'{decode(msg.get("Subject"))} {text[:3000]}')
    if pressure:
        score += min(2, len(pressure))
        why.append('לחץ / בקשה לפרטים („' + pressure[0][:30] + '”)')
    return score, why
