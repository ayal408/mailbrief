"""📥 The inbox page — MailBrief as a mailbox: folders, the message list, a reading pane, and writing / replying,
without opening Gmail. The page is one screen that talks to small JSON addresses (/inbox_*.json); the email body
itself is shown from /inbox_body, which is sandboxed (see mail/sanitize.py)."""
import collections
import html as _html
import json
import re
from email.utils import getaddresses
from urllib.parse import quote

from mailbrief import config, view
from mailbrief.mail import mailbox, sanitize
from mailbrief.mail.message import body_text, decode
from mailbrief.storage import load_json
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


# ---- data for the page ---------------------------------------------------------------------------------------------------

def gmail_link(address, gid):
    return f'https://mail.google.com/mail/?authuser={quote(address)}#all/{gid}' if gid else ''


def contact_card(address, sender_email):
    """👤 Who wrote: how many emails, when last, how fast you answer, the client card and the receipts / invoices."""
    sender_email = (sender_email or '').lower()
    if not sender_email or sender_email == (address or '').lower():
        return None
    history = [h for h in load_json(config.HISTORY_FILE, {}).values() if (h.get('sender') or '').lower() == sender_email]
    card = {'email': sender_email, 'emails': len(history), 'last': max((h['date'] for h in history), default=''),
            'name': next((h.get('name') for h in sorted(history, key=lambda h: h['date'], reverse=True) if h.get('name')), '')}
    answered = [h for h in history if h.get('answered') is not None]
    if answered:
        card['answered_pct'] = round(100 * sum(1 for h in answered if h['answered']) / len(answered))
    hours = sorted(h['reply_hours'] for h in history if h.get('reply_hours') is not None)
    if hours:
        card['reply_hours'] = hours[len(hours) // 2]
    card['waiting'] = sum(1 for h in history if h.get('answered') is False)
    try:
        from mailbrief.money.ledger import ils, vendor_key
        key = vendor_key(sender_email)
        docs = [r for r in load_json(config.LEDGER_FILE, {}).values() if r.get('vendor_key') == key]
        if docs:
            card['docs'] = len(docs)
            card['docs_total'] = round(sum(ils(r) or 0 for r in docs))
            card['docs_last'] = max(r['date'] for r in docs)
    except Exception:
        pass
    try:
        from mailbrief.features.history import client_groups
        for gkey, g in client_groups().items():
            if any((h.get('sender') or '').lower() == sender_email for h in g['emails']):
                card['client'] = {'key': gkey, 'name': g['name'], 'invoices': len(g.get('invoices', []))}
                break
    except Exception:
        pass
    try:
        book = load_json(config.CONTACTS_FILE, {})
        if (book.get(sender_email) or {}).get('phone'):
            card['phone'] = book[sender_email]['phone']
    except Exception:
        pass
    return card


def message_info(address, folder, uid):
    """Everything the reading pane shows, except the body (that comes from /inbox_body)."""
    raw = mailbox.fetch_raw(address, folder, uid)
    msg = mailbox.parse(raw)
    name, sender_email = mailbox.sender(msg)
    to = [{'name': decode(n).strip(' "'), 'email': a} for n, a in getaddresses([decode(msg.get('To') or '')]) if a]
    cc = [{'name': decode(n).strip(' "'), 'email': a} for n, a in getaddresses([decode(msg.get('Cc') or '')]) if a]
    _, blocked = sanitize.message_html(msg, images=False)
    files = [{'n': n, 'name': fname, 'type': ctype, 'size': size, 'view': viewable(ctype, fname)}
             for n, fname, ctype, size, _ in mailbox.attachments(msg)]
    text = body_text(msg)
    try:
        from mailbrief.mail.phishing import phishing_score
        score, why = phishing_score(msg, name, sender_email, text)
    except Exception:
        score, why = 0, []
    row = next((r for r in mailbox.cached_list(address.lower(), folder) if r['uid'] == int(uid)), None) or {}
    thread = row.get('thread') or mailbox.thread_key(msg)
    try:
        when = mailbox.parsedate_to_datetime(msg.get('Date')).astimezone().isoformat(timespec='minutes')
    except Exception:
        when = row.get('at', '')
    folders = mailbox.folders(address, fresh=False)
    role = next((f['role'] for f in folders if f['id'] == folder), '')
    always = address.lower() in {a.lower() for a in load_json(config.SETTINGS_FILE, {}).get('images_from', [])} or \
        sender_email.lower() in {a.lower() for a in load_json(config.SETTINGS_FILE, {}).get('images_from', [])}
    return {'account': address, 'folder': folder, 'uid': int(uid), 'role': role,
            'subject': decode(msg.get('Subject')).strip(), 'from': {'name': name, 'email': sender_email}, 'to': to, 'cc': cc,
            'date': when, 'files': files, 'blocked': blocked, 'images': always,
            'flagged': '\\Flagged' in row.get('flags', []), 'labels': row.get('labels', []),
            'phishing': {'score': score, 'why': why} if score >= 3 else None,
            'unsub': bool(msg.get('List-Unsubscribe')), 'gmail': gmail_link(address, row.get('gid', '')),
            'message_id': str(msg.get('Message-ID') or '').strip(), 'thread': thread,
            'earlier': [{'folder': r['folder'], 'uid': r['uid'], 'from': r['from'], 'at': r['at'], 'subject': r['subject']}
                        for r in mailbox.thread_messages(address, folder, thread, uid, str(msg.get('Message-ID') or '').strip())],
            'contact': contact_card(address, sender_email), 'draft': role == 'drafts' or '\\Draft' in row.get('flags', []),
            'gapps': _has_gapps(), 'can': mailbox.can(address), 'translate': translate_link(text)}


LABEL_COLORS = ['#7c3aed', '#f97316', '#0ea5e9', '#16a34a', '#ec4899', '#ca8a04', '#dc2626', '#14b8a6', '#6366f1', '#64748b']


def folder_prefs():
    """📌 Pinned / hidden / coloured folders and labels — kept on this computer: {address: {folder id: {...}}}."""
    return load_json(config.SETTINGS_FILE, {}).get('folder_prefs') or {}


def with_prefs(address, folders):
    prefs = folder_prefs().get(address.lower(), {})
    out = []
    for f in folders:
        p = prefs.get(f['id'], {})
        out.append(dict(f, hidden=bool(p.get('hidden')), pinned=bool(p.get('pinned')), color=p.get('color', '')))
    pinned = [f for f in out if f['pinned'] and not f['role']]
    return [f for f in out if f['role']] + pinned + [f for f in out if not f['role'] and not f['pinned']]


def set_folder_pref(address, folder, key, value):
    from mailbrief.storage import save_json
    settings = load_json(config.SETTINGS_FILE, {})
    box = settings.setdefault('folder_prefs', {}).setdefault(address.lower(), {}).setdefault(folder, {})
    if value in (None, False, ''):
        box.pop(key, None)
    else:
        box[key] = value
    save_json(config.SETTINGS_FILE, settings)


def translate_link(text):
    """🌐 A message mostly not in Hebrew: a Google Translate link (opened only when the user asks — it sends the text there)."""
    hebrew = len(re.findall(r'[֐-׿]', text))
    letters = len(re.findall(r'[^\W\d_]', text))
    if letters < 40 or hebrew > letters * 0.2:
        return ''
    return 'https://translate.google.com/?sl=auto&tl=iw&op=translate&text=' + quote(re.sub(r'\s+', ' ', text)[:1800])


VIEW_TYPES = ('application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp', 'text/plain', 'text/csv',
              'text/html', 'text/calendar', 'application/json', 'application/xml', 'text/xml', 'audio/mpeg', 'audio/mp4', 'audio/ogg',
              'audio/wav', 'audio/x-wav', 'audio/webm', 'video/mp4', 'video/webm', 'video/ogg')


def viewable(ctype, name=''):
    """👁️ Shown inside MailBrief: pictures, PDF, text (an HTML file as its source text), sound and video."""
    return ctype in VIEW_TYPES or bool(re.search(r'\.(txt|csv|log|md|json|xml)$', name or '', re.I))


def _has_gapps():
    try:
        from mailbrief.features.google_apps import gapps_account
        return bool(gapps_account())
    except Exception:
        return False


def body_document(address, folder, uid, images=False):
    msg = mailbox.parse(mailbox.fetch_raw(address, folder, uid, mark_seen=False))
    body, _ = sanitize.message_html(msg, images=images, collapse=True)
    return sanitize.frame_document(body)


def print_document(address, folder, uid, nonce):
    """🖨️ Subject, who, when and the cleaned body (pictures from inside the email only), then print() — nothing else runs."""
    msg = mailbox.parse(mailbox.fetch_raw(address, folder, uid, mark_seen=False))
    body, _ = sanitize.message_html(msg, images=False)
    name, sender_email = mailbox.sender(msg)
    esc = _html.escape
    rows = [('מאת', f'{name} <{sender_email}>' if name else sender_email), ('אל', decode(msg.get('To') or '')),
            ('עותק', decode(msg.get('Cc') or '')), ('תאריך', str(msg.get('Date') or ''))]
    head = ''.join(f'<tr><th>{k}</th><td dir="auto">{esc(v)}</td></tr>' for k, v in rows if v)
    files = ', '.join(esc(n) for _, n, _, _, _ in mailbox.attachments(msg))
    return (f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>{esc(decode(msg.get("Subject")) or "מייל")}</title>'
            '<style>body{font:14px/1.5 Arial,sans-serif;margin:24px;color:#111}h1{font-size:20px;margin:0 0 10px}'
            'table{border-collapse:collapse;margin-bottom:14px;font-size:13px}th{text-align:start;color:#666;padding:2px 12px 2px 0;font-weight:400}'
            'hr{border:0;border-top:1px solid #ccc;margin:12px 0}img{max-width:100%}img[data-blocked]{display:none}</style></head><body>'
            f'<h1 dir="auto">{esc(decode(msg.get("Subject")) or "(ללא נושא)")}</h1><table>{head}</table>'
            + (f'<p style="font-size:13px">📎 {files}</p>' if files else '') + f'<hr>{body}'
            f'<script nonce="{nonce}">window.onload=function(){{window.print();}};</script></body></html>')


def people():
    """For the "to" box: everyone you corresponded with, the most frequent first."""
    count, names = collections.Counter(), {}
    for h in load_json(config.HISTORY_FILE, {}).values():
        address = (h.get('sender') or '').lower()
        if address and 'newsletters' not in h.get('cats', []) and not re.search(r'no-?reply|mailer-daemon', address):
            count[address] += 1
            names.setdefault(address, h.get('name') or '')
    return [{'email': a, 'name': names.get(a, '')} for a, _ in count.most_common(800)]


def _re(prefix, subject):
    pattern = r'(?i)^\s*(re|תשובה|השב)\s*:' if prefix == 'Re' else r'(?i)^\s*(fwd?|הועבר)\s*:'
    return subject if re.match(pattern, subject or '') else f'{prefix}: {subject or ""}'.strip()


def quote_of(msg, forward=False):
    """The original under the answer: a header line, then the text (> lines) / the cleaned HTML in a side-lined block."""
    name, sender_email = mailbox.sender(msg)
    date = str(msg.get('Date') or '')
    try:
        date = mailbox.parsedate_to_datetime(msg.get('Date')).astimezone().strftime('%d/%m/%Y %H:%M')
    except Exception:
        pass
    who = f'{name} <{sender_email}>' if name else sender_email
    if forward:
        head = (f'---------- הודעה שהועברה ----------\nמאת: {who}\nתאריך: {date}\nנושא: {decode(msg.get("Subject"))}\n'
                f'אל: {decode(msg.get("To"))}\n')
    else:
        head = f'ב-{date}, {who} כתב/ה:\n'
    plain_part = msg.get_body(preferencelist=('plain',))
    try:
        plain = plain_part.get_content() if plain_part is not None else body_text(msg)
    except Exception:
        plain = body_text(msg)
    text = head + ('\n' + plain if forward else '\n'.join('> ' + line for line in plain.splitlines()))
    body, _ = sanitize.message_html(msg, images=True)
    head_html = _html.escape(head).replace('\n', '<br>')
    rich = (f'<div dir="auto" style="color:#555;font-family:Arial">{head_html}</div>'
            + (body if forward else f'<blockquote style="margin:0 0 0 .8ex;border-inline-start:1px solid #ccc;padding-inline-start:1ex">{body}</blockquote>'))
    return {'text': text, 'html': rich}


def compose_data(mode, address, folder='', uid=None):
    """What the writing window starts with: reply / all / fwd / edit (a draft) / new."""
    if mode == 'new' or not uid:
        return {'mode': 'new', 'account': address, 'to': '', 'cc': '', 'bcc': '', 'subject': '', 'body': ''}
    msg = mailbox.parse(mailbox.fetch_raw(address, folder, uid, mark_seen=False))
    me = {a['email'].lower() for a in mailbox.accounts()}
    out = {'mode': mode, 'account': address, 'folder': folder, 'uid': int(uid), 'to': '', 'cc': '', 'bcc': '', 'body': ''}
    subject = decode(msg.get('Subject')).strip()
    if mode == 'edit':
        plain = msg.get_body(preferencelist=('plain',))
        try:
            text = plain.get_content() if plain is not None else body_text(msg)
        except Exception:
            text = body_text(msg)
        out.update(to=decode(msg.get('To') or ''), cc=decode(msg.get('Cc') or ''), bcc=decode(msg.get('Bcc') or ''),
                   subject=subject, body=text.rstrip())
        return out
    if mode == 'fwd':
        out['subject'] = _re('Fwd', subject)
        out['files'] = [name for _, name, _, _, _ in mailbox.attachments(msg)]
        return out
    reply_to = [a for _, a in getaddresses([decode(msg.get('Reply-To') or msg.get('From') or '')]) if a]
    _, sender_email = mailbox.sender(msg)
    if sender_email.lower() in me:                       # answering my own sent mail: to its recipients
        reply_to = [a for _, a in getaddresses([decode(msg.get('To') or '')]) if a]
    to = list(dict.fromkeys(reply_to))
    cc = []
    if mode == 'all':
        others = [a for _, a in getaddresses([decode(msg.get('To') or ''), decode(msg.get('Cc') or '')]) if a]
        cc = [a for a in dict.fromkeys(others) if a.lower() not in me and a.lower() not in {t.lower() for t in to}]
    out.update(to=', '.join(to), cc=', '.join(cc), subject=_re('Re', subject))
    return out


def thread_headers(msg):
    mid = str(msg.get('Message-ID') or '').strip()
    refs = f"{str(msg.get('References') or '').strip()} {mid}".strip()
    return {'in_reply_to': mid, 'references': refs[-1900:]}


def receipt_from(address, msg):
    """🧾 Keep this email as a receipt / invoice: its PDF in קבלות and a row in the books."""
    from mailbrief.mail.classify import classify
    from mailbrief.money.ledger import save_attachments, update_ledger
    it = classify(msg, address, load_json(config.RULES_FILE, []))
    it['cats'] = sorted(set(it['cats']) | {'receipts'})
    it['message_id'] = str(msg.get('Message-ID') or '').strip()
    it['files'] = save_attachments(msg, it)
    if not it.get('amount'):
        try:
            from mailbrief.money.pdftext import amount_from_attachments
            it['amount'] = amount_from_attachments(msg)
        except Exception:
            pass
    update_ledger([{'email': address, 'items': [it]}])
    return it


# ---- the page ----------------------------------------------------------------------------------------------------------------

CSS = r"""
main:has(#ibx){max-width:min(1640px,calc(100vw - 32px));padding:14px}
body:has(#ibx) .hero{padding:10px 16px 0}body:has(#ibx) .hero .gift,body:has(#ibx) .hero .name,body:has(#ibx) .hero .tag{display:none}body:has(#ibx) .hero .corner{position:static;justify-content:flex-end}
#ibx{--row:var(--bg);display:grid;grid-template-columns:230px minmax(300px,400px) 1fr;gap:0;height:calc(100vh - 150px);min-height:540px;
border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--surface);text-align:start}
#ibx button{font:inherit;cursor:pointer}
.ib-side{border-inline-end:1px solid var(--line);overflow-y:auto;padding:12px 8px;background:var(--bg)}
.ib-new{width:100%;border:0;background:linear-gradient(90deg,var(--accent),var(--accent-2));color:#fff;border-radius:14px;padding:12px;font-weight:700;margin-bottom:10px;box-shadow:0 6px 18px color-mix(in srgb,var(--accent) 30%,transparent)}
.ib-acc{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);padding:12px 8px 4px;cursor:pointer;user-select:none}
.ib-acc span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ib-f{display:flex;align-items:center;gap:8px;width:100%;border:0;background:none;color:var(--ink);padding:7px 10px;border-radius:10px;text-align:start;font-size:14px}
.ib-f:hover{background:color-mix(in srgb,var(--accent) 8%,transparent)}.ib-f.on{background:color-mix(in srgb,var(--accent) 16%,transparent);font-weight:500}
.ib-f .n{margin-inline-start:auto;font-size:12px;font-weight:700;color:var(--accent)}.ib-f .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ib-list{display:flex;flex-direction:column;border-inline-end:1px solid var(--line);min-width:0}
.ib-tools{display:flex;gap:6px;align-items:center;padding:8px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.ib-tools input[type=search]{flex:1;min-width:120px;padding:8px 12px!important;border-radius:999px!important;font-size:14px}
.ib-ic{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:10px;padding:6px 9px;font-size:14px;line-height:1}
.ib-ic:hover{border-color:var(--accent)}.ib-ic.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.ib-bulk{display:none;gap:4px;width:100%;align-items:center;font-size:13px}.ib-bulk.on{display:flex}
.ib-rows{overflow-y:auto;flex:1}
.ib-row{display:grid;grid-template-columns:auto 1fr auto;gap:2px 8px;padding:9px 10px;border-bottom:1px solid var(--line);cursor:pointer;position:relative}
.ib-row:hover{background:color-mix(in srgb,var(--accent) 5%,transparent)}
.ib-row.sel{background:color-mix(in srgb,var(--accent) 13%,transparent)}.ib-row.kb{box-shadow:inset 3px 0 0 var(--accent-2)}
.ib-row.unread .who,.ib-row.unread .sub{font-weight:700}.ib-row.unread::before{content:"";position:absolute;inset-inline-start:2px;top:16px;width:6px;height:6px;border-radius:50%;background:var(--accent)}
.ib-row .ck{grid-row:span 2;display:flex;flex-direction:column;gap:2px;align-items:center}
.ib-row input{margin:0;cursor:pointer}.ib-star{border:0;background:none;padding:0;font-size:15px;color:var(--muted);filter:grayscale(1);opacity:.5}
.ib-star.on{filter:none;opacity:1}
.ib-row .who{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}.ib-row .when{font-size:12px;color:var(--muted);white-space:nowrap}
.ib-row .sub{grid-column:2/4;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ib-row .sn{color:var(--muted);font-weight:400}.ib-row .cnt{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:0 6px;margin-inline-start:4px}
.ib-more{padding:12px;text-align:center}.ib-empty{padding:40px 16px;text-align:center;color:var(--muted)}
.ib-read{display:flex;flex-direction:column;min-width:0;overflow:hidden}
.ib-mtools{display:flex;gap:4px;flex-wrap:wrap;padding:8px 12px;border-bottom:1px solid var(--line);align-items:center}
.ib-mtools select{font:inherit;font-size:13px;padding:5px 8px;border-radius:10px;border:1px solid var(--line);background:var(--surface);color:var(--ink);max-width:150px}
.ib-scroll{overflow-y:auto;flex:1;display:flex;flex-direction:column}
.ib-head{padding:14px 18px 6px}.ib-head h2{font-size:20px;margin:0 0 8px;direction:rtl;text-align:start;unicode-bidi:plaintext}
.ib-meta{display:flex;gap:10px;align-items:flex-start;font-size:13px;color:var(--muted)}.ib-meta b{color:var(--ink);font-size:14px}
.ib-av{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;color:#fff;font-weight:700;flex:none}
.ib-card{margin:8px 18px 0;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--bg);font-size:13px;display:flex;gap:12px;flex-wrap:wrap}
.ib-card span{white-space:nowrap}
.ib-warn{margin:8px 18px 0;padding:10px 12px;border:1px solid var(--bad);color:var(--bad);border-radius:12px;font-size:13px}
.ib-imgs{margin:8px 18px 0;padding:8px 12px;border:1px dashed var(--line);border-radius:12px;font-size:13px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.ib-imgs button{border:0;background:none;color:var(--accent);padding:0;text-decoration:underline}
.ib-earlier{margin:8px 18px 0}.ib-earlier div{padding:6px 10px;border:1px solid var(--line);border-radius:10px;margin-bottom:4px;font-size:13px;cursor:pointer;background:var(--bg)}
.ib-earlier div:hover{border-color:var(--accent)}
.ib-body{flex:1;min-height:420px;margin:10px 18px;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff;display:flex}
.ib-body iframe{border:0;width:100%;flex:1;min-height:420px;background:#fff}
.ib-files{display:flex;gap:8px;flex-wrap:wrap;margin:0 18px 14px}
.ib-file{display:flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:10px;padding:6px 10px;font-size:13px;background:var(--bg)}
.ib-file a,.ib-file button{border:0;background:none;color:var(--accent);padding:0;font-size:12px;text-decoration:none}
.ib-quick{display:flex;gap:6px;margin:0 18px 18px;flex-wrap:wrap}
.ib-none{margin:auto;text-align:center;color:var(--muted);padding:30px}.ib-none b{font-size:56px;display:block}
.ib-back{display:none}
#ib-comp{position:fixed;bottom:16px;inset-inline-end:16px;width:min(620px,calc(100vw - 24px));max-height:calc(100vh - 32px);display:none;flex-direction:column;
background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.25);z-index:50;overflow:hidden}
#ib-comp.on{display:flex}#ib-comp.big{width:min(1000px,calc(100vw - 24px));height:calc(100vh - 32px)}
#ib-comp header{display:flex;align-items:center;gap:8px;padding:10px 14px;background:linear-gradient(90deg,var(--accent),var(--accent-2));color:#fff;font-weight:500}
#ib-comp header button{border:0;background:rgba(255,255,255,.18);color:#fff;border-radius:8px;padding:3px 9px}
#ib-comp .fl{display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--line);padding:4px 14px}
#ib-comp .fl[hidden]{display:none}
#ib-comp .fl label{font-size:13px;color:var(--muted);min-width:44px}
#ib-comp .fl input,#ib-comp .fl select{flex:1;border:0;background:none;color:var(--ink);font:inherit;padding:8px 0;outline:none}
#ib-c-body{flex:1;min-height:220px;overflow-y:auto;padding:12px 14px;font-size:15px;background:var(--surface);color:var(--ink);outline:none;line-height:1.6}
#ib-c-body:empty::before{content:attr(data-ph);color:var(--muted)}#ib-c-body a{color:var(--accent)}
#ib-comp.drop{outline:3px dashed var(--accent);outline-offset:-8px}
.ib-fmt{display:flex;gap:2px;flex-wrap:wrap;padding:4px 10px;border-bottom:1px solid var(--line);background:var(--bg)}
.ib-fmt button{border:0;background:none;color:var(--ink);border-radius:8px;padding:4px 8px;font-size:14px;min-width:30px}
.ib-fmt button:hover{background:color-mix(in srgb,var(--accent) 12%,transparent)}.ib-fmt .sw{width:18px;height:18px;min-width:0;padding:0;border-radius:50%;margin:3px 2px}
.ib-pop{position:fixed;z-index:70;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:14px;box-shadow:0 14px 40px rgba(0,0,0,.2);padding:8px;min-width:200px;display:none;font-size:14px}
.ib-pop.on{display:block}.ib-pop button.it{display:flex;gap:8px;width:100%;border:0;background:none;color:var(--ink);text-align:start;padding:7px 10px;border-radius:8px}
.ib-pop button.it:hover{background:color-mix(in srgb,var(--accent) 10%,transparent)}.ib-pop .row{display:flex;gap:6px;align-items:center;padding:6px 8px;flex-wrap:wrap}
.ib-pop input[type=text],.ib-pop select{font:inherit;font-size:14px;padding:6px 10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);flex:1;min-width:0}
.ib-pop label{font-size:13px;color:var(--muted)}.ib-pop .sw{width:20px;height:20px;border-radius:50%;border:2px solid var(--surface);box-shadow:0 0 0 1px var(--line);cursor:pointer;padding:0}
#ib-view{position:fixed;inset:0;z-index:75;background:rgba(10,8,16,.75);display:none;flex-direction:column}
#ib-view.on{display:flex}#ib-view header{display:flex;gap:10px;align-items:center;padding:10px 16px;color:#fff}
#ib-view header button,#ib-view header a{border:0;background:rgba(255,255,255,.15);color:#fff;border-radius:10px;padding:6px 12px;text-decoration:none;font-size:14px}
#ib-view .stage{flex:1;display:grid;place-items:center;padding:0 16px 16px;min-height:0}
#ib-view .stage>*{max-width:100%;max-height:100%;border-radius:10px;background:#fff}#ib-view iframe{width:min(1100px,100%);height:100%;border:0}
.ib-home{padding:22px;overflow-y:auto;flex:1}.ib-home h3{margin:0 0 12px}.ib-accs{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px;margin-bottom:18px}
.ib-acc-card{border:1px solid var(--line);border-radius:14px;padding:12px 14px;background:var(--bg);cursor:pointer}.ib-acc-card:hover{border-color:var(--accent)}
.ib-acc-card b{font-size:28px;display:block}.ib-week{display:flex;gap:6px;align-items:flex-end;height:90px;margin:8px 0 18px}
.ib-week div{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;font-size:11px;color:var(--muted);height:100%;justify-content:flex-end}
.ib-week i{display:block;width:100%;max-width:38px;border-radius:6px 6px 2px 2px;background:linear-gradient(180deg,var(--accent),var(--accent-2));min-height:3px}
.ib-late div{padding:8px 10px;border:1px solid var(--line);border-radius:10px;margin-bottom:6px;cursor:pointer;font-size:13px;background:var(--bg)}.ib-late div:hover{border-color:var(--accent)}
#ibx.dense .ib-row{padding:4px 10px;gap:0 8px}#ibx.dense .ib-row .sub{font-size:12.5px}#ibx.dense .ib-f{padding:4px 10px}
#ibx.nopane{grid-template-columns:230px 1fr}#ibx.nopane .ib-read{display:none}#ibx.nopane.reading .ib-list{display:none}#ibx.nopane.reading .ib-read{display:flex}
#ibx.nopane.reading .ib-back{display:inline-block}.ib-hid{opacity:.55}.ib-f.drop{background:color-mix(in srgb,var(--accent) 25%,transparent);outline:2px dashed var(--accent)}
.ib-inline{border:1px solid var(--line);border-radius:10px;margin:-2px 0 6px;overflow:hidden;background:#fff;resize:vertical;height:280px;display:flex}
.ib-inline iframe{border:0;width:100%;flex:1}.ib-dot{width:9px;height:9px;border-radius:50%;flex:none}
#ib-comp footer{display:flex;gap:8px;align-items:center;padding:10px 14px;border-top:1px solid var(--line);flex-wrap:wrap}
#ib-comp footer .send{border:0;background:var(--accent);color:#fff;border-radius:12px;padding:9px 20px;font-weight:700}
#ib-comp footer select{font:inherit;font-size:13px;padding:6px;border-radius:10px;border:1px solid var(--line);background:var(--surface);color:var(--ink)}
#ib-comp .note{font-size:12px;color:var(--muted);padding:4px 14px}
#ib-toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1d1a24;color:#fff;padding:10px 16px;border-radius:12px;display:none;gap:12px;align-items:center;z-index:60;font-size:14px;box-shadow:0 10px 30px rgba(0,0,0,.3)}
#ib-toast.on{display:flex}#ib-toast button{border:0;background:none;color:#fbbf24;font-weight:700;padding:0}
@media(max-width:1100px){#ibx{grid-template-columns:200px minmax(260px,340px) 1fr}}
@media(max-width:820px){#ibx{grid-template-columns:1fr;height:auto;min-height:0}.ib-side{display:flex;gap:4px;overflow-x:auto;padding:8px;border:0;border-bottom:1px solid var(--line)}
.ib-side .ib-new{width:auto;margin:0;white-space:nowrap}.ib-acc{display:none}.ib-f{width:auto;white-space:nowrap}.ib-rows{max-height:none}
.ib-read{display:none;position:fixed;inset:0;z-index:40;background:var(--surface)}#ibx.reading .ib-read{display:flex}.ib-back{display:inline-block}}
"""


def inbox_page(start=None):
    boxes = view.emails()
    if not boxes:
        return page('דואר נכנס', heading('📥', 'דואר נכנס') + '<p>עוד לא חוברה תיבת מייל. <a href="/?s=boxes">חיבור תיבה</a></p>', '/inbox')
    current = view.current_account()
    start = start or {}
    boot = {'accounts': [{'email': b, 'color': view.color(b), 'name': view.account(b).get('display_name', '')} for b in boxes],
            'account': start.get('a') or (current if current else ('*' if len(boxes) > 1 else boxes[0])),
            'folder': start.get('f') or 'INBOX', 'uid': start.get('u') or '', 'token': TOKEN, 'q': start.get('q') or '', 'compose': bool(start.get('compose'))}
    data = json.dumps(boot, ensure_ascii=False).replace('</', '<\\/')
    body = f'''<style>{CSS}</style>
<div id="ibx">
  <aside class="ib-side"><button class="ib-new" type="button" data-do="compose" title="הודעה חדשה (C)">✏️ הודעה חדשה</button><div id="ib-folders"></div></aside>
  <section class="ib-list">
    <div class="ib-tools">
      <input type="checkbox" id="ib-all" title="בחירת הכול (X לבחירת שורה)">
      <input type="search" id="ib-q" placeholder="🔍 חיפוש בתיקייה… (/)" autocomplete="off">
      <button class="ib-ic" type="button" id="ib-adv" title="אפשרויות חיפוש">⚙️</button>
      <button class="ib-ic" type="button" id="ib-unread" title="רק לא נקראו">●</button>
      <button class="ib-ic" type="button" id="ib-refresh" title="רענון">⟳</button>
      <button class="ib-ic" type="button" id="ib-look" title="תצוגה: צפיפות, גופן, חלונית קריאה">🎛️</button>
      <div class="ib-bulk" id="ib-bulk"><span id="ib-bulk-n"></span>
        <button class="ib-ic" type="button" data-bulk="read" title="סימון כנקרא">✉️</button><button class="ib-ic" type="button" data-bulk="unread" title="סימון כלא נקרא">●</button>
        <button class="ib-ic" type="button" data-bulk="star" title="כוכב">⭐</button><button class="ib-ic" type="button" data-bulk="archive" title="לארכיון (E)">🗄️</button>
        <button class="ib-ic" type="button" data-bulk="delete" title="מחיקה (#)">🗑️</button><button class="ib-ic" type="button" data-bulk="spam" title="ספאם">🚫</button></div>
    </div>
    <div class="ib-rows" id="ib-rows"><div class="ib-empty">טוען…</div></div>
  </section>
  <section class="ib-read" id="ib-read"><div class="ib-none"><b>📬</b>בוחרים הודעה מהרשימה כדי לקרוא אותה כאן<br>
    <span style="font-size:13px">מקשים: <kbd>J</kbd>/<kbd>K</kbd> מעבר · <kbd>Enter</kbd> פתיחה · <kbd>E</kbd> ארכיון · <kbd>#</kbd> מחיקה · <kbd>R</kbd> תשובה · <kbd>A</kbd> לכולם · <kbd>F</kbd> העברה · <kbd>S</kbd> כוכב · <kbd>U</kbd> לא נקרא · <kbd>C</kbd> חדשה · <kbd>/</kbd> חיפוש</span></div></section>
</div>
<div id="ib-comp" role="dialog" aria-label="כתיבת מייל">
  <header><span id="ib-c-title">✏️ הודעה חדשה</span><span style="flex:1"></span><button type="button" id="ib-c-big" title="הגדלה">⤢</button><button type="button" id="ib-c-close" title="סגירה (נשמר כטיוטה)">✕</button></header>
  <div class="fl"><label>מאת</label><select id="ib-c-from"></select></div>
  <div class="fl"><label>אל</label><input id="ib-c-to" list="ib-people" autocomplete="off" dir="ltr"><button type="button" class="ib-ic" id="ib-c-ccb" style="font-size:12px">עותק / מוסתר</button></div>
  <div class="fl" id="ib-c-ccrow" hidden><label>עותק</label><input id="ib-c-cc" list="ib-people" autocomplete="off" dir="ltr"></div>
  <div class="fl" id="ib-c-bccrow" hidden><label>מוסתר</label><input id="ib-c-bcc" list="ib-people" autocomplete="off" dir="ltr"></div>
  <div class="fl"><label>נושא</label><input id="ib-c-subject" dir="auto"></div>
  <div class="ib-fmt" id="ib-fmt">
    <button type="button" data-cmd="bold" title="מודגש (Ctrl+B)"><b>B</b></button><button type="button" data-cmd="italic" title="נטוי (Ctrl+I)"><i>I</i></button>
    <button type="button" data-cmd="underline" title="קו תחתון (Ctrl+U)"><u>U</u></button><button type="button" data-cmd="strikeThrough" title="קו חוצה"><s>S</s></button>
    <button type="button" data-cmd="insertUnorderedList" title="רשימה">•≡</button><button type="button" data-cmd="insertOrderedList" title="רשימה ממוספרת">1≡</button>
    <button type="button" data-cmd="link" title="קישור">🔗</button><button type="button" data-cmd="rtl" title="ימין לשמאל">⇐</button><button type="button" data-cmd="ltr" title="שמאל לימין">⇒</button>
    <button type="button" class="sw" data-color="#1d1a24" style="background:#1d1a24" title="שחור"></button><button type="button" class="sw" data-color="#dc2626" style="background:#dc2626" title="אדום"></button>
    <button type="button" class="sw" data-color="#2563eb" style="background:#2563eb" title="כחול"></button><button type="button" class="sw" data-color="#16a34a" style="background:#16a34a" title="ירוק"></button>
    <button type="button" class="sw" data-color="#7c3aed" style="background:#7c3aed" title="סגול"></button>
    <button type="button" data-cmd="big" title="גדול">A+</button><button type="button" data-cmd="removeFormat" title="ניקוי עיצוב">⌫</button><button type="button" data-cmd="template" title="הוספת תבנית תשובה">📋 תבנית</button>
  </div>
  <div id="ib-c-body" contenteditable="true" dir="auto" role="textbox" aria-multiline="true" data-ph="כותבים כאן… אפשר גם לגרור קבצים לכאן"></div>
  <div class="note" id="ib-c-note"></div>
  <footer>
    <button type="button" class="send" id="ib-c-send">שליחה ➤</button>
    <select id="ib-c-when" title="מתי לשלוח"><option value="now">עכשיו</option><option value="tomorrow8">מחר ב-8:00</option><option value="sunday8">ראשון ב-8:00</option><option value="after_holy">אחרי שבת / חג</option><option value="custom">📅 במועד אחר…</option></select>
    <input type="datetime-local" id="ib-c-at" hidden title="מתי לשלוח" style="font:inherit;font-size:13px;padding:5px 8px;border-radius:10px;border:1px solid var(--line);background:var(--surface);color:var(--ink)">
    <label class="ib-ic" style="cursor:pointer">📎 קבצים<input type="file" id="ib-c-files" multiple hidden></label><span id="ib-c-fn" class="muted" style="font-size:12px"></span>
    <label style="font-size:13px" id="ib-c-qrow"><input type="checkbox" id="ib-c-quote" checked> לצטט את המקור</label>
    <span style="flex:1"></span><button type="button" class="ib-ic" id="ib-c-draft" title="שמירה בטיוטות">💾</button><button type="button" class="ib-ic" id="ib-c-discard" title="מחיקת הטיוטה">🗑️</button>
  </footer>
</div>
<datalist id="ib-people"></datalist>
<div class="ib-pop" id="ib-menu"></div>
<div id="ib-view" role="dialog" aria-label="צפייה בקובץ"><header><b id="ib-view-name" dir="auto" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></b>
  <button type="button" id="ib-view-open">פתיחה בתוכנה</button><button type="button" id="ib-view-save">💾 שמירה</button><button type="button" id="ib-view-x">✕ סגירה</button></header><div class="stage" id="ib-view-stage"></div></div>
<div id="ib-toast"><span id="ib-toast-t"></span><button type="button" id="ib-toast-b"></button></div>
<script>window.IBX={data};</script><script>{JS}</script>'''
    return page('דואר נכנס', body, '/inbox')


JS = r"""
(function(){
var B = window.IBX, $ = function(id){ return document.getElementById(id); };
if (window.__ibx) window.__ibx.stop();
var S = {acc: B.account, folder: B.folder, page: 0, q: B.q, unread: false, items: [], groups: [], sel: null, kb: -1, checked: {}, v: -1,
         open: null, imgs: false, comp: null, gpending: 0, folders: {}, total: 0};
var esc = function(t){ return String(t == null ? '' : t).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); };
var color = function(a){ var x = B.accounts.filter(function(b){ return b.email.toLowerCase() === (a||'').toLowerCase(); })[0]; return x ? x.color : '#7c3aed'; };
var multi = B.accounts.length > 1;

function api(path, params){
  var u = new URL(path, location.href); Object.keys(params || {}).forEach(function(k){ if (params[k] !== '' && params[k] != null) u.searchParams.set(k, params[k]); });
  return fetch(u, {credentials: 'same-origin', cache: 'no-store'}).then(function(r){ return r.json().then(function(d){ if (!r.ok) throw new Error(d.error || r.status); return d; }); });
}
function post(path, fields, files){
  var f = new FormData(); f.append('t', B.token); Object.keys(fields).forEach(function(k){ f.append(k, fields[k]); });
  (files || []).forEach(function(x){ f.append('files', x, x.name); });
  return fetch(path, {method: 'POST', body: f, credentials: 'same-origin'}).then(function(r){ return r.json().then(function(d){ if (!r.ok || d.error) throw new Error(d.error || r.status); return d; }); });
}
var toastTimer;
function toast(text, label, action, seconds){
  clearInterval(toastTimer); $('ib-toast-t').textContent = text; var b = $('ib-toast-b');
  b.style.display = label ? '' : 'none'; b.textContent = label || ''; b.onclick = function(){ $('ib-toast').classList.remove('on'); if (action) action(); };
  $('ib-toast').classList.add('on'); var left = seconds || 5;
  toastTimer = setInterval(function(){ if (--left <= 0) { clearInterval(toastTimer); $('ib-toast').classList.remove('on'); } else if (label && seconds) b.textContent = label + ' (' + left + ')'; }, 1000);
  if (label && seconds) b.textContent = label + ' (' + left + ')';
}
function fail(e){ toast('⚠️ ' + (e && e.message || e)); }

function when(iso){
  if (!iso) return ''; var d = new Date(iso), now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString('he-IL', {hour: '2-digit', minute: '2-digit'});
  var y = new Date(now); y.setDate(now.getDate() - 1); if (d.toDateString() === y.toDateString()) return 'אתמול';
  if (now - d < 6 * 864e5) return d.toLocaleDateString('he-IL', {weekday: 'short'});
  return d.toLocaleDateString('he-IL', d.getFullYear() === now.getFullYear() ? {day: 'numeric', month: 'short'} : {day: 'numeric', month: 'numeric', year: '2-digit'});
}
function sizeOf(n){ return n > 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.max(1, Math.round(n / 1024)) + 'KB'; }
function avatar(name, mail, size){
  var l = (name || mail || '?').trim().charAt(0).toUpperCase(), h = 0; (mail || '').split('').forEach(function(c){ h = (h * 31 + c.charCodeAt(0)) % 360; });
  return '<span class="ib-av" style="background:hsl(' + h + ' 55% 52%);' + (size ? 'width:' + size + 'px;height:' + size + 'px' : '') + '">' + esc(l) + '</span>';
}
function syncUrl(){
  var u = new URL(location.href); u.search = '';
  if (S.acc) u.searchParams.set('a', S.acc); if (S.folder !== 'INBOX') u.searchParams.set('f', S.folder);
  if (S.open) u.searchParams.set('u', S.open.uid); if (S.q) u.searchParams.set('q', S.q);
  history.replaceState(history.state, '', u.pathname + u.search);
}

// ---- folders ----
function folderButton(acc, f){
  var on = S.acc === acc && S.folder === f.id;
  return '<button type="button" class="ib-f' + (on ? ' on' : '') + (f.hidden ? ' ib-hid' : '') + '" data-acc="' + esc(acc) + '" data-folder="' + esc(f.id) + '" title="' + esc(f.path || f.name) + ' — לחיצה ימנית לעוד" style="padding-inline-start:' + (10 + 12 * Math.min(f.pinned ? 0 : f.depth || 0, 3)) + 'px">' +
    (f.color ? '<span class="ib-dot" style="background:' + esc(f.color) + '"></span>' : '<span>' + (f.pinned && !f.role ? '📌' : f.icon) + '</span>') +
    '<span class="nm">' + esc(f.name) + '</span>' + (f.unread ? '<span class="n">' + f.unread + '</span>' : '') + '</button>';
}
function drawFolders(){
  var html = '';
  if (multi) html += '<button type="button" class="ib-f' + (S.acc === '*' ? ' on' : '') + '" data-acc="*" data-folder="INBOX"><span>📬</span><span class="nm">כל התיבות</span></button>';
  B.accounts.forEach(function(a){
    var list = S.folders[a.email], open = !multi || S.acc === a.email || a.open;
    if (multi) html += '<div class="ib-acc" data-toggle="' + esc(a.email) + '"><span style="width:8px;height:8px;border-radius:50%;background:' + a.color + ';flex:none"></span><span>' + esc(a.name || a.email) + '</span><span style="margin-inline-start:auto">' + (open ? '▾' : '▸') + '</span></div>';
    if (!open) return;
    if (!list) { html += '<div class="muted" style="font-size:12px;padding:4px 12px">טוען תיקיות…</div>'; return; }
    if (list.error) { html += '<div class="muted" style="font-size:12px;padding:4px 12px">⚠️ ' + esc(list.error) + '</div>'; return; }
    var shown = list.filter(function(f){ return !f.hidden || S.showHidden || (S.acc === a.email && S.folder === f.id); });
    var hidden = list.filter(function(f){ return f.hidden; }).length;
    var main = shown.filter(function(f){ return f.role || f.pinned; }), own = shown.filter(function(f){ return !f.role && !f.pinned; });
    html += main.map(function(f){ return folderButton(a.email, f); }).join('');
    html += '<details' + (own.some(function(f){ return S.acc === a.email && S.folder === f.id; }) || S.labelsOpen ? ' open' : '') + ' data-labels="1"><summary class="muted" style="font-size:12px;padding:6px 12px;cursor:pointer">תוויות ותיקיות (' + own.length + ')</summary>' +
      own.map(function(f){ return folderButton(a.email, f); }).join('') +
      '<button type="button" class="ib-f" data-newlabel="' + esc(a.email) + '" style="color:var(--muted);font-size:13px"><span>➕</span><span class="nm">תווית / תיקייה חדשה</span></button>' +
      (hidden ? '<button type="button" class="ib-f" data-showhidden="1" style="color:var(--muted);font-size:13px"><span>👁️</span><span class="nm">' + (S.showHidden ? 'הסתרת המוסתרות' : 'הצגת מוסתרות (' + hidden + ')') + '</span></button>' : '') + '</details>';
  });
  $('ib-folders').innerHTML = html;
}

// ---- small menus (folders, search options, display) ----
function menu(anchor, html, setup){
  var m = $('ib-menu'); m.innerHTML = html; m.classList.add('on'); m.onclick = null;
  var r = anchor.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
  m.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, r.bottom + 4)) + 'px';
  m.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w)) + 'px';
  if (setup) setup(m);
  var first = m.querySelector('input[type=text]'); if (first) first.focus();
}
function closeMenu(){ $('ib-menu').classList.remove('on'); }
function outside(ev){ var m = $('ib-menu'); if (m && m.classList.contains('on') && !m.contains(ev.target) && !ev.target.closest('#ib-adv,#ib-look')) closeMenu(); }
function folderOp(acc, folder, op, extra){
  return post('/inbox_folder', Object.assign({a: acc, f: folder, op: op}, extra || {})).then(function(d){ closeMenu(); return loadFolders(acc, true).then(function(){ return d; }); }).catch(fail);
}
var COLORS = ['#7c3aed', '#f97316', '#0ea5e9', '#16a34a', '#ec4899', '#ca8a04', '#dc2626', '#14b8a6', '#6366f1', '#64748b'];
function folderMenu(btn){
  var acc = btn.dataset.acc, id = btn.dataset.folder, f = (S.folders[acc] || []).filter(function(x){ return x.id === id; })[0];
  if (!f) return;
  var gmail = /gmail\.com$|googlemail\.com$/i.test(acc);
  menu(btn, '<div class="row"><b dir="auto">' + esc(f.icon + ' ' + (f.path || f.name)) + '</b></div>' +
    (f.role ? '' : '<button type="button" class="it" data-op="pin">' + (f.pinned ? '📌 ביטול הצמדה' : '📌 הצמדה למעלה') + '</button>') +
    '<button type="button" class="it" data-op="hide">' + (f.hidden ? '👁️ הצגה ברשימה' : '🙈 הסתרה מהרשימה') + '</button>' +
    '<div class="row"><label>🎨</label>' + COLORS.map(function(c){ return '<button type="button" class="sw" data-color="' + c + '" style="background:' + c + '"></button>'; }).join('') + '<button type="button" class="sw" data-color="" title="בלי צבע" style="background:var(--bg)"></button></div>' +
    (f.role ? '' : '<div class="row"><input type="text" id="ib-fname" value="' + esc(f.name) + '" dir="auto"><button type="button" class="ib-ic" data-op="rename">✏️ שם</button></div>') +
    '<div class="row"><input type="text" id="ib-fsub" placeholder="תת־תיקייה חדשה…" dir="auto"><button type="button" class="ib-ic" data-op="sub">➕</button></div>' +
    '<button type="button" class="it" data-op="readall">✓ סימון הכול כנקרא</button>' +
    (f.role === 'trash' || f.role === 'junk' ? '<button type="button" class="it" data-op="empty" style="color:var(--bad)">🧹 ריקון ' + (f.role === 'trash' ? 'האשפה' : 'הספאם') + ' (מחיקה לצמיתות)</button>' : '') +
    (f.role ? '' : '<button type="button" class="it" data-op="delete" style="color:var(--bad)">🗑️ ' + (gmail ? 'מחיקת התווית (המיילים נשארים)' : 'מחיקת התיקייה') + '</button>'), function(m){
    m.onclick = function(ev){
      var b = ev.target.closest('[data-op],[data-color]'); if (!b) return;
      if (b.hasAttribute('data-color')) { folderOp(acc, id, 'color', {color: b.dataset.color}); return; }
      var op = b.dataset.op;
      if (op === 'pin') folderOp(acc, id, 'pin', {on: f.pinned ? '' : '1'});
      else if (op === 'hide') folderOp(acc, id, 'hide', {on: f.hidden ? '' : '1'});
      else if (op === 'rename') folderOp(acc, id, 'rename', {name: $('ib-fname').value}).then(function(d){ if (d && S.folder === id) choose(acc, d.folder); });
      else if (op === 'sub') folderOp(acc, id, 'create', {name: $('ib-fsub').value}).then(function(d){ if (d) toast('🏷️ נוצרה'); });
      else if (op === 'readall') post('/inbox_act', {a: acc, f: id, uids: '', act: 'readall'}).then(function(d){ closeMenu(); toast('✓ ' + d.count + ' סומנו כנקראו'); loadFolders(acc, true); if (S.acc === acc && S.folder === id) loadList({quiet: 1}); }).catch(fail);
      else if (op === 'empty') { if (b.dataset.sure) post('/inbox_act', {a: acc, f: id, uids: '', act: 'empty'}).then(function(d){ closeMenu(); toast('🧹 נמחקו ' + d.count + ' הודעות'); loadFolders(acc, true); if (S.acc === acc && S.folder === id) loadList({quiet: 1}); }).catch(fail);
        else { b.dataset.sure = 1; b.textContent = '⚠️ ללחוץ שוב — אי אפשר לשחזר'; } }
      else if (op === 'delete') { if (b.dataset.sure) folderOp(acc, id, 'delete').then(function(d){ if (d && S.folder === id) choose(acc, 'INBOX'); }); else { b.dataset.sure = 1; b.textContent = '⚠️ ללחוץ שוב לאישור'; } }
    };
  });
}
function newLabel(btn){
  var acc = btn.dataset.newlabel;
  menu(btn, '<div class="row"><b>➕ תווית / תיקייה חדשה</b></div><div class="row"><input type="text" id="ib-fnew" placeholder="שם…" dir="auto"><button type="button" class="ib-ic" id="ib-fnew-ok">יצירה</button></div>', function(){
    var go = function(){ folderOp(acc, '', 'create', {name: $('ib-fnew').value}).then(function(d){ if (d) toast('🏷️ נוצרה'); }); };
    $('ib-fnew-ok').onclick = go; $('ib-fnew').onkeydown = function(ev){ if (ev.key === 'Enter') go(); };
  });
}

// ---- search options and display ----
function searchMenu(btn){
  menu(btn, '<div class="row"><b>🔍 חיפוש מתקדם</b></div>' +
    '<div class="row"><label style="min-width:52px">מאת</label><input type="text" id="ib-s-from" dir="auto"></div>' +
    '<div class="row"><label style="min-width:52px">אל</label><input type="text" id="ib-s-to" dir="auto"></div>' +
    '<div class="row"><label style="min-width:52px">נושא</label><input type="text" id="ib-s-subject" dir="auto"></div>' +
    '<div class="row"><label style="min-width:52px">מילים</label><input type="text" id="ib-s-words" dir="auto"></div>' +
    '<div class="row"><label style="min-width:52px">מתי</label><select id="ib-s-when"><option value="">כל הזמן</option><option value="newer_than:1d">היום</option><option value="newer_than:7d">השבוע</option><option value="newer_than:1m">החודש</option><option value="newer_than:1y">השנה</option><option value="older_than:1y">לפני יותר משנה</option></select></div>' +
    '<div class="row"><label style="min-width:52px">מתאריך</label><input type="date" id="ib-s-after"></div>' +
    '<div class="row"><label style="min-width:52px">עד</label><input type="date" id="ib-s-before"></div>' +
    '<div class="row"><label><input type="checkbox" id="ib-s-att"> 📎 עם קבצים</label><label><input type="checkbox" id="ib-s-star"> ⭐ עם כוכב</label><label><input type="checkbox" id="ib-s-big"> גדולים (5MB+)</label></div>' +
    '<div class="row"><button type="button" class="ib-ic on" id="ib-s-go">חיפוש</button><span class="muted" style="font-size:12px">אפשר גם לכתוב ישר: from: subject: has:attachment newer_than:7d</span></div>', function(){
    var go = function(){
      var q = [], v = function(id){ return $(id).value.trim(); }, word = function(x){ return /\s/.test(x) ? '"' + x + '"' : x; };
      if (v('ib-s-from')) q.push('from:' + word(v('ib-s-from'))); if (v('ib-s-to')) q.push('to:' + word(v('ib-s-to')));
      if (v('ib-s-subject')) q.push('subject:' + word(v('ib-s-subject'))); if ($('ib-s-when').value) q.push($('ib-s-when').value);
      if ($('ib-s-after').value) q.push('after:' + $('ib-s-after').value.replace(/-/g, '/'));
      if ($('ib-s-before').value) q.push('before:' + $('ib-s-before').value.replace(/-/g, '/'));
      if ($('ib-s-att').checked) q.push('has:attachment'); if ($('ib-s-star').checked) q.push('is:starred'); if ($('ib-s-big').checked) q.push('larger:5M');
      if (v('ib-s-words')) q.push(v('ib-s-words'));
      $('ib-q').value = S.q = q.join(' '); S.page = 0; closeMenu(); syncUrl(); loadList();
    };
    $('ib-s-go').onclick = go;
    Array.prototype.forEach.call($('ib-menu').querySelectorAll('input[type=text]'), function(i){ i.onkeydown = function(ev){ if (ev.key === 'Enter') go(); }; });
  });
}
var LOOK = (function(){ try { return JSON.parse(localStorage.getItem('ibx-look') || '{}'); } catch (e) { return {}; } })();
var FONTS = {Rubik: '', Heebo: 'Heebo:wght@400;500;700', 'Noto Sans Hebrew': 'Noto+Sans+Hebrew:wght@400;500;700', 'Assistant': 'Assistant:wght@400;600;700'};
function applyLook(){
  var box = $('ibx'); box.classList.toggle('dense', LOOK.density === 'dense'); box.classList.toggle('nopane', LOOK.pane === 'none');
  var font = LOOK.font && FONTS[LOOK.font] !== undefined ? LOOK.font : '';
  if (font && FONTS[font] && !document.getElementById('ib-font-' + font.replace(/ /g, ''))) {
    var l = document.createElement('link'); l.rel = 'stylesheet'; l.id = 'ib-font-' + font.replace(/ /g, '');
    l.href = 'https://fonts.googleapis.com/css2?family=' + FONTS[font] + '&display=swap'; document.head.appendChild(l);
  }
  box.style.fontFamily = font ? '"' + font + '",Rubik,system-ui,sans-serif' : '';
}
function lookMenu(btn){
  var opt = function(name, value, label){ return '<label style="display:flex;gap:6px;align-items:center;color:var(--ink);font-size:14px;padding:3px 0"><input type="radio" name="' + name + '" value="' + value + '"' + ((LOOK[name] || '') === value ? ' checked' : '') + '> ' + label + '</label>'; };
  menu(btn, '<div class="row"><b>🎛️ תצוגה</b></div>' +
    '<div class="row" style="display:block"><label>צפיפות הרשימה</label>' + opt('density', '', 'רגילה') + opt('density', 'dense', 'צפופה — יותר מיילים במסך') + '</div>' +
    '<div class="row" style="display:block"><label>חלונית קריאה</label>' + opt('pane', '', 'בצד הרשימה') + opt('pane', 'none', 'בלי — ההודעה נפתחת במקום הרשימה') + '</div>' +
    '<div class="row" style="display:block"><label>גופן</label>' + opt('font', '', 'Rubik') + opt('font', 'Heebo', 'Heebo') + opt('font', 'Noto Sans Hebrew', 'Noto Sans Hebrew') + opt('font', 'Assistant', 'Assistant') + '</div>', function(m){
    m.onchange = function(ev){ if (ev.target.name) { LOOK[ev.target.name] = ev.target.value; try { localStorage.setItem('ibx-look', JSON.stringify(LOOK)); } catch (e) {} applyLook(); } };
  });
}
function unreadTitle(){
  var n = 0; B.accounts.forEach(function(a){ var l = S.folders[a.email]; if (l && l.filter) l.forEach(function(f){ if (f.role === 'inbox') n += f.unread || 0; }); });
  if ($('ibx')) document.title = (n ? '(' + n + ') ' : '') + 'דואר נכנס · MailBrief';
}
function loadFolders(email, fresh){
  return api('/inbox_folders.json', {a: email, fresh: fresh ? 1 : ''}).then(function(d){ S.folders[email] = d.folders; drawFolders(); unreadTitle(); })
    .catch(function(e){ if (!S.folders[email]) S.folders[email] = {error: e.message}; drawFolders(); });
}
function loadAllFolders(fresh){ B.accounts.forEach(function(a){ if (fresh || !S.folders[a.email] || multi && S.acc === a.email) loadFolders(a.email, fresh); }); }

// ---- the list ----
function group(items){
  var map = {}, out = [];
  items.forEach(function(r){
    var key = (r.account || S.acc) + '|' + (r.thread || r.uid);
    if (!map[key]) { map[key] = {key: key, rows: [], account: r.account || S.acc}; out.push(map[key]); }
    map[key].rows.push(r);
  });
  out.forEach(function(g){ g.top = g.rows[0]; g.unread = g.rows.some(function(r){ return r.flags.indexOf('\\Seen') < 0; });
    g.star = g.rows.some(function(r){ return r.flags.indexOf('\\Flagged') >= 0; }); g.attach = g.rows.some(function(r){ return r.attach; }); });
  return out;
}
function rowName(r){
  var sentLike = /sent|drafts/.test(currentRole());
  if (sentLike && r.to && r.to.length) return 'אל: ' + r.to.map(function(t){ return t.name || t.email; }).join(', ');
  return r.from.name || r.from.email;
}
function currentRole(){ var l = S.folders[S.acc] || []; var f = (l.filter ? l : []).filter(function(x){ return x.id === S.folder; })[0]; return f ? f.role : (S.acc === '*' ? 'inbox' : ''); }
function drawList(){
  var rows = $('ib-rows');
  if (!S.groups.length) { rows.innerHTML = '<div class="ib-empty">' + (S.q ? '🔍 לא נמצאו הודעות' : S.unread ? '🎉 אין הודעות שלא נקראו' : '📭 התיקייה ריקה') + '</div>'; return; }
  rows.innerHTML = S.groups.map(function(g, i){
    var r = g.top, sel = S.open && S.open.account.toLowerCase() === g.account.toLowerCase() && g.rows.some(function(x){ return x.uid === S.open.uid; });
    return '<div class="ib-row' + (g.unread ? ' unread' : '') + (sel ? ' sel' : '') + (i === S.kb ? ' kb' : '') + '" data-i="' + i + '" draggable="true">' +
      '<div class="ck"><input type="checkbox" data-ck="' + i + '"' + (S.checked[g.key] ? ' checked' : '') + '><button type="button" class="ib-star' + (g.star ? ' on' : '') + '" data-star="' + i + '" title="כוכב (S)">⭐</button></div>' +
      '<div class="who" dir="auto">' + (multi && S.acc === '*' ? '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + color(g.account) + ';margin-inline-end:6px"></span>' : '') +
        esc(rowName(r)) + (g.rows.length > 1 ? '<span class="cnt">' + g.rows.length + '</span>' : '') + '</div>' +
      '<div class="when">' + (g.attach ? '📎 ' : '') + when(r.at) + '</div>' +
      '<div class="sub" dir="auto">' + esc(r.subject || '(ללא נושא)') + ' <span class="sn">— ' + esc(r.snippet) + '</span></div></div>';
  }).join('') + (S.total > (S.page + 1) * 50 ? '<div class="ib-more"><button class="ib-ic" type="button" id="ib-more">עוד הודעות ▾</button></div>' : '');
  drawBulk();
}
function drawBulk(){
  var n = Object.keys(S.checked).length; $('ib-bulk').classList.toggle('on', n > 0); $('ib-bulk-n').textContent = n ? n + ' נבחרו' : '';
  $('ib-all').checked = n > 0 && n === S.groups.length;
}
var listSeq = 0;
function loadList(opts){
  opts = opts || {}; var seq = ++listSeq;
  var params = {a: S.acc, f: S.folder, p: opts.more ? S.page : 0, q: S.q, unread: S.unread ? 1 : ''};
  if (!opts.more && !opts.quiet && !S.items.length) $('ib-rows').innerHTML = '<div class="ib-empty">טוען…</div>';
  var show = function(d, cached){
    if (seq !== listSeq) return;
    S.items = opts.more ? S.items.concat(d.items) : d.items; S.total = d.total;
    if (!opts.more && !cached) { var keep = {}; group(S.items).forEach(function(g){ if (S.checked[g.key]) keep[g.key] = 1; }); S.checked = keep; }
    S.groups = group(S.items); drawList();
    if (d.offline) toast('📴 אין חיבור — מוצגת הרשימה האחרונה ששמורה במחשב');
    if (d.errors && d.errors.length) toast('⚠️ ' + d.errors[0]);
  };
  if (!opts.more && !S.q && !S.unread && !opts.quiet) api('/inbox_list.json', Object.assign({}, params, {cached: 1})).then(function(d){ if (d.items.length && !S.items.length) show(d, true); }).catch(function(){});
  return api('/inbox_list.json', params).then(function(d){ show(d, false); }).catch(function(e){ if (seq === listSeq && !S.items.length) $('ib-rows').innerHTML = '<div class="ib-empty">⚠️ ' + esc(e.message) + '</div>'; });
}
function choose(acc, folder){
  S.acc = acc; S.folder = folder; S.page = 0; S.items = []; S.groups = []; S.checked = {}; S.kb = -1;
  drawFolders(); syncUrl(); loadList();
  if (acc !== '*' && !S.folders[acc]) loadFolders(acc);
}
function selectedRefs(){
  var refs = [];
  S.groups.forEach(function(g){ if (S.checked[g.key]) g.rows.forEach(function(r){ refs.push({a: g.account, f: r.folder || S.folder, u: r.uid}); }); });
  return refs;
}
function act(what, refs, extra){
  var by = {};
  refs.forEach(function(r){ var k = r.a + '\u0001' + r.f; (by[k] = by[k] || []).push(r.u); });
  var gone = /archive|delete|spam|notspam|move/.test(what);
  if (gone) {                                         // instant: off the list now, the server catches up
    var drop = {}; refs.forEach(function(r){ drop[r.a.toLowerCase() + '|' + r.u] = 1; });
    S.items = S.items.filter(function(x){ return !drop[(x.account || S.acc).toLowerCase() + '|' + x.uid]; }); S.groups = group(S.items); S.checked = {};
    if (S.open && drop[S.open.account.toLowerCase() + '|' + S.open.uid]) { var next = S.groups[Math.min(S.kb < 0 ? 0 : S.kb, S.groups.length - 1)]; closeMessage(); if (next) openGroup(S.groups.indexOf(next)); }
    drawList();
  } else {
    refs.forEach(function(r){ S.items.forEach(function(x){ if (x.uid === r.u && (x.account || S.acc).toLowerCase() === r.a.toLowerCase()) {
      var fl = {read: ['\\Seen', 1], unread: ['\\Seen', 0], star: ['\\Flagged', 1], unstar: ['\\Flagged', 0]}[what];
      if (fl) { var i = x.flags.indexOf(fl[0]); if (fl[1] && i < 0) x.flags.push(fl[0]); if (!fl[1] && i >= 0) x.flags.splice(i, 1); } } }); });
    S.groups = group(S.items); drawList();
  }
  var jobs = Object.keys(by).map(function(k){ var p = k.split('\u0001');
    return post('/inbox_act', Object.assign({a: p[0], f: p[1], uids: by[k].join(','), act: what}, extra || {})); });
  return Promise.all(jobs).then(function(res){
    var label = {archive: '🗄️ הועבר לארכיון', delete: '🗑️ נמחק', spam: '🚫 סומן כספאם', notspam: '📥 הוחזר לדואר הנכנס', move: '📁 הועבר'}[what];
    var keys = Object.keys(by), undo = res.map(function(r, i){ return r && r.undo ? {a: keys[i].split('\u0001')[0], u: r.undo} : null; }).filter(Boolean);
    if (label && undo.length === res.length) toast(label + (refs.length > 1 ? ' (' + refs.length + ')' : ''), '↩️ ביטול', function(){
      Promise.all(undo.map(function(x){ return post('/inbox_act', {a: x.a, f: x.u.folder, uids: x.u.uids.join(','), act: 'move', to: x.u.back}); }))
        .then(function(){ toast('↩️ הוחזר'); loadList({quiet: 1}); loadAllFolders(true); }).catch(fail);
    }, 10);
    else if (label) toast(label + (refs.length > 1 ? ' (' + refs.length + ')' : ''));
    loadAllFolders(true);
  }).catch(function(e){ fail(e); loadList({quiet: 1}); });
}

// ---- reading ----
function closeMessage(){ S.open = null; $('ibx').classList.remove('reading'); syncUrl(); drawHome(); }
function ago(iso){
  if (!iso) return ''; var m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 60 ? 'לפני ' + Math.max(1, m) + ' דק׳' : m < 1440 ? 'לפני ' + Math.round(m / 60) + ' שע׳' : 'לפני ' + Math.round(m / 1440) + ' ימים';
}
var homeSeq = 0;
function drawHome(){
  var seq = ++homeSeq;
  $('ib-read').innerHTML = '<div class="ib-home"><h3>🏠 סקירה</h3><div class="muted">טוען…</div></div>';
  api('/inbox_overview.json').then(function(d){
    if (seq !== homeSeq || S.open) return;
    var max = 1, total = [0, 0, 0, 0, 0, 0, 0];
    d.accounts.forEach(function(a){ a.days.forEach(function(n, i){ total[i] += n; }); }); total.forEach(function(n){ max = Math.max(max, n); });
    var html = '<div class="ib-home"><h3>🏠 סקירה</h3><div class="ib-accs">' + d.accounts.map(function(a){
      return '<div class="ib-acc-card" data-goacc="' + esc(a.email) + '" style="border-inline-start:4px solid ' + color(a.email) + '"><span class="muted" style="font-size:12px">' + esc(a.email) + '</span>' +
        (a.ok ? '<b>' + a.unread + '</b><span class="muted" style="font-size:13px">לא נקראו' + (a.newest ? ' · החדש ' + ago(a.newest) : '') + '</span><div style="font-size:12px;color:var(--good)">● מחובר</div>'
              : '<div style="color:var(--bad);font-size:13px;margin-top:6px">⚠️ לא מחובר — ' + esc(a.error || '') + '</div>') + '</div>';
    }).join('') + '</div><h3>📊 המייל שנכנס השבוע</h3><div class="ib-week">' + total.map(function(n, i){
      var day = new Date(d.week[i]);
      return '<div title="' + n + ' מיילים"><span>' + n + '</span><i style="height:' + Math.round(70 * n / max) + 'px"></i>' + day.toLocaleDateString('he-IL', {weekday: 'short'}) + '</div>';
    }).join('') + '</div>' + (d.latest.length ? '<h3>✉️ אחרונים שלא נקראו</h3><div class="ib-late">' + d.latest.map(function(r){
      return '<div data-goopen="' + esc(r.account) + '\u0001' + r.uid + '">' + (multi ? '<span style="color:' + color(r.account) + '">●</span> ' : '') + '<b dir="auto">' + esc(r.from.name || r.from.email) + '</b> · ' + when(r.at) + ' — <span dir="auto">' + esc(r.subject || '(ללא נושא)') + '</span></div>';
    }).join('') + '</div>' : '<p class="muted">🎉 אין מיילים שלא נקראו</p>') +
      '<p class="muted" style="font-size:12px;margin-top:18px">' + new Date().toLocaleDateString('he-IL-u-ca-hebrew', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'}) + ' · ' + new Date().toLocaleDateString('he-IL', {day: 'numeric', month: 'long', year: 'numeric'}) + '</p></div>';
    $('ib-read').innerHTML = html;
  }).catch(function(e){ if (seq === homeSeq && !S.open) $('ib-read').innerHTML = '<div class="ib-none">⚠️ ' + esc(e.message) + '</div>'; });
}
function openGroup(i){
  var g = S.groups[i]; if (!g) return; S.kb = i;
  var r = g.rows[0]; openMessage(g.account, r.folder || S.folder, r.uid);
  g.rows.forEach(function(x){ if (x.flags.indexOf('\\Seen') < 0) x.flags.push('\\Seen'); }); g.unread = false; drawList();
}
function openMessage(acc, folder, uid){
  S.open = {account: acc, folder: folder, uid: +uid}; S.imgs = false; syncUrl(); $('ibx').classList.add('reading');
  $('ib-read').innerHTML = '<div class="ib-none">טוען…</div>';
  api('/inbox_msg.json', {a: acc, f: folder, u: uid}).then(function(m){
    if (!S.open || S.open.uid !== m.uid) return; S.open = m; S.imgs = m.images; drawMessage(); setTimeout(function(){ loadAllFolders(true); }, 800);
  }).catch(function(e){ $('ib-read').innerHTML = '<div class="ib-none">⚠️ ' + esc(e.message) + '</div>'; });
}
function folderOptions(acc){
  var l = S.folders[acc]; if (!l || !l.filter) return '';
  return '<select id="ib-move" title="העברה לתיקייה"><option value="">📁 העברה ל…</option>' + l.filter(function(f){ return f.id !== S.open.folder; }).map(function(f){ return '<option value="' + esc(f.id) + '">' + esc(f.icon + ' ' + (f.path || f.name)) + '</option>'; }).join('') + '</select>';
}
function people(list){ return list.map(function(p){ return '<span title="' + esc(p.email) + '">' + esc(p.name || p.email) + '</span>'; }).join(', '); }
function drawMessage(){
  var m = S.open, c = m.contact, ref = 'a=' + encodeURIComponent(m.account) + '&f=' + encodeURIComponent(m.folder) + '&u=' + m.uid;
  var tools = '<button class="ib-ic ib-back" type="button" data-m="back">→ חזרה</button>' +
    (m.draft ? '<button class="ib-ic" type="button" data-m="edit">✏️ המשך כתיבה</button>' :
     '<button class="ib-ic" type="button" data-m="reply" title="תשובה (R)">↩️ תשובה</button><button class="ib-ic" type="button" data-m="all" title="תשובה לכולם (A)">↩️↩️</button><button class="ib-ic" type="button" data-m="fwd" title="העברה (F)">↪️</button>') +
    '<span style="width:8px"></span>' + (m.can.archive && m.role !== 'all' ? '<button class="ib-ic" type="button" data-m="archive" title="ארכיון (E)">🗄️</button>' : '') + '<button class="ib-ic" type="button" data-m="delete" title="מחיקה (#)">🗑️</button>' +
    '<button class="ib-ic' + (m.flagged ? ' on' : '') + '" type="button" data-m="star" title="כוכב (S)">⭐</button><button class="ib-ic" type="button" data-m="unread" title="סימון כלא נקרא (U)">●</button>' +
    (m.can.spam ? '<button class="ib-ic" type="button" data-m="' + (m.role === 'junk' ? 'notspam' : 'spam') + '" title="' + (m.role === 'junk' ? 'לא ספאם' : 'ספאם') + '">' + (m.role === 'junk' ? '📥' : '🚫') + '</button>' : '') + folderOptions(m.account) +
    (m.translate ? '<button class="ib-ic" type="button" data-m="translate" title="תרגום לעברית ב-Google Translate (הטקסט נשלח ל-Google)">🌐 תרגום</button>' : '') +
    '<select id="ib-more-act" title="עוד פעולות"><option value="">⋯ עוד</option><option value="remind1">⏰ תזכורת מחר</option><option value="remind3">⏰ תזכורת בעוד 3 ימים</option><option value="remind7">⏰ תזכורת בעוד שבוע</option><option value="remind_date">📅 תזכורת בתאריך…</option>' +
    '<option value="snooze_tomorrow8">💤 נודניק עד מחר בבוקר</option><option value="snooze_week">💤 נודניק לשבוע</option>' + (m.gapps ? '<option value="task">✅ משימה ב-Google</option>' : '') +
    '<option value="receipt">🧾 לשמור כקבלה / חשבונית</option>' + (m.unsub ? '<option value="unsub">🔕 ביטול מנוי לשולח</option>' : '') +
    '<option value="files">💾 שמירת כל הקבצים בהורדות</option><option value="print">🖨️ הדפסה</option><option value="block">🚫 חסימת השולח</option>' +
    (m.gmail ? '<option value="gmail">🔗 פתיחה ב-Gmail</option>' : '') + '<option value="original">🧾 הצגת המקור (EML)</option></select>';
  var meta = '<div class="ib-meta">' + avatar(m.from.name, m.from.email) + '<div style="flex:1;min-width:0"><b dir="auto">' + esc(m.from.name || m.from.email) + '</b> <span dir="ltr">&lt;' + esc(m.from.email) + '&gt;</span><br>' +
    'אל: ' + people(m.to) + (m.cc.length ? ' · עותק: ' + people(m.cc) : '') + (multi ? ' · <span style="color:' + color(m.account) + '">●</span> ' + esc(m.account) : '') + '</div>' +
    '<div style="white-space:nowrap;text-align:end">' + (m.date ? new Date(m.date).toLocaleString('he-IL', {dateStyle: 'medium', timeStyle: 'short'}) +
      '<br><span style="font-size:12px">' + new Date(m.date).toLocaleDateString('he-IL-u-ca-hebrew', {day: 'numeric', month: 'long', year: 'numeric'}) + '</span>' : '') + '</div></div>';
  var card = '';
  if (c && (c.emails || c.docs || c.client)) {
    card = '<div class="ib-card">👤' + (c.client ? '<span>לקוח: <a href="/client?key=' + encodeURIComponent(c.client.key) + '">' + esc(c.client.name) + '</a></span>' : '') +
      (c.emails ? '<span>📨 ' + c.emails + ' מיילים' + (c.last ? ' · אחרון ' + new Date(c.last).toLocaleDateString('he-IL') : '') + '</span>' : '') +
      (c.answered_pct != null ? '<span>↩️ ענית על ' + c.answered_pct + '%</span>' : '') + (c.reply_hours != null ? '<span>⏱️ בד"כ תוך ' + (c.reply_hours < 24 ? Math.round(c.reply_hours) + ' שעות' : Math.round(c.reply_hours / 24) + ' ימים') + '</span>' : '') +
      (c.waiting ? '<span style="color:var(--warn)">⏳ ' + c.waiting + ' מחכים לתשובה</span>' : '') + (c.docs ? '<span>🧾 ' + c.docs + ' מסמכים · ₪' + c.docs_total.toLocaleString('he-IL') + '</span>' : '') +
      (c.phone ? '<span>📱 <a href="https://wa.me/972' + esc(c.phone.replace(/^0/, '')) + '" target="_blank">' + esc(c.phone) + '</a></span>' : '') + '</div>';
  } else if (c && !c.emails) card = '<div class="ib-card">👤 שולח חדש — עוד לא התכתבת איתו</div>';
  var warn = m.phishing ? '<div class="ib-warn">🎣 <b>זהירות — ייתכן שזו הונאה:</b> ' + m.phishing.why.map(esc).join(' · ') + '. לא ללחוץ על קישורים ולא לשלוח פרטים.</div>' : '';
  var imgs = m.blocked && !S.imgs ? '<div class="ib-imgs">📷 ' + (m.blocked === 1 ? 'תמונה אחת מהאינטרנט הוסתרה' : m.blocked + ' תמונות מהאינטרנט הוסתרו') + ' (הן מגלות לשולח שפתחת) <button type="button" data-m="imgs">הצגה</button> · <button type="button" data-m="imgs_always">תמיד מהשולח הזה</button></div>' : '';
  var earlier = m.earlier.length ? '<div class="ib-earlier">' + m.earlier.map(function(e){ return '<div data-open="' + esc(e.folder) + '\u0001' + e.uid + '" title="לחיצה: פתיחה כאן · לחיצה כפולה: כהודעה מלאה">🗨️ <b>' + esc(e.from.name || e.from.email) + '</b> · ' + when(e.at) + ' — ' + esc(e.subject) + '</div>'; }).join('') + '</div>' : '';
  var files = m.files.length ? '<div class="ib-files">' + m.files.map(function(f){ var u = '/inbox_file?' + ref + '&n=' + f.n;
      return '<div class="ib-file">📄 <span dir="auto">' + esc(f.name) + '</span> <span class="muted">' + sizeOf(f.size) + '</span>' +
        (f.view ? '<button type="button" data-view="' + f.n + '">👁️ צפייה</button>' : '') + '<button type="button" data-file="' + f.n + '">פתיחה</button><button type="button" data-save="' + f.n + '">שמירה</button></div>'; }).join('') +
      (m.files.length > 1 ? '<button class="ib-ic" type="button" data-m="allfiles" style="font-size:13px">💾 כל הקבצים</button>' : '') + '</div>' : '';
  var labels = (m.labels || []).filter(function(l){ return !/^\\\\/.test(l); }).map(function(l){ return '<span class="pill">' + esc(l) + '</span>'; }).join('');
  $('ib-read').innerHTML = '<div class="ib-mtools">' + tools + '</div><div class="ib-scroll"><div class="ib-head"><h2>' + esc(m.subject || '(ללא נושא)') + ' ' + labels + '</h2>' + meta + '</div>' +
    warn + card + earlier + imgs + '<div class="ib-body"><iframe title="תוכן ההודעה" referrerpolicy="no-referrer" src="/inbox_body?' + ref + (S.imgs ? '&img=1' : '') + '"></iframe></div>' + files +
    (m.draft ? '' : '<div class="ib-quick"><button class="ib-ic" type="button" data-m="reply">↩️ תשובה</button><button class="ib-ic" type="button" data-m="all">↩️↩️ לכולם</button><button class="ib-ic" type="button" data-m="fwd">↪️ העברה</button></div>') + '</div>';
  var mv = $('ib-move'); if (mv) mv.onchange = function(){ if (mv.value) act('move', [{a: m.account, f: m.folder, u: m.uid}], {to: mv.value}); };
  var more = $('ib-more-act'); more.onchange = function(){ var v = more.value; more.value = ''; if (v) tool(v); };
}
function tool(v){
  var m = S.open, ref = {a: m.account, f: m.folder, u: m.uid};
  if (v === 'gmail') { window.open(m.gmail, '_blank'); return; }
  if (v === 'print') { window.open('/inbox_print?a=' + encodeURIComponent(m.account) + '&f=' + encodeURIComponent(m.folder) + '&u=' + m.uid, '_blank'); return; }
  if (v === 'block' && !confirmTwice('block', '🚫 לחסום את ' + m.from.email + '? לבחור שוב כדי לאשר')) return;
  if (v === 'original') { window.open('/inbox_file?a=' + encodeURIComponent(m.account) + '&f=' + encodeURIComponent(m.folder) + '&u=' + m.uid + '&n=eml', '_blank'); return; }
  if (v === 'remind_date') {
    menu($('ib-more-act'), '<div class="row"><b>⏰ תזכורת על המייל הזה</b></div><div class="row"><input type="datetime-local" id="ib-rem-at"></div><div class="row"><button type="button" class="ib-ic on" id="ib-rem-ok">קביעה</button></div>', function(){
      var at = $('ib-rem-at'), t = new Date(Date.now() + 864e5); t.setHours(9, 0, 0, 0);
      at.value = new Date(t.getTime() - t.getTimezoneOffset() * 6e4).toISOString().slice(0, 16); at.dispatchEvent(new Event('change'));
      $('ib-rem-ok').onclick = function(){ if (!at.value) return; closeMenu(); post('/inbox_tool', Object.assign({tool: 'remind_at', at: at.value}, ref)).then(function(d){ toast(d.msg); }).catch(fail); };
    });
    return;
  }
  post('/inbox_tool', Object.assign({tool: v}, ref)).then(function(d){
    if (d.open) window.open(d.open, '_blank');
    toast(d.msg || '✓');
    if (/^snooze/.test(v)) { S.items = S.items.filter(function(x){ return x.uid !== m.uid; }); S.groups = group(S.items); drawList(); closeMessage(); }
  }).catch(fail);
}

// ---- writing ----
function fillFrom(acc){
  $('ib-c-from').innerHTML = B.accounts.map(function(a){ return '<option value="' + esc(a.email) + '"' + (a.email.toLowerCase() === (acc || '').toLowerCase() ? ' selected' : '') + '>' + esc((a.name ? a.name + ' · ' : '') + a.email) + '</option>'; }).join('');
}
var peopleLoaded = false;
function compose(mode){
  var src = S.open && mode !== 'new' ? S.open : null;
  var acc = src ? src.account : (S.acc !== '*' ? S.acc : B.accounts[0].email);
  if (!peopleLoaded) { peopleLoaded = true; api('/inbox_people.json').then(function(d){ $('ib-people').innerHTML = d.people.map(function(p){ return '<option value="' + esc(p.email) + '">' + esc(p.name) + '</option>'; }).join(''); }).catch(function(){}); }
  var start = function(d){
    S.comp = {mode: d.mode, ref: src ? {a: src.account, f: src.folder, u: src.uid} : null, draft: d.mode === 'edit' ? {f: src.folder, u: src.uid} : null, files: [], dirty: false};
    fillFrom(d.account || acc); $('ib-c-to').value = d.to || ''; $('ib-c-cc').value = d.cc || ''; $('ib-c-bcc').value = d.bcc || '';
    $('ib-c-ccrow').hidden = !d.cc; $('ib-c-bccrow').hidden = !d.bcc; $('ib-c-subject').value = d.subject || ''; $('ib-c-body').innerText = d.body || '';
    $('ib-c-title').textContent = {new: '✏️ הודעה חדשה', reply: '↩️ תשובה', all: '↩️↩️ תשובה לכולם', fwd: '↪️ העברה', edit: '📝 טיוטה'}[d.mode];
    $('ib-c-qrow').style.display = /reply|all|fwd/.test(d.mode) ? '' : 'none'; $('ib-c-quote').checked = true;
    $('ib-c-note').textContent = d.files && d.files.length ? '📎 הקבצים של ההודעה המקורית יצורפו: ' + d.files.join(', ') : '';
    $('ib-c-files').value = ''; $('ib-c-fn').textContent = ''; $('ib-c-when').value = 'now'; $('ib-c-at').value = ''; whenChanged();
    $('ib-comp').classList.add('on'); (d.to ? $('ib-c-body') : $('ib-c-to')).focus();
    if (d.to) { var r = document.createRange(), sel = window.getSelection(); r.setStart($('ib-c-body'), 0); r.collapse(true); sel.removeAllRanges(); sel.addRange(r); $('ib-c-body').scrollTop = 0; }
    clearInterval(S.autosave); S.autosave = setInterval(function(){ if (S.comp && S.comp.dirty) { S.comp.dirty = false; saveDraft(true).then(function(){ $('ib-c-note').textContent = '💾 נשמר בטיוטות ' + new Date().toLocaleTimeString('he-IL', {hour: '2-digit', minute: '2-digit'}); }).catch(function(){}); } }, 30000);
  };
  if (!src) start({mode: 'new', account: acc}); else api('/inbox_compose.json', {mode: mode, a: src.account, f: src.folder, u: src.uid}).then(start).catch(fail);
}
function compFields(){
  var c = S.comp, f = {a: $('ib-c-from').value, to: $('ib-c-to').value, cc: $('ib-c-cc').value, bcc: $('ib-c-bcc').value, subject: $('ib-c-subject').value,
    body: $('ib-c-body').innerText, html: hasFormat() ? $('ib-c-body').innerHTML : '', mode: c.mode, quote: $('ib-c-quote').checked ? 1 : '', when: $('ib-c-when').value,
    at: $('ib-c-at').value};
  if (c.ref) { f.ref_a = c.ref.a; f.ref_f = c.ref.f; f.ref_u = c.ref.u; }
  if (c.draft) { f.draft_f = c.draft.f; f.draft_u = c.draft.u; }
  return f;
}
function whenChanged(){
  var custom = $('ib-c-when').value === 'custom', at = $('ib-c-at'), btn = at.nextElementSibling, heb = btn && btn.nextElementSibling;
  at.hidden = !custom; [btn, heb].forEach(function(x){ if (x && /hp-/.test(x.className)) x.hidden = !custom; });   // the picker's 📅 and Hebrew date
  if (custom) { var soon = new Date(Date.now() + 3600e3); at.min = new Date(Date.now() - soon.getTimezoneOffset() * 6e4).toISOString().slice(0, 16);
    if (!at.value) at.value = new Date(soon.getTime() - soon.getTimezoneOffset() * 6e4).toISOString().slice(0, 14) + '00';
    if (window.HebPicker) { at.dispatchEvent(new Event('change')); window.HebPicker.open(at); } }
  $('ib-c-send').textContent = $('ib-c-when').value === 'now' ? 'שליחה ➤' : '🕒 תזמון';
}
function closeComp(){ $('ib-comp').classList.remove('on', 'big'); S.comp = null; clearInterval(S.autosave); }
function hasFormat(){ return /<(b|strong|i|em|u|s|strike|ol|ul|a|font|span|h\d|blockquote)\b|style=|dir=/i.test($('ib-c-body').innerHTML); }
function fmt(cmd, value){
  var body = $('ib-c-body'); body.focus();
  if (cmd === 'link') { var sel = String(window.getSelection()); menu($('ib-fmt'), '<div class="row"><b>🔗 קישור</b></div><div class="row"><input type="text" id="ib-link" dir="ltr" placeholder="https://"><button type="button" class="ib-ic" id="ib-link-ok">הוספה</button></div>', function(){
      var range = window.getSelection().rangeCount ? window.getSelection().getRangeAt(0) : null;
      var go = function(){ var url = $('ib-link').value.trim(); if (!/^(https?:|mailto:)/i.test(url)) url = 'https://' + url; closeMenu(); body.focus();
        if (range) { var s2 = window.getSelection(); s2.removeAllRanges(); s2.addRange(range); }
        if (sel) document.execCommand('createLink', false, url); else document.execCommand('insertHTML', false, '<a href="' + esc(url) + '">' + esc(url) + '</a>'); S.comp.dirty = true; };
      $('ib-link-ok').onclick = go; $('ib-link').onkeydown = function(ev){ if (ev.key === 'Enter') go(); }; }); return; }
  if (cmd === 'rtl' || cmd === 'ltr') { var node = window.getSelection().anchorNode; var el = node && (node.nodeType === 1 ? node : node.parentElement);
    while (el && el !== body && !/^(DIV|P|LI|BLOCKQUOTE)$/.test(el.tagName)) el = el.parentElement;
    if (!el || el === body) { document.execCommand('formatBlock', false, 'div'); node = window.getSelection().anchorNode; el = node && (node.nodeType === 1 ? node : node.parentElement); }
    if (el && el !== body) { el.setAttribute('dir', cmd); el.style.textAlign = cmd === 'rtl' ? 'right' : 'left'; } S.comp.dirty = true; return; }
  if (cmd === 'template') {
    api('/inbox_templates.json').then(function(d){
      menu($('ib-fmt'), '<div class="row"><b>📋 תבניות תשובה</b></div>' + d.templates.map(function(t, i){ return '<button type="button" class="it" data-t="' + i + '">' + esc(t.name) + '</button>'; }).join('') +
        '<div class="row"><a href="/?s=auto#templates" class="muted" style="font-size:12px">עריכת התבניות בהגדרות</a></div>', function(m){
        m.onclick = function(ev){ var b = ev.target.closest('[data-t]'); if (!b) return; closeMenu(); body.focus();
          var name = S.open && S.comp && S.comp.ref ? (S.open.from.name || '').split(' ')[0] : '';
          document.execCommand('insertText', false, d.templates[+b.dataset.t].text.replace(/\{from_name\}/g, name).replace(/\{[a-z_]+\}/g, '')); S.comp.dirty = true; };
      });
    }).catch(fail);
    return;
  }
  if (cmd === 'big') { document.execCommand('fontSize', false, '5'); S.comp.dirty = true; return; }
  if (cmd === 'color') { document.execCommand('styleWithCSS', false, true); document.execCommand('foreColor', false, value); document.execCommand('styleWithCSS', false, false); S.comp.dirty = true; return; }
  document.execCommand(cmd, false, null); S.comp.dirty = true;
}
function addFiles(list){
  var input = $('ib-c-files'), dt = new DataTransfer();
  Array.prototype.forEach.call(input.files, function(f){ dt.items.add(f); }); Array.prototype.forEach.call(list, function(f){ dt.items.add(f); });
  input.files = dt.files; input.onchange();
}
function send(){
  var btn = $('ib-c-send'); btn.disabled = true;
  post('/inbox_send', compFields(), Array.prototype.slice.call($('ib-c-files').files)).then(function(d){
    closeComp();
    if (d.id) toast(d.msg, '↩️ ביטול', function(){ post('/inbox_cancel', {id: d.id}).then(function(){ toast('✓ השליחה בוטלה'); }).catch(fail); }, d.undo || 10);
    else toast(d.msg);
  }).catch(fail).then(function(){ btn.disabled = false; });
}
function saveDraft(silent){
  if (!S.comp) return Promise.resolve();
  if (S.comp.saving) return S.comp.saving.then(function(){ return saveDraft(silent); });
  var f = compFields(); if (!f.to.trim() && !f.subject.trim() && !f.body.trim()) return Promise.resolve();
  var comp = S.comp;
  comp.saving = post('/inbox_draft', f).then(function(d){ comp.draft = {f: d.folder, u: d.uid}; if (!silent) toast('💾 נשמר בטיוטות'); })
    .then(function(){ comp.saving = null; }, function(e){ comp.saving = null; throw e; });
  return comp.saving;
}

// ---- events ----
$('ibx').addEventListener('click', function(ev){
  var t = ev.target, el;
  if ((el = t.closest('[data-ck]'))) {
    var i0 = +el.dataset.ck, g = S.groups[i0];
    if (ev.shiftKey && S.lastCk != null) {                // ⇧ + click: everything between
      for (var k = Math.min(S.lastCk, i0); k <= Math.max(S.lastCk, i0); k++) { if (el.checked) S.checked[S.groups[k].key] = 1; else delete S.checked[S.groups[k].key]; }
      S.lastCk = i0; drawList(); return;
    }
    S.lastCk = i0; if (el.checked) S.checked[g.key] = 1; else delete S.checked[g.key]; drawBulk(); return; }
  if ((el = t.closest('[data-star]'))) { var g2 = S.groups[+el.dataset.star]; act(g2.star ? 'unstar' : 'star', g2.rows.map(function(r){ return {a: g2.account, f: r.folder || S.folder, u: r.uid}; })); return; }
  if ((el = t.closest('.ib-row'))) { openGroup(+el.dataset.i); return; }
  if ((el = t.closest('[data-toggle]'))) { var a = B.accounts.filter(function(x){ return x.email === el.dataset.toggle; })[0]; a.open = !a.open; if (!S.folders[a.email]) loadFolders(a.email); drawFolders(); return; }
  if ((el = t.closest('[data-newlabel]'))) { newLabel(el); return; }
  if ((el = t.closest('[data-showhidden]'))) { S.showHidden = !S.showHidden; S.labelsOpen = true; drawFolders(); return; }
  if ((el = t.closest('.ib-f'))) { choose(el.dataset.acc, el.dataset.folder); return; }
  if ((el = t.closest('[data-goacc]'))) { choose(el.dataset.goacc, 'INBOX'); return; }
  if ((el = t.closest('[data-goopen]'))) { var g2p = el.dataset.goopen.split('\u0001'); openMessage(g2p[0], 'INBOX', g2p[1]); return; }
  if ((el = t.closest('[data-view]'))) { viewFile(+el.dataset.view); return; }
  if ((el = t.closest('[data-bulk]'))) { var refs = selectedRefs(); if (refs.length) act(el.dataset.bulk, refs); return; }
  if ((el = t.closest('[data-do=compose]'))) { compose('new'); return; }
  if (t.id === 'ib-more') { S.page++; loadList({more: 1}); return; }
  if ((el = t.closest('[data-open]'))) {                // 🗨️ an earlier message of the conversation, opened right here
    var p = el.dataset.open.split('\u0001'), next = el.nextElementSibling;
    if (ev.detail > 1) { openMessage(S.open.account, p[0], p[1]); return; }
    if (next && next.classList.contains('ib-inline')) { next.remove(); return; }
    var box = document.createElement('section'); box.className = 'ib-inline';
    box.innerHTML = '<iframe title="הודעה קודמת" referrerpolicy="no-referrer" src="/inbox_body?a=' + encodeURIComponent(S.open.account) + '&f=' + encodeURIComponent(p[0]) + '&u=' + p[1] + '"></iframe>';
    el.insertAdjacentElement('afterend', box); return; }
  if ((el = t.closest('[data-file]'))) { post('/inbox_save', {a: S.open.account, f: S.open.folder, u: S.open.uid, n: el.dataset.file, open: 1}).then(function(d){ toast(d.msg); }).catch(fail); return; }
  if ((el = t.closest('[data-save]'))) { post('/inbox_save', {a: S.open.account, f: S.open.folder, u: S.open.uid, n: el.dataset.save}).then(function(d){ toast(d.msg); }).catch(fail); return; }
  if ((el = t.closest('[data-m]'))) msgAction(el.dataset.m);
});
function msgAction(k){
  var m = S.open; if (!m) return; var ref = [{a: m.account, f: m.folder, u: m.uid}];
  if (!m.files && !/^(back|reply|all|fwd|archive|delete|unread|spam|notspam)$/.test(k)) return;   // still loading
  if (k === 'back') { closeMessage(); return; }
  if (/^(reply|all|fwd|edit)$/.test(k)) { compose(k); return; }
  if (k === 'imgs') { S.imgs = true; drawMessage(); return; }
  if (k === 'translate') { window.open(m.translate, '_blank'); return; }
  if (k === 'allfiles') { tool('files'); return; }
  if (k === 'imgs_always') { post('/inbox_tool', {tool: 'images', a: m.account, f: m.folder, u: m.uid}).then(function(){ S.imgs = true; drawMessage(); }).catch(fail); return; }
  if (k === 'star') { m.flagged = !m.flagged; act(m.flagged ? 'star' : 'unstar', ref); drawMessage(); return; }
  if (k === 'unread') { act('unread', ref); closeMessage(); return; }
  act(k, ref);
}
$('ib-q').value = S.q;
var qTimer; $('ib-q').addEventListener('input', function(){ clearTimeout(qTimer); qTimer = setTimeout(function(){ S.q = $('ib-q').value.trim(); S.page = 0; syncUrl(); loadList(); }, 450); });
$('ib-unread').onclick = function(){ S.unread = !S.unread; this.classList.toggle('on', S.unread); S.page = 0; loadList(); };
$('ib-refresh').onclick = function(){ loadList({quiet: 1}); loadAllFolders(true); if (!S.open) drawHome(); };
$('ib-adv').onclick = function(){ if ($('ib-menu').classList.contains('on')) closeMenu(); else searchMenu(this); };
$('ib-look').onclick = function(){ if ($('ib-menu').classList.contains('on')) closeMenu(); else lookMenu(this); };
$('ib-folders').addEventListener('contextmenu', function(ev){ var b = ev.target.closest('.ib-f[data-folder]'); if (b && b.dataset.acc !== '*') { ev.preventDefault(); folderMenu(b); } });
$('ib-fmt').addEventListener('mousedown', function(ev){ var b = ev.target.closest('button'); if (!b) return; ev.preventDefault(); if (b.dataset.color) fmt('color', b.dataset.color); else fmt(b.dataset.cmd); });
$('ib-c-body').addEventListener('input', function(){ if (S.comp) S.comp.dirty = true; });
['ib-c-to', 'ib-c-cc', 'ib-c-bcc', 'ib-c-subject'].forEach(function(id){ $(id).addEventListener('input', function(){ if (S.comp) S.comp.dirty = true; }); });
$('ib-c-body').addEventListener('paste', function(ev){
  var files = ev.clipboardData && ev.clipboardData.files; if (files && files.length) { ev.preventDefault(); addFiles(files); return; }
  var html = ev.clipboardData && ev.clipboardData.getData('text/html');
  if (html) { ev.preventDefault(); document.execCommand('insertText', false, ev.clipboardData.getData('text/plain')); }   // pasted text keeps no outside styling
});
var comp = $('ib-comp'), dragDepth = 0;
comp.addEventListener('dragenter', function(ev){ if (ev.dataTransfer && Array.prototype.indexOf.call(ev.dataTransfer.types, 'Files') >= 0) { dragDepth++; comp.classList.add('drop'); } });
comp.addEventListener('dragleave', function(){ if (--dragDepth <= 0) { dragDepth = 0; comp.classList.remove('drop'); } });
comp.addEventListener('dragover', function(ev){ if (ev.dataTransfer && Array.prototype.indexOf.call(ev.dataTransfer.types, 'Files') >= 0) ev.preventDefault(); });
comp.addEventListener('drop', function(ev){ if (!ev.dataTransfer || !ev.dataTransfer.files.length) return; ev.preventDefault(); dragDepth = 0; comp.classList.remove('drop'); addFiles(ev.dataTransfer.files); });
function viewFile(n){
  var m = S.open, f = m.files.filter(function(x){ return x.n === n; })[0]; if (!f) return;
  var u = '/inbox_file?a=' + encodeURIComponent(m.account) + '&f=' + encodeURIComponent(m.folder) + '&u=' + m.uid + '&n=' + n + '&view=1', stage = $('ib-view-stage');
  $('ib-view-name').textContent = f.name + ' · ' + sizeOf(f.size);
  stage.innerHTML = /^image\//.test(f.type) ? '<img alt="" src="' + u + '">' : /^audio\//.test(f.type) ? '<audio controls autoplay src="' + u + '"></audio>' :
    /^video\//.test(f.type) ? '<video controls autoplay src="' + u + '"></video>' : '<iframe title="' + esc(f.name) + '" src="' + u + '"></iframe>';
  $('ib-view-open').onclick = function(){ post('/inbox_save', {a: m.account, f: m.folder, u: m.uid, n: n, open: 1}).then(function(d){ toast(d.msg); }).catch(fail); };
  $('ib-view-save').onclick = function(){ post('/inbox_save', {a: m.account, f: m.folder, u: m.uid, n: n}).then(function(d){ toast(d.msg); }).catch(fail); };
  $('ib-view').classList.add('on');
}
function closeView(){ $('ib-view').classList.remove('on'); $('ib-view-stage').innerHTML = ''; }
$('ib-view-x').onclick = closeView; $('ib-view').onclick = function(ev){ if (ev.target === this || ev.target.id === 'ib-view-stage') closeView(); };
$('ib-all').onchange = function(){ var on = this.checked; S.checked = {}; if (on) S.groups.forEach(function(g){ S.checked[g.key] = 1; }); drawList(); };
$('ib-c-ccb').onclick = function(){ $('ib-c-ccrow').hidden = false; $('ib-c-bccrow').hidden = false; $('ib-c-cc').focus(); };
$('ib-c-big').onclick = function(){ $('ib-comp').classList.toggle('big'); };
$('ib-c-close').onclick = function(){ saveDraft(true).then(closeComp).catch(function(e){ fail(e); closeComp(); }); };
$('ib-c-discard').onclick = function(){ var d = S.comp && S.comp.draft; closeComp(); if (d && S.comp === null) post('/inbox_act', {a: $('ib-c-from').value, f: d.f, uids: d.u, act: 'delete_draft'}).catch(function(){}); toast('🗑️ הטיוטה נמחקה'); };
$('ib-c-draft').onclick = function(){ saveDraft(false).catch(fail); };
$('ib-c-send').onclick = send;
$('ib-c-when').onchange = whenChanged;
$('ib-c-files').onchange = function(){ $('ib-c-fn').textContent = Array.prototype.map.call(this.files, function(f){ return f.name; }).join(', '); };
$('ib-comp').addEventListener('keydown', function(ev){ if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); send(); } if (ev.key === 'Escape') $('ib-c-close').click(); });

var confirmed = {};
function confirmTwice(key, text){ if (confirmed[key] && Date.now() - confirmed[key] < 8000) { delete confirmed[key]; return true; } confirmed[key] = Date.now(); toast(text); return false; }
function refsOf(i){
  var g = S.groups[i]; if (!g) return [];
  if (S.checked[g.key]) return selectedRefs();
  return g.rows.map(function(r){ return {a: g.account, f: r.folder || S.folder, u: r.uid}; });
}
// ✋ drag messages onto a folder
$('ib-rows').addEventListener('dragstart', function(ev){
  var row = ev.target.closest('.ib-row'); if (!row) return;
  S.drag = refsOf(+row.dataset.i); ev.dataTransfer.effectAllowed = 'move'; ev.dataTransfer.setData('text/plain', S.drag.length + ' מיילים');
});
$('ib-rows').addEventListener('dragend', function(){ S.drag = null; Array.prototype.forEach.call(document.querySelectorAll('.ib-f.drop'), function(x){ x.classList.remove('drop'); }); });
$('ib-folders').addEventListener('dragover', function(ev){
  var f = ev.target.closest('.ib-f[data-folder]'); if (!f || !S.drag || f.dataset.acc === '*') return;
  if (S.drag.every(function(r){ return r.a.toLowerCase() === f.dataset.acc.toLowerCase() && r.f !== f.dataset.folder; })) { ev.preventDefault(); f.classList.add('drop'); }
});
$('ib-folders').addEventListener('dragleave', function(ev){ var f = ev.target.closest('.ib-f'); if (f) f.classList.remove('drop'); });
$('ib-folders').addEventListener('drop', function(ev){
  var f = ev.target.closest('.ib-f[data-folder]'); if (!f || !S.drag) return; ev.preventDefault(); f.classList.remove('drop');
  act('move', S.drag, {to: f.dataset.folder}); S.drag = null;
});
// 🖱️ right-click on a message
$('ib-rows').addEventListener('contextmenu', function(ev){
  var row = ev.target.closest('.ib-row'); if (!row) return; ev.preventDefault();
  var i = +row.dataset.i, g = S.groups[i], refs = refsOf(i), n = refs.length;
  menu(row, '<div class="row"><b dir="auto">' + (n > 1 ? n + ' הודעות' : esc(g.top.subject || '(ללא נושא)')) + '</b></div>' +
    '<button type="button" class="it" data-r="open">📖 פתיחה</button>' +
    '<button type="button" class="it" data-r="' + (g.unread ? 'read' : 'unread') + '">' + (g.unread ? '✉️ סימון כנקרא' : '● סימון כלא נקרא') + '</button>' +
    '<button type="button" class="it" data-r="' + (g.star ? 'unstar' : 'star') + '">⭐ ' + (g.star ? 'הסרת כוכב' : 'כוכב') + '</button>' +
    '<button type="button" class="it" data-r="archive">🗄️ ארכיון</button><button type="button" class="it" data-r="delete">🗑️ מחיקה</button>' +
    '<button type="button" class="it" data-r="spam">🚫 ספאם</button>' +
    '<div class="row"><label>📁</label><select id="ib-r-move"><option value="">העברה ל…</option>' + ((S.folders[g.account] || []).filter ? S.folders[g.account].filter(function(f){ return f.id !== S.folder; }).map(function(f){ return '<option value="' + esc(f.id) + '">' + esc(f.icon + ' ' + (f.path || f.name)) + '</option>'; }).join('') : '') + '</select></div>', function(m){
    m.onclick = function(e2){ var b = e2.target.closest('[data-r]'); if (!b) return; closeMenu(); var r = b.dataset.r;
      if (r === 'open') openGroup(i); else act(r, refs); };
    $('ib-r-move').onchange = function(){ if (this.value) { closeMenu(); act('move', refs, {to: this.value}); } };
  });
});
function keys(ev){
  if (!$('ibx')) return stop();
  if (ev.key === 'Escape' && $('ib-view').classList.contains('on')) { closeView(); return; }
  if (ev.key === 'Escape' && $('ib-menu').classList.contains('on')) { closeMenu(); return; }
  var typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
  if (typing || ev.ctrlKey || ev.metaKey || ev.altKey || $('ib-comp').classList.contains('on')) return;
  var k = ev.code && ev.code.indexOf('Key') === 0 ? ev.code.slice(3).toLowerCase() : ev.key;
  if (k === 'g') { S.gpending = Date.now(); return; }
  if (Date.now() - S.gpending < 1500) return;             // G + letter = the page shortcuts
  var n = S.groups.length, move = function(d){ S.kb = Math.max(0, Math.min(n - 1, (S.kb < 0 ? -1 : S.kb) + d)); drawList();
    var row = document.querySelector('.ib-row.kb'); if (row) row.scrollIntoView({block: 'nearest'}); if (S.open) openGroup(S.kb); };
  var g = S.groups[S.kb], target = function(){ return S.open ? [{a: S.open.account, f: S.open.folder, u: S.open.uid}] : g ? g.rows.map(function(r){ return {a: g.account, f: r.folder || S.folder, u: r.uid}; }) : []; };
  var handled = true;
  if (k === 'j' || ev.key === 'ArrowDown') move(1);
  else if (k === 'k' || ev.key === 'ArrowUp') move(-1);
  else if ((k === 'o' || ev.key === 'Enter') && S.kb >= 0) openGroup(S.kb);
  else if (k === 'x' && g) { if (S.checked[g.key]) delete S.checked[g.key]; else S.checked[g.key] = 1; drawList(); }
  else if (k === 'e') { var r1 = Object.keys(S.checked).length ? selectedRefs() : target(); if (r1.length) act('archive', r1); }
  else if (ev.key === '#' || ev.key === 'Delete') { var r2 = Object.keys(S.checked).length ? selectedRefs() : target(); if (r2.length) act('delete', r2); }
  else if (k === 's') { if (S.open) msgAction('star'); else if (g) act(g.star ? 'unstar' : 'star', target()); }
  else if (k === 'u') { if (S.open) msgAction('unread'); else if (g) act(g.unread ? 'read' : 'unread', target()); }
  else if (k === 'r' && S.open) compose('reply');
  else if (k === 'a' && S.open) compose('all');
  else if (k === 'f' && S.open) compose('fwd');
  else if (k === 'c') compose('new');
  else if (ev.key === '/') $('ib-q').focus();
  else if (ev.key === 'Escape' && S.open) closeMessage();
  else handled = false;
  if (handled) ev.preventDefault();
}
var timer = setInterval(function(){
  if (!$('ibx')) return stop();
  api('/inbox_poll.json').then(function(d){ if (S.v >= 0 && d.v !== S.v) { loadList({quiet: 1}); loadAllFolders(true); } S.v = d.v; }).catch(function(){});
}, 8000);
function stop(){ clearInterval(timer); clearInterval(S.autosave); window.removeEventListener('keydown', keys); window.removeEventListener('beforeunload', unload); document.removeEventListener('mousedown', outside); window.__ibx = null; }
function unload(){ if (S.comp) saveDraft(true); }
window.addEventListener('keydown', keys); window.addEventListener('beforeunload', unload); document.addEventListener('mousedown', outside);
window.__ibx = {stop: stop};

applyLook(); drawFolders(); loadAllFolders(false); if (S.acc !== '*') loadFolders(S.acc, true);
if (!B.uid) drawHome();
api('/inbox_poll.json').then(function(d){ S.v = d.v; }).catch(function(){});
if (B.compose) compose('new');
loadList().then(function(){ if (B.uid) { var i = -1; S.groups.forEach(function(g, n){ if (g.rows.some(function(r){ return String(r.uid) === String(B.uid); })) i = n; });
  if (i >= 0) openGroup(i); else openMessage(S.acc === '*' ? B.accounts[0].email : S.acc, S.folder, B.uid); } });
})();
"""
