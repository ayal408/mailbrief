"""The automation engine: trigger -> conditions -> actions."""
import datetime as dt
import imaplib
import json
import os
import re
import urllib.request
from email.message import EmailMessage
from urllib.parse import quote
from urllib.parse import urlparse

from mailbrief import config
from mailbrief.address import link
from mailbrief.features import google_apps
from mailbrief.features import notify
from mailbrief.mail import imap
from mailbrief.mail import smtp
from mailbrief.features.reminders import add_reminder
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.classify import CATS, classify, demote_automated, is_bulk, RX
from mailbrief.mail.imap import fetch_recent, is_gmail, mark_unanswered, special_folder
from mailbrief.mail.labels import tag_message
from mailbrief.mail.message import decode
from mailbrief.mail.smtp import build_forward, build_reply
from mailbrief.money.excel import write_xlsx
from mailbrief.money.ledger import find_duplicate, ils, item_key, parse_amount, vendor_key
from mailbrief.net import _PUBLIC_TLS
from mailbrief.storage import load_json, save_json
from mailbrief.util import e, money, safe_name, write_once


TRIGGERS = {
    'new_mail': '📨 מגיע מייל חדש',
    'receipt': '🧾 מגיעה קבלה / חשבונית',
    'waiting': '⏳ מייל מחכה לתשובה שלי',
    'double': '⚠️ ייתכן חיוב כפול',
    'schedule': '🕘 בזמן קבוע',
}


COND_FIELDS = {
    'from': 'השולח', 'subject': 'הנושא', 'body': 'תוכן המייל', 'any': 'כל מקום', 'attachment': 'שם קובץ מצורף',
    'category': 'הקטגוריה / התווית', 'account': 'התיבה', 'amount': 'הסכום', 'waiting_days': 'ימי המתנה',
}


COND_OPS = {'contains': 'מכיל', 'not_contains': 'לא מכיל', 'equals': 'שווה ל', 'gt': 'גדול מ', 'lt': 'קטן מ'}


ACTIONS = {                                     # type: (label, parameter hint, needs write access to the mailbox)
    'label': ('🏷️ הוספת תווית', 'שם התווית', True),
    'star': ('⭐ סימון בכוכב', '', True),
    'mark_read': ('👁️ סימון כנקרא', '', True),
    'archive': ('📥 העברה לארכיון (Gmail)', '', True),
    'notify': ('🔔 התראת Windows', 'טקסט, למשל: {subject} מ-{from_name}', False),
    'forward': ('↪️ העברה לכתובת', 'כתובת מייל', False),
    'draft_reply': ('📝 טיוטת תשובה ב-Gmail', 'נוסח התשובה', True),
    'auto_reply': ('🤖 תשובה אוטומטית', 'נוסח התשובה', False),
    'save_attachments': ('📎 שמירת הקבצים המצורפים', 'תיקייה (ריק = „יומני אוטומציה”)', False),
    'log_excel': ('📊 רישום שורה באקסל', 'שם הקובץ (ריק = שם האוטומציה)', False),
    'webhook': ('🔗 Webhook (למשל n8n)', 'כתובת URL', False),
    'email_me': ('✉️ מייל אליי', 'נוסח המייל', False),
    'remind': ('⏰ תזכורת בעוד X ימים', 'מספר ימים (ברירת מחדל 3)', False),
    'gtask': ('✅ משימה ב-Google Tasks', 'כותרת, למשל: לענות ל-{from_name} (ריק = נושא המייל). תאריך יעד = {due} אם נמצא', False),
    'gevent': ('📅 אירוע ב-Google Calendar', 'כותרת (ריק = נושא המייל). ביום התשלום אם נמצא, אחרת מחר', False),
}


SCHEDULE_ACTIONS = {'notify', 'email_me', 'webhook', 'log_excel', 'gtask', 'gevent'}


WEEKDAYS = [('ראשון', 6), ('שני', 0), ('שלישי', 1), ('רביעי', 2), ('חמישי', 3), ('שישי', 4)]   # no Shabbat


VARIABLES = '{from} {from_name} {subject} {date} {account} {amount} {due} {snippet} {link} {waiting_days} {category}'


def workflows(enabled_only=False):
    items = load_json(config.WF_FILE, [])
    return [w for w in items if w.get('enabled', True)] if enabled_only else items


def workflows_need_write():
    return any(ACTIONS.get(a['type'], ('', '', False))[2]
               for w in workflows(True) if w['trigger'] != 'schedule' for a in w['actions'])


def fill(template, ctx):
    return re.sub(r'\{(\w+)\}', lambda m: str(ctx.get(m.group(1), m.group(0))), template or '')


def wf_context(acc, it):
    return {'from': it['sender'], 'from_name': it['sender_name'], 'subject': it['subject'], 'date': it['date'],
            'account': acc['email'], 'amount': it.get('amount', ''), 'snippet': it['snippet'], 'link': it.get('link', ''),
            'waiting_days': it.get('waiting_days', 0), 'due': it.get('due', ''),
            'category': ', '.join([CATS[c][1] for c in it['cats'] if c in CATS] + it.get('rules', []))}


def cond_ok(c, acc, it):
    field, op, value = c.get('field'), c.get('op'), (c.get('value') or '').strip().lower()
    if field in ('amount', 'waiting_days'):
        have = parse_amount(it.get('amount'))[0] if field == 'amount' else it.get('waiting_days')
        try:
            want = float(value.replace(',', ''))
        except ValueError:
            return False
        if have is None:
            return False
        return {'gt': have > want, 'lt': have < want, 'equals': abs(have - want) < 0.005}.get(op, False)
    text = {
        'from': f"{it['sender_name']} {it['sender']}", 'subject': it['subject'], 'body': it.get('body', ''),
        'any': f"{it['sender_name']} {it['sender']} {it['subject']} {it.get('body', '')}",
        'attachment': ' '.join(it.get('attachments', [])), 'account': acc['email'],
        'category': ' '.join([CATS[x][1] for x in it['cats'] if x in CATS] + it.get('rules', [])),
    }.get(field, '').lower()
    if op == 'contains':
        return value in text
    if op == 'not_contains':
        return value not in text
    if op == 'equals':
        return text.strip() == value
    return False


def trigger_ok(wf, acc, it, ledger, ignore_created=False):
    arrived = dt.datetime.fromisoformat(it['iso'])
    fresh = ignore_created or arrived >= dt.datetime.fromisoformat(wf['created'])
    kind = wf['trigger']
    if kind == 'new_mail':
        return fresh
    if kind == 'receipt':
        return fresh and 'receipts' in it['cats']
    if kind == 'waiting':
        return it.get('waiting_days', 0) >= int(wf.get('wait_days') or 3)
    if kind == 'double':
        return fresh and 'receipts' in it['cats'] and bool(find_duplicate(
            ledger, item_key(acc['email'], it), vendor_key(it['sender']), parse_amount(it.get('amount'))[0],
            it['iso'][:10], it['subject']))
    return False


def matches(wf, acc, it, ledger, ignore_created=False):
    return trigger_ok(wf, acc, it, ledger, ignore_created) and all(cond_ok(c, acc, it) for c in wf.get('conditions', []))


def append_excel_row(name, ctx):
    rows = load_json(config.WF_ROWS, {})
    rows.setdefault(name, []).append([dt.datetime.now().strftime('%Y-%m-%d %H:%M'), ctx.get('account', ''),
                                      ctx.get('from_name', ''), ctx.get('from', ''), ctx.get('subject', ''),
                                      ctx.get('amount', ''), ctx.get('category', ''), ctx.get('link', '')])
    save_json(config.WF_ROWS, rows)
    os.makedirs(config.WF_DIR, exist_ok=True)
    path = os.path.join(config.WF_DIR, f'{safe_name(name)}.xlsx')
    write_xlsx(path, name[:31], ['זמן', 'תיבה', 'שולח', 'מייל השולח', 'נושא', 'סכום', 'קטגוריה', 'קישור'],
               rows[name], [16, 26, 22, 28, 44, 12, 18, 40])
    return path


def post_webhook(url, payload):
    if urlparse(url).scheme not in ('http', 'https'):
        raise RuntimeError('כתובת Webhook צריכה להתחיל ב-http או https')
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), method='POST',
                                 headers={'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'MailBrief/1.0'})
    with urllib.request.urlopen(req, timeout=15, context=_PUBLIC_TLS) as resp:
        return resp.status


def run_action(a, wf, acc, ctx, m=None, it=None, msg=None, state=None):
    kind, param = a.get('type'), (a.get('param') or '').strip()
    label = ACTIONS.get(kind, (kind,))[0]
    try:
        if kind == 'notify':
            notify.toast(f'⚡ {wf["name"]}', [fill(param or '{subject} — {from_name}', ctx)], ctx.get('link') or link('automations'))
        elif kind == 'email_me':
            note = EmailMessage()
            note['From'] = note['To'] = acc['email']
            note['Subject'] = f'⚡ {wf["name"]}' + (f': {ctx["subject"]}' if it else '')
            note['X-MailBrief-Forwarded'] = '1'
            body = fill(param or '{subject}\n{from_name} <{from}>\n{link}', ctx)
            note.set_content(body)
            note.add_alternative(f'<div dir="rtl" style="font-family:Arial">{e(body).replace(chr(10), "<br>")}</div>', subtype='html')
            smtp.send_mail(acc, note)
        elif kind == 'webhook':
            post_webhook(param, {'automation': wf['name'], 'trigger': wf['trigger'], **ctx})
        elif kind == 'log_excel':
            append_excel_row(param or wf['name'], ctx)
        elif kind in ('gtask', 'gevent'):
            return google_action(kind, label, param, wf, ctx)
        elif it is None:
            return f'— {label}: לא רלוונטי לתזמון'
        elif kind in ('label', 'star', 'mark_read', 'archive'):
            if not it.get('uid'):
                raise RuntimeError('אין מזהה הודעה')
            if kind == 'label':
                tag_message(m, acc, it['uid'], fill(param, ctx) or wf['name'])
            elif kind == 'archive':
                if not is_gmail(acc):
                    return f'— {label}: נתמך רק ב-Gmail'
                m.uid('STORE', it['uid'], '-X-GM-LABELS', r'(\Inbox)')
            else:
                m.uid('STORE', it['uid'], '+FLAGS', r'(\Flagged)' if kind == 'star' else r'(\Seen)')
        elif kind == 'forward':
            if not re.fullmatch(r'[^@\s<>",;]+@[^@\s<>",;]+\.[^@\s<>",;]+', param):
                raise RuntimeError(f'כתובת לא תקינה: {param}')
            if param.lower() == it['sender'].lower():
                return f'— {label}: לא מחזירים לשולח עצמו'
            smtp.send_mail(acc, build_forward(msg, acc, param))
        elif kind == 'draft_reply':
            drafts = special_folder(m, r'\Drafts')
            if not drafts:
                raise RuntimeError('לא נמצאה תיקיית טיוטות')
            m.append(f'"{drafts}"', r'(\Draft)', imaplib.Time2Internaldate(dt.datetime.now().timestamp()),
                     build_reply(msg, acc, fill(param, ctx), auto=False).as_bytes())
        elif kind == 'auto_reply':
            own = {x['email'].lower() for x in load_json(config.ACCOUNTS_FILE, [])}
            sender = it['sender'].lower()
            if is_bulk(msg) or RX['robot_sender'].search(sender) or sender in own or not sender:
                return f'— {label}: דילוג (שולח אוטומטי / רשימת תפוצה / התיבה שלך)'
            sent_today = state.setdefault('_autoreplied', {})
            today = dt.date.today().isoformat()
            if sent_today.get(f'{wf["id"]}|{sender}') == today:
                return f'— {label}: כבר נענה היום'
            if state.setdefault('_auto_budget', {}).get(today, 0) >= config.MAX_AUTO_REPLIES:
                return f'— {label}: הגעת למגבלה היומית ({config.MAX_AUTO_REPLIES})'
            smtp.send_mail(acc, build_reply(msg, acc, fill(param, ctx), auto=True))
            sent_today[f'{wf["id"]}|{sender}'] = today
            state['_auto_budget'] = {today: state['_auto_budget'].get(today, 0) + 1}
        elif kind == 'remind':
            days = int(param) if param.isdigit() else 3
            due = add_reminder(days, it['subject'], it['sender_name'], it.get('link', ''), acc['email'], wf['name'])
            return f'✓ {label} ({due:%d/%m %H:%M})'
        elif kind == 'save_attachments':
            folder = param or os.path.join(config.WF_DIR, safe_name(wf['name']))
            count = 0
            for part in msg.iter_attachments():
                data = part.get_payload(decode=True)
                if data:
                    write_once(folder, f"{it['iso'][:10]} {safe_name(decode(part.get_filename()) or 'file')}", data)
                    count += 1
            return f'✓ {label} ({count})'
        else:
            return f'⚠️ פעולה לא מוכרת: {kind}'
        return f'✓ {label}'
    except Exception as exc:
        return f'⚠️ {label}: {friendly_error(exc, acc) if isinstance(exc, (imaplib.IMAP4.error, RuntimeError)) else exc}'


def google_action(kind, label, param, wf, ctx):
    g = google_apps.gapps_account()
    if not g:
        raise RuntimeError('היומן והמשימות לא מחוברים — „📅 חיבור יומן ומשימות” בדף ההגדרות')
    title = fill(param, ctx) if param else (ctx.get('subject') or wf['name'])
    notes = '\n'.join(x for x in (
        f"{ctx.get('from_name', '')} <{ctx['from']}>" if ctx.get('from') else '',
        f"סכום: {ctx['amount']}" if ctx.get('amount') else '', ctx.get('link', ''), f'⚡ {wf["name"]}') if x)
    due = ctx.get('due', '')
    if kind == 'gtask':
        google_apps.add_task(g, title, notes, due)
        return f'✓ {label}' + (f' (עד {due[8:10]}/{due[5:7]})' if due else '')
    day = dt.date.fromisoformat(due) if due else dt.date.today() + dt.timedelta(days=1)
    if not due and day.weekday() == 5:
        day += dt.timedelta(days=1)             # "tomorrow" from Friday is Sunday, not Shabbat
    google_apps.add_event(g, title, day, notes)
    return f'✓ {label} ({day:%d/%m})'


def log_run(wf, subject, results):
    log = load_json(config.WF_LOG, [])
    log.append({'at': dt.datetime.now().strftime('%d/%m %H:%M'), 'workflow': wf['name'], 'subject': subject, 'results': results})
    save_json(config.WF_LOG, log[-300:])
    items = workflows()
    for w in items:
        if w['id'] == wf['id']:
            w['runs'] = w.get('runs', 0) + 1
            w['last'] = dt.datetime.now().strftime('%d/%m %H:%M')
    save_json(config.WF_FILE, items)


def run_workflows(m, acc, pairs, state, ledger, budget):
    wfs = [w for w in workflows(True) if w['trigger'] != 'schedule']
    if not wfs or not pairs:
        return
    done = set(state.get('_wf_done', []))
    if workflows_need_write():
        m.select('INBOX', readonly=False)      # mark_unanswered left the Sent folder selected
    for it, msg in pairs:
        if msg.get('X-MailBrief-Forwarded') or msg.get('X-MailBrief-Auto'):
            continue                             # never react to our own messages
        for wf in wfs:
            key = f"{wf['id']}|{item_key(acc['email'], it)}"
            if key in done or budget[0] <= 0 or not matches(wf, acc, it, ledger):
                continue
            budget[0] -= 1
            done.add(key)
            ctx = wf_context(acc, it)
            log_run(wf, it['subject'], [run_action(a, wf, acc, ctx, m, it, msg, state) for a in wf['actions']])
    state['_wf_done'] = sorted(done)[-10000:]


def schedule_context():
    snap, ledger = load_json(config.SNAPSHOT_FILE, {}), load_json(config.LEDGER_FILE, {})
    month = dt.date.today().strftime('%Y-%m')
    waiting, urgent = snap.get('waiting', []), snap.get('urgent', [])
    return {
        'date': dt.date.today().strftime('%d/%m/%Y'), 'subject': 'סיכום MailBrief', 'from_name': 'MailBrief', 'from': '',
        'waiting_count': len(waiting), 'urgent_count': len(urgent),
        'waiting_list': '\n'.join(f"• {w['from']} — {w['subject']} ({w['days']} ימים)" for w in waiting) or 'אין',
        'urgent_list': '\n'.join(f"• {u['why']}: {u['subject']}" for u in urgent) or 'אין',
        'month_total': money(sum(ils(r) for r in ledger.values() if r['date'].startswith(month) and ils(r) is not None)),
        'link': link('today'),
    }


def run_schedule_workflows(state, accounts):
    if not accounts:
        return
    now, today = dt.datetime.now(), dt.date.today().isoformat()
    ran = state.setdefault('_wf_sched', {})
    for wf in workflows(True):
        if wf['trigger'] != 'schedule' or ran.get(wf['id']) == today:
            continue
        sched = wf.get('schedule') or {}
        if now.weekday() not in sched.get('days', []) or now.hour < int(sched.get('hour', 9)):
            continue
        ran[wf['id']] = today
        ctx = schedule_context()
        log_run(wf, f'⏰ {now:%H:%M}', [run_action(a, wf, accounts[0], ctx) for a in wf['actions']])


def test_workflow(wf):
    """Dry run over the last 7 days: which emails would match. No actions, nothing changes."""
    accounts, rules, ledger = load_json(config.ACCOUNTS_FILE, []), load_json(config.RULES_FILE, []), load_json(config.LEDGER_FILE, {})
    found, errors = [], []
    for acc in accounts:
        try:
            m = imap.connect(acc)
            try:
                items = []
                for uid, gid, msg in fetch_recent(m, is_gmail(acc), days=7, readonly=True):
                    it = classify(msg, acc['email'], rules)
                    it['message_id'] = (msg.get('Message-ID') or '').strip()
                    it['link'] = f"https://mail.google.com/mail/?authuser={quote(acc['email'])}#all/{gid:x}" if gid else ''
                    items.append(it)
                demote_automated(items, [a['email'] for a in accounts])
                mark_unanswered(m, items)
            finally:
                m.logout()
            found += [(acc['email'], it) for it in items if matches(wf, acc, it, ledger, ignore_created=True)]
        except Exception as exc:
            errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
    save_json(config.ACCOUNTS_FILE, accounts)
    return found, errors


RECIPES = [
    {'name': 'חשבונית גדולה — כוכב והתראה', 'trigger': 'receipt',
     'conditions': [{'field': 'amount', 'op': 'gt', 'value': '1000'}],
     'actions': [{'type': 'star'}, {'type': 'notify', 'param': 'חשבונית של {amount} מ-{from_name}'}]},
    {'name': 'מחכה 3 ימים — טיוטת תשובה', 'trigger': 'waiting', 'wait_days': 3, 'conditions': [],
     'actions': [{'type': 'draft_reply', 'param': 'שלום {from_name},\nקיבלתי את ההודעה ואחזור בהקדם.\nתודה!'}]},
    {'name': 'סיכום בוקר ביום ראשון', 'trigger': 'schedule', 'schedule': {'days': [6], 'hour': 9}, 'conditions': [],
     'actions': [{'type': 'email_me', 'param': 'בוקר טוב!\n\nממתינים לתשובה ({waiting_count}):\n{waiting_list}\n\n'
                                               'דחוף ({urgent_count}):\n{urgent_list}\n\nהוצאות החודש: {month_total}\n{link}'}]},
    {'name': 'כל קבלה — שורה באקסל', 'trigger': 'receipt', 'conditions': [],
     'actions': [{'type': 'log_excel', 'param': 'כל הקבלות'}]},
    {'name': 'מחכה 2 ימים — משימה ב-Google Tasks', 'trigger': 'waiting', 'wait_days': 2, 'conditions': [],
     'actions': [{'type': 'gtask', 'param': 'לענות ל-{from_name}: {subject}'}]},
    {'name': 'חשבון לתשלום — ביומן', 'trigger': 'receipt',
     'conditions': [{'field': 'any', 'op': 'contains', 'value': 'לתשלום'}],
     'actions': [{'type': 'gevent', 'param': '💸 לשלם: {from_name} {amount}'}, {'type': 'gtask', 'param': 'לשלם ל-{from_name} {amount}'}]},
    {'name': 'משרות — לארכיון', 'trigger': 'new_mail',
     'conditions': [{'field': 'from', 'op': 'contains', 'value': 'alljob'}],
     'actions': [{'type': 'label', 'param': 'משרות'}, {'type': 'archive'}]},
]


def describe(wf):
    trig = TRIGGERS.get(wf['trigger'], wf['trigger'])
    if wf['trigger'] == 'waiting':
        trig += f' ({wf.get("wait_days", 3)} ימים)'
    if wf['trigger'] == 'schedule':
        sched = wf.get('schedule') or {}
        names = [n for n, d in WEEKDAYS if d in sched.get('days', [])]
        trig += f' — {", ".join(names) or "אף יום"} ב-{int(sched.get("hour", 9)):02d}:00'
    conds = ' וגם '.join(f'{COND_FIELDS.get(c["field"], c["field"])} {COND_OPS.get(c["op"], c["op"])} „{c["value"]}”'
                         for c in wf.get('conditions', []))
    acts = ' ← '.join(ACTIONS.get(a['type'], (a['type'],))[0] + (f' ({a["param"][:40]})' if a.get('param') else '')
                      for a in wf['actions'])
    return trig, conds, acts
