"""Sending: as the account itself, forwarded messages and replies."""
import base64
import re
import smtplib
from email.message import EmailMessage
from email.utils import formatdate
from email.utils import make_msgid
from email.utils import getaddresses, parseaddr

from mailbrief.mail.message import _part_text, body_text, decode
from mailbrief.mail.oauth import access_token, PROVIDERS
from mailbrief.net import TLS
from mailbrief.storage import decrypt
from mailbrief.util import e


class PartialDelivery(RuntimeError):
    """Some recipients were accepted; retrying the whole message would duplicate delivery."""
    def __init__(self, refused, recipients):
        self.refused = {addr: {'code': code, 'message': (text.decode('utf-8', 'replace') if isinstance(text, bytes) else str(text))}
                        for addr, (code, text) in refused.items()}
        self.accepted = [addr for addr in recipients if addr not in refused]
        super().__init__('נשלח רק לחלק מהנמענים. נדחו: ' + ', '.join(self.refused))


class DeliveryUncertain(RuntimeError):
    """The connection broke during submission; the server may already have accepted the message."""


def build_reply(original, acc, text, auto):
    name, addr = parseaddr(decode(original.get('Reply-To') or original.get('From')))
    subject = decode(original.get('Subject')) or ''
    reply = EmailMessage()
    reply['From'] = acc['email']
    reply['To'] = addr
    reply['Subject'] = subject if re.match(r'(?i)^re\s*:', subject) else f'Re: {subject}'
    reply['Date'] = formatdate(localtime=True)
    reply['Message-ID'] = make_msgid(domain=acc['email'].rsplit('@', 1)[-1])
    reply['X-MailBrief-Auto'] = '1'
    if original.get('Message-ID'):
        reply['In-Reply-To'] = original['Message-ID']
        reply['References'] = f"{original.get('References', '')} {original['Message-ID']}".strip()
    if auto:
        reply['Auto-Submitted'] = 'auto-replied'       # RFC 3834 — other robots won't answer back
    reply.set_content(text)
    reply.add_alternative(f'<div dir="rtl" style="font-family:Arial">{e(text).replace(chr(10), "<br>")}</div>', subtype='html')
    return reply


def send_mail(acc, message):
    """Send as the account itself: Google / Microsoft via XOAUTH2, other providers via their SMTP + password."""
    auth = acc.get('auth')
    if auth == 'microsoft':
        server = smtplib.SMTP('smtp.office365.com', 587, timeout=60)
        server.starttls(context=TLS)
    else:
        host = 'smtp.gmail.com' if auth == 'google' else (acc.get('smtp_host') or re.sub(r'^imap\.', 'smtp.', acc['host']))
        server = smtplib.SMTP_SSL(host, 465, timeout=60, context=TLS)
    try:
        server.ehlo()
        if auth in PROVIDERS:
            blob = base64.b64encode(f"user={acc['user']}\x01auth=Bearer {access_token(acc)}\x01\x01".encode()).decode()
            code, resp = server.docmd('AUTH', 'XOAUTH2 ' + blob)
            if code != 235:
                raise RuntimeError(f'השרת דחה את השליחה ({code}) — ייתכן שצריך להתחבר מחדש לתיבה')
        else:
            server.login(acc['user'], decrypt(acc['password']))
        recipients = [addr for _, addr in getaddresses(message.get_all('To', []) + message.get_all('Cc', []) + message.get_all('Bcc', []))]
        try:
            refused = server.send_message(message)
        except smtplib.SMTPServerDisconnected as exc:
            raise DeliveryUncertain('החיבור נותק בזמן שליחה — יש לבדוק בדואר שנשלח לפני שליחה נוספת') from exc
        except smtplib.SMTPException:
            raise
        except OSError as exc:
            raise DeliveryUncertain('החיבור נותק בזמן שליחה — יש לבדוק בדואר שנשלח לפני שליחה נוספת') from exc
        if refused:
            raise PartialDelivery(refused, recipients)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def build_forward(original, acc, to):
    subject = decode(original.get('Subject')) or '(ללא נושא)'
    fwd = EmailMessage()
    fwd['From'] = acc['email']
    fwd['To'] = to
    fwd['Subject'] = subject if re.match(r'(?i)^(fwd?|הועבר)\s*:', subject) else f'Fwd: {subject}'
    fwd['Date'] = formatdate(localtime=True)
    fwd['Message-ID'] = make_msgid(domain=acc['email'].rsplit('@', 1)[-1])
    fwd['X-MailBrief-Forwarded'] = '1'
    header = (f'---------- הודעה שהועברה (MailBrief) ----------\nמאת: {decode(original.get("From"))}\n'
              f'תאריך: {original.get("Date", "")}\nנושא: {subject}\nאל: {decode(original.get("To"))}\n\n')
    plain = _part_text(original.get_body(preferencelist=('plain',))) or body_text(original)
    fwd.set_content(header + plain)
    html_part = original.get_body(preferencelist=('html',))
    if html_part is not None:
        try:
            fwd.add_alternative(f'<div dir="rtl" style="font-family:Arial;color:#555">{e(header).replace(chr(10), "<br>")}</div><hr>'
                                + html_part.get_content(), subtype='html')
        except Exception:
            pass
    for part in original.iter_attachments():
        data = part.get_payload(decode=True)
        if data:
            maintype, _, subtype = part.get_content_type().partition('/')
            fwd.add_attachment(data, maintype=maintype, subtype=subtype or 'octet-stream',
                               filename=decode(part.get_filename()) or 'attachment')
    return fwd
