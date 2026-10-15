"""Scheduled sending: write now, send later — "after Shabbat", "Sunday morning", or any time. Nothing is ever sent
during Shabbat / Yom Tov: a time that falls inside one moves to its end."""
import datetime as dt
import mimetypes
import os
import re
import secrets
import shutil
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid

from mailbrief import config, net
from mailbrief.features.calendar import holy_windows, is_holy_time
from mailbrief.mail import smtp
from mailbrief.storage import file_lock, locked, load_json, save_json
from mailbrief.util import e, safe_name


AFTER_HAVDALAH = dt.timedelta(minutes=20)
MAX_PER_RUN = 25              # per round (every few minutes while MailBrief runs) — gentle on Gmail's sending limits
EMAIL = re.compile(r'[^@\s<>",;]+@[^@\s<>",;]+\.[^@\s<>",;]+')


def _now():
    return dt.datetime.now().astimezone()


def outbox():
    return load_json(config.OUTBOX_FILE, [])


def out_of_holy(when, windows=None):
    """A moment inside Shabbat / Yom Tov moves to its end (+20 minutes)."""
    for start, end in (holy_windows() if windows is None else windows) or []:
        if start <= when < end + AFTER_HAVDALAH:
            return end + AFTER_HAVDALAH
    return when


def when_for(choice, custom='', now=None, windows=None):
    now = now or _now()
    windows = holy_windows() if windows is None else windows
    if choice == 'after_holy':
        upcoming = [w for w in (windows or []) if w[1] > now]
        if upcoming:
            return upcoming[0][1] + AFTER_HAVDALAH
        days = (5 - now.weekday()) % 7                  # no calendar: Saturday 20:30
        return (now + dt.timedelta(days=days)).replace(hour=20, minute=30, second=0, microsecond=0)
    if choice == 'sunday8':
        days = (6 - now.weekday()) % 7 or 7
        return out_of_holy((now + dt.timedelta(days=days)).replace(hour=8, minute=0, second=0, microsecond=0), windows)
    if choice == 'tomorrow8':
        return out_of_holy((now + dt.timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0), windows)
    moment = dt.datetime.fromisoformat(custom)
    moment = moment.astimezone() if moment.tzinfo is None else moment
    if moment <= now:
        raise ValueError('הזמן שנבחר כבר עבר')
    return out_of_holy(moment, windows)


def addresses(text):
    text = text or ''
    if '<' in text or '"' in text:
        return [addr.strip() for _, addr in getaddresses([text.replace(';', ',')]) if addr.strip()]
    return [a.strip() for a in re.split(r'[,;\s]+', text) if a.strip()]


@locked(lambda: config.OUTBOX_FILE)
def schedule(account, to, subject, body, send_at, files=(), thread=None, follow=None, cc='', bcc='', quote=None, forward=None,
             draft=None, html=''):
    """quote: {'text', 'html'} of the message answered / forwarded; forward: {account, folder, uid} — its files go along;
    draft: {folder, uid} — the draft this mail was written in, removed once it is sent."""
    to, cc, bcc = addresses(to), addresses(cc), addresses(bcc)
    if not to and not cc and not bcc:
        raise ValueError('צריך לכתוב לפחות נמען אחד')
    bad = [a for a in to + cc + bcc if not EMAIL.fullmatch(a)]
    if bad:
        raise ValueError(f'הכתובת ״{bad[0]}״ לא נראית תקינה')
    if not subject.strip() and not body.strip():
        raise ValueError('המייל ריק')
    item = {'id': secrets.token_hex(4), 'account': account, 'to': to, 'subject': subject.strip()[:300], 'body': body[:50000],
            'send_at': send_at.isoformat(), 'created': _now().isoformat(timespec='minutes'), 'status': 'waiting'}
    if thread:
        item['thread'] = {k: thread.get(k, '') for k in ('in_reply_to', 'references')}
    for key, value in (('cc', cc), ('bcc', bcc)):
        if value:
            item[key] = value
    if quote and (quote.get('text') or quote.get('html')):
        item['quote'] = {'text': (quote.get('text') or '')[:200000], 'html': (quote.get('html') or '')[:1000000]}
    if forward:
        item['forward'] = {k: forward[k] for k in ('account', 'folder', 'uid')}
    if draft:
        item['draft'] = {k: draft[k] for k in ('folder', 'uid')}
        item['draft']['account'] = draft.get('account') or account
    if html.strip():                                   # ✍️ written with bold / colours / lists in the inbox editor
        item['html'] = rich_html(html)
    if follow and follow.get('days'):                  # ⏰ "no answer within N days -> a polite reminder"
        item['follow'] = {'days': int(follow['days']), 'text': (follow.get('text') or '').strip()[:3000]}
    if files:
        folder = os.path.join(config.DATA, 'outbox-files', item['id'])
        os.makedirs(folder, exist_ok=True)
        item['files'] = []
        for name, data in files:
            name = safe_name(name) or 'file'
            with open(os.path.join(folder, name), 'wb') as f:
                f.write(data)
            item['files'].append(name)
    save_json(config.OUTBOX_FILE, outbox() + [item])
    return item


@locked(lambda: config.OUTBOX_FILE)
def cancel(item_id):
    items = outbox()
    for it in items:
        if it['id'] == item_id:
            if it['status'] != 'waiting':
                raise ValueError('המייל כבר בתהליך שליחה, נשלח או בוטל')
            it['status'] = 'cancelled'
    save_json(config.OUTBOX_FILE, items)


@locked(lambda: config.OUTBOX_FILE)
def update(item_id, to=None, subject=None, body=None, send_at=None):
    """Change a mail that still waits: recipients, subject, text or time (a Shabbat/Yom Tov time moves to its end)."""
    items = outbox()
    it = next((m for m in items if m['id'] == item_id and m['status'] == 'waiting'), None)
    if not it:
        raise ValueError('המייל כבר נשלח או בוטל')
    if to is not None:
        to = addresses(to)
        if not to or not all(EMAIL.fullmatch(a) for a in to):
            raise ValueError('כתובת הנמען לא נראית תקינה')
        it['to'] = to
    if subject is not None:
        it['subject'] = subject.strip()[:300]
    if body is not None:
        it['body'] = body[:50000]
        it.pop('html', None)  # the queue editor supplies plain text; discard the previous rich version
    if send_at is not None:
        it['send_at'] = out_of_holy(send_at).isoformat()
    it.pop('retry', None)
    save_json(config.OUTBOX_FILE, items)
    return it


def with_signature(body, acc):
    """The mailbox's own signature at the end — unless the text already has it."""
    sig = (acc.get('signature') or '').strip()
    if not sig or sig in body:
        return body
    return body.rstrip() + '\n\n-- \n' + sig


LOGO_CID = 'mailbrief-logo'


def logo_path(acc):
    import re as _re
    return os.path.join(config.DATA, 'signatures', f"{_re.sub(r'[^0-9a-f]', '', acc.get('id', ''))[:16] or 'x'}.img")


def signature_html(acc):
    """🖼️ The signature as HTML: the text, the business logo and the links (website, WhatsApp). (html, (bytes, subtype) or None)."""
    sig = (acc.get('signature') or '').strip()
    links = acc.get('signature_links') or {}
    logo = None
    path = logo_path(acc)
    if acc.get('signature_logo') and os.path.isfile(path):
        with open(path, 'rb') as f:
            logo = (f.read(), acc['signature_logo'])
    if not (sig or logo or links.get('site') or links.get('whatsapp')):
        return '', None
    parts = []
    if logo:
        parts.append(f'<img src="cid:{LOGO_CID}" alt="" style="max-height:60px;max-width:180px;display:block;margin-bottom:6px">')
    if sig:
        parts.append(f'<div style="white-space:pre-wrap">{e(sig)}</div>')
    row = []
    if links.get('site'):
        row.append(f'<a href="{e(links["site"])}" style="color:#7c3aed">{e(links["site"].split("//")[-1].rstrip("/"))}</a>')
    if links.get('whatsapp'):
        row.append(f'<a href="https://wa.me/972{e(links["whatsapp"][1:])}" style="color:#16a34a">💬 WhatsApp</a>')
    if row:
        parts.append('<div style="margin-top:4px">' + ' · '.join(row) + '</div>')
    return ('<div dir="auto" style="font-family:Arial;color:#555;border-top:1px solid #ddd;margin-top:16px;padding-top:8px;font-size:13px">'
            + ''.join(parts) + '</div>'), logo


def rich_html(html):
    """The editor's HTML, cleaned like an incoming email (pasted text can carry anything)."""
    from mailbrief.mail.sanitize import clean_html
    return clean_html(html[:300000], images=True)[0]


def build(item, acc, files_data=(), include_signature=True):
    msg = EmailMessage()
    msg['From'] = formataddr((acc['display_name'], acc['email'])) if acc.get('display_name') else acc['email']
    if item['to']:
        msg['To'] = ', '.join(item['to'])
    if item.get('cc'):
        msg['Cc'] = ', '.join(item['cc'])
    if item.get('bcc'):
        msg['Bcc'] = ', '.join(item['bcc'])
    msg['Subject'] = item['subject']
    msg['Date'] = formatdate(localtime=True)
    msg['X-MailBrief-Scheduled'] = '1'
    for header, key in (('In-Reply-To', 'in_reply_to'), ('References', 'references')):
        if (item.get('thread') or {}).get(key):
            msg[header] = item['thread'][key]
    if not item.get('message_id'):                     # known in advance: the automatic follow-up looks for replies to it
        item['message_id'] = make_msgid(domain=acc['email'].rsplit('@', 1)[-1])
    msg['Message-ID'] = item['message_id']
    quote = item.get('quote') or {}
    msg.set_content((with_signature(item['body'], acc) if include_signature else item['body']) + ('\n\n' + quote['text'] if quote.get('text') else ''))
    sig_html, logo = signature_html(acc) if include_signature else ('', None)
    quoted = ''
    if quote.get('html'):
        quoted = f'<br><div class="mb-quote">{quote["html"]}</div>'
    elif quote.get('text'):
        quoted = f'<br><div style="white-space:pre-wrap;color:#555">{e(quote["text"])}</div>'
    text_html = (f'<div dir="auto" style="font-family:Arial">{item["html"]}</div>' if item.get('html') else
                 f'<div dir="auto" style="font-family:Arial;white-space:pre-wrap">{e(item["body"].rstrip())}</div>')
    msg.add_alternative(f'{text_html}{sig_html}{quoted}', subtype='html')
    if logo:
        msg.get_payload()[-1].add_related(logo[0], maintype='image', subtype=logo[1], cid=f'<{LOGO_CID}>')
    if item.get('forward'):                            # ↪️ a forward takes the original's files along
        from mailbrief.mail import mailbox
        f = item['forward']
        original = mailbox.parse(mailbox.fetch_raw(f['account'], f['folder'], f['uid'], mark_seen=False))
        for _, name, ctype, _, part in mailbox.attachments(original):
            main, _, sub = ctype.partition('/')
            msg.add_attachment(part.get_payload(decode=True) or b'', maintype=main, subtype=sub or 'octet-stream', filename=name)
    for name, data in files_data:
        name = safe_name(name) or 'file'
        ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        main, sub = ctype.split('/', 1)
        if not any(p.get_filename() == name and p.get_payload(decode=True) == data for p in msg.iter_attachments()):
            msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    for name in item.get('files', []):
        path = os.path.join(config.DATA, 'outbox-files', item['id'], name)
        with open(path, 'rb') as f:
            ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
            main, sub = ctype.split('/', 1)
            data = f.read()
            if not any(p.get_filename() == name and p.get_payload(decode=True) == data for p in msg.iter_attachments()):
                msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return msg


def after_send(acc, item, message):
    """A copy in Sent (servers other than Gmail / Outlook don't keep one themselves), and the draft it came from goes."""
    from mailbrief.mail import mailbox
    try:
        if not mailbox.keeps_sent_copy(acc):
            del message['Bcc']
            mailbox.append(acc['email'], 'sent', message)
        if item.get('draft'):
            mailbox.delete_for_good(item['draft'].get('account') or acc['email'], item['draft']['folder'], [item['draft']['uid']])
    except Exception:
        pass
    try:
        from mailbrief.features import live
        live.bump()
    except Exception:
        pass


@locked(lambda: config.OUTBOX_FILE + '.sender')
def send_due(accounts=None, now=None):
    """One sender across processes. Claim and persist each message before contacting SMTP.

    Queue changes use a separate short lock, so adding/cancelling other messages stays possible during network I/O.
    An interrupted submission is never retried automatically: SMTP cannot guarantee exactly-once delivery.
    """
    fixed_now = now
    now = now or _now()
    if is_holy_time(now) or not net.online():
        return 0
    accounts = load_json(config.ACCOUNTS_FILE, []) if accounts is None else accounts
    with file_lock(config.OUTBOX_FILE):
        items = outbox()
        for it in items:
            if it['status'] == 'sending':
                it['status'] = 'uncertain'
                it['error'] = 'התוכנה נסגרה בזמן שליחה — יש לבדוק בדואר שנשלח לפני שליחה נוספת'
        save_json(config.OUTBOX_FILE, items)
        ids = [it['id'] for it in items if it['status'] == 'waiting']
    sent = attempts = 0
    for item_id in ids:
        now = fixed_now or _now()
        if attempts >= MAX_PER_RUN or is_holy_time(now):
            break
        with file_lock(config.OUTBOX_FILE):
            items = outbox()
            it = next((it for it in items if it['id'] == item_id and it['status'] == 'waiting'), None)
            if not it or dt.datetime.fromisoformat(it['send_at']) > now:
                continue
            it['status'] = 'sending'
            it.setdefault('message_id', make_msgid())
            save_json(config.OUTBOX_FILE, items)
        attempts += 1
        acc = next((a for a in accounts if a['email'].lower() == it['account'].lower()), None)
        message = None
        try:
            if not acc:
                raise RuntimeError('התיבה כבר לא מחוברת')
            message = build(it, acc)
            smtp.send_mail(acc, message)
        except smtp.PartialDelivery as exc:
            it.update(status='partial', error=str(exc), refused=exc.refused, accepted=exc.accepted,
                      sent=now.isoformat())
        except smtp.DeliveryUncertain as exc:
            it.update(status='uncertain', error=str(exc))
        except smtplib.SMTPException as exc:
            it.update(status='failed', error=str(exc)[:200])
        except (OSError, TimeoutError) as exc:  # before SMTP submission (submission errors are DeliveryUncertain)
            it.update(status='waiting', retry=f'{now.isoformat()} · {str(exc)[:120]}')
        except Exception as exc:
            if str(exc) == net.OFFLINE:
                it.update(status='waiting', retry=f'{now.isoformat()} · {net.OFFLINE}')
            else:
                it.update(status='failed', error=str(exc)[:200])
        else:
            it.update(status='sent', sent=now.isoformat())
            it.pop('retry', None)
            sent += 1
        # Commit SMTP's result before optional bookkeeping; a follow-up/copy failure must never trigger resending.
        with file_lock(config.OUTBOX_FILE):
            items = outbox()
            items = [it if old['id'] == item_id else old for old in items]
            save_json(config.OUTBOX_FILE, items)
            if it['status'] == 'sent' and it.get('files'):
                shutil.rmtree(os.path.join(config.DATA, 'outbox-files', it['id']), ignore_errors=True)
        if it['status'] == 'sent':
            after_send(acc, it, message)
            if it.get('follow'):
                try:
                    from mailbrief.features.autofollow import register
                    register(it, now)
                except Exception:
                    from mailbrief.features.diag import log_error
                    log_error('outbox follow-up')
    with file_lock(config.OUTBOX_FILE):
        items = outbox()
        for it in items:
            if it['status'] == 'cancelled' and it.get('files'):
                shutil.rmtree(os.path.join(config.DATA, 'outbox-files', it['id']), ignore_errors=True)
        active = [it for it in items if it['status'] not in ('sent', 'cancelled')]
        done = [it for it in items if it['status'] in ('sent', 'cancelled')]
        save_json(config.OUTBOX_FILE, active + done[-50:])
    return sent
