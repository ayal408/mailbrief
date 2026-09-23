"""The local web server (127.0.0.1 only) and all its routes."""
import datetime as dt
import json
import os
import re
import secrets
import threading
import traceback
import webbrowser
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse

from mailbrief import config
from mailbrief.features import notify
from mailbrief.mail import imap
from mailbrief.mail import smtp
from mailbrief.features.alerts import check_alerts
from mailbrief.features.archive import archive_backfill, archive_old_newsletters, write_archive_index
from mailbrief.features.automations import ACTIONS, COND_FIELDS, COND_OPS, log_run, RECIPES, run_action, SCHEDULE_ACTIONS, schedule_context, test_workflow, TRIGGERS, WEEKDAYS, workflows
from mailbrief.features.brief import import_receipts, run_all
from mailbrief.features.calendar import CITIES, pause_for
from mailbrief.features.history import build_history
from mailbrief.features.maintenance import make_backup, restore_backup
from mailbrief.features.notify import telegram_api, telegram_cfg, telegram_send
from mailbrief.features.reminders import add_reminder
from mailbrief.features.replies import create_draft_reply, reply_templates, VACATION_DEFAULT
from mailbrief.features.search import download_search_attachments
from mailbrief.features.unsubscribe import unsubscribe
from mailbrief.mail.accounts import finish_oauth, friendly_error
from mailbrief.mail.domains import guess_host
from mailbrief.mail.oauth import PROVIDERS, start_oauth
from mailbrief.storage import encrypt, load_json, save_json
from mailbrief.tray import close_tray, run_tray
from mailbrief.util import e
from mailbrief.web.automations import automations_page
from mailbrief.web.clients import client_page, clients_page
from mailbrief.web.dashboard import dashboard_page, stats_page
from mailbrief.web.help import health_page, help_page
from mailbrief.web.layout import FONT, STYLE
from mailbrief.web.reading import reading_page
from mailbrief.web.search import search_page
from mailbrief.web.settings import FIELD_NAMES, settings_page
from mailbrief.web.today import today_page
from mailbrief.web.token import TOKEN


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _host_ok(self):
        return self.headers.get('Host', '') in (f'127.0.0.1:{config.PORT}', f'localhost:{config.PORT}')

    def _send(self, body, ctype='text/html; charset=utf-8', code=200):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to):
        self.send_response(303)
        self.send_header('Location', to)
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            return self._send('forbidden', code=403)
        url = urlparse(self.path)
        if url.path == '/':
            return self._send(settings_page(parse_qs(url.query).get('msg', [''])[0]))
        if url.path == '/oauth/callback':
            try:
                msg = finish_oauth(parse_qs(url.query))
            except Exception as exc:
                msg = f'שגיאה: {exc}'
            return self._redirect(f'http://127.0.0.1:{config.PORT}/?msg=' + quote(msg))
        if url.path.startswith('/reports/'):
            name = os.path.basename(unquote(url.path[9:]))
            path = os.path.join(config.REPORTS, name)
            if name.endswith('.html') and os.path.isfile(path):
                with open(path, 'rb') as f:
                    return self._send(f.read())
        if url.path == '/dashboard':
            return self._send(dashboard_page())
        if url.path == '/today':
            return self._send(today_page())
        if url.path == '/stats':
            return self._send(stats_page())
        if url.path == '/help':
            return self._send(help_page(parse_qs(url.query).get('msg', [''])[0]))
        if url.path == '/clients':
            return self._send(clients_page())
        if url.path == '/client':
            return self._send(client_page(parse_qs(url.query).get('key', [''])[0]))
        if url.path == '/reading':
            return self._send(reading_page(parse_qs(url.query).get('msg', [''])[0]))
        if url.path == '/automations':
            return self._send(automations_page(parse_qs(url.query).get('msg', [''])[0]))
        if url.path == '/search':
            return self._send(search_page(parse_qs(url.query).get('q', [''])[0].strip()[:200]))
        if url.path == '/unsub':                # link from a report: confirm first, never act on GET
            key = parse_qs(url.query).get('id', [''])[0]
            entry = load_json(config.UNSUBS_FILE, {}).get(key)
            if entry:
                return self._send(
                    f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>ביטול מנוי</title>{FONT}'
                    f'<style>{STYLE} button{{font:inherit;border:0;background:var(--accent);color:#fff;padding:10px 18px;border-radius:10px;cursor:pointer}}</style>'
                    f'</head><body><main><h1>ביטול מנוי</h1><p dir="auto">לבטל את המנוי של <b>{e(entry.get("name") or entry["sender"])}</b>'
                    f' ({e(entry["sender"])}) בתיבה {e(entry["account"])}?</p>'
                    f'<form method="post" action="/unsubscribe"><input type="hidden" name="t" value="{TOKEN}">'
                    f'<input type="hidden" name="id" value="{e(key)}"><button>כן, לבטל</button></form></main></body></html>')
        self._send('not found', code=404)

    def do_POST(self):
        if not self._host_ok():
            return self._send('forbidden', code=403)
        length = int(self.headers.get('Content-Length', 0))
        raw = parse_qs(self.rfile.read(length).decode('utf-8'))
        form = {k: v[0] for k, v in raw.items()}
        form['_lists'] = raw                     # multi-value fields (checkbox groups)
        if not secrets.compare_digest(form.get('t', ''), TOKEN):
            return self._redirect('/?msg=' + quote('הדף היה ישן (MailBrief עודכן או הופעל מחדש) — הפעולה לא בוצעה. אפשר לנסות שוב עכשיו.'))
        route = urlparse(self.path).path
        try:
            msg = getattr(self, 'post_' + route.strip('/'))(form)
        except AttributeError:
            return self._send('not found', code=404)
        except Exception as exc:
            msg = f'שגיאה: {exc}'
        if msg is None:                         # handler already answered
            return
        if isinstance(msg, tuple):              # (redirect target, None)
            return self._redirect(msg[0])
        self._redirect('/?msg=' + quote(msg))

    def post_add(self, f):
        address = f.get('email', '').strip()
        acc = {'id': secrets.token_hex(4), 'email': address, 'user': address,
               'host': f.get('host', '').strip() or guess_host(address),
               'port': int(f.get('port') or 993), 'tag': 'tag' in f,
               'password': encrypt(f.get('password', ''))}
        try:
            imap.connect(acc).logout()
        except Exception as exc:
            return f'לא הצלחתי להתחבר ל-{address}: {friendly_error(exc, acc)}'
        accounts = [a for a in load_json(config.ACCOUNTS_FILE, []) if a['email'].lower() != address.lower()]
        save_json(config.ACCOUNTS_FILE, accounts + [acc])
        return f'✓ {address} נוספה בהצלחה'

    def post_connect(self, f):
        if f.get('provider') not in PROVIDERS:
            return 'ספק לא מוכר'
        return (start_oauth(f['provider']), None)

    def post_oauth_config(self, f):
        provider = f.get('provider')
        if provider not in PROVIDERS:
            return 'ספק לא מוכר'
        settings = load_json(config.SETTINGS_FILE, {})
        cfg = settings.get(provider) or {}
        cfg['client_id'] = f.get('client_id', '').strip()
        if f.get('client_secret', '').strip():
            cfg['client_secret'] = encrypt(f['client_secret'].strip())
        settings[provider] = cfg
        save_json(config.SETTINGS_FILE, settings)
        return f'✓ ההגדרות של {PROVIDERS[provider]["name"]} נשמרו — אפשר ללחוץ על כפתור החיבור'

    def post_remove(self, f):
        accounts = load_json(config.ACCOUNTS_FILE, [])
        save_json(config.ACCOUNTS_FILE, [a for a in accounts if a['id'] != f.get('id')])
        return 'התיבה הוסרה (המייל עצמו לא נגעתי בו)'

    def post_test(self, f):
        accounts = load_json(config.ACCOUNTS_FILE, [])
        acc = next((a for a in accounts if a['id'] == f.get('id')), None)
        if not acc:
            return 'התיבה לא נמצאה'
        try:
            imap.connect(acc).logout()
            return f'✓ החיבור ל-{acc["email"]} עובד'
        except Exception as exc:
            return f'{acc["email"]}: {friendly_error(exc, acc)}'
        finally:
            save_json(config.ACCOUNTS_FILE, accounts)     # keep a rotated refresh token

    def post_run(self, f):
        if not load_json(config.ACCOUNTS_FILE, []):
            return 'קודם צריך להוסיף תיבה'
        path, _ = run_all(open_report=False)
        return ('/reports/' + quote(os.path.basename(path)), None)

    def post_rule_add(self, f):
        contains = f.get('contains', '').strip()
        forward_to = f.get('forward_to', '').strip()
        label = (f.get('label', '').strip() or (f'העברה ל-{forward_to.split("@")[0]}' if forward_to else '')).replace('/', '-')[:40]
        if not contains or not label:
            return 'צריך למלא „מכיל”, וגם תווית או כתובת להעברה'
        if forward_to and not re.fullmatch(r'[^@\s<>",;]+@[^@\s<>",;]+\.[^@\s<>",;]+', forward_to):
            return f'הכתובת „{forward_to}” לא נראית תקינה'
        own = {a['email'].lower() for a in load_json(config.ACCOUNTS_FILE, [])}
        rules = load_json(config.RULES_FILE, [])
        rules.append({'id': secrets.token_hex(4), 'field': f.get('field') if f.get('field') in FIELD_NAMES else 'any',
                      'contains': contains, 'label': label, 'notify': 'notify' in f,
                      'forward_to': forward_to, 'created': dt.datetime.now().astimezone().isoformat()})
        save_json(config.RULES_FILE, rules)
        extra = f' מיילים חדשים שמתאימים יועברו אל {forward_to}.' if forward_to else ''
        loop = ' (שימי לב: זו אחת התיבות שלך — שלא ייווצר כלל הפוך שמחזיר אותם.)' if forward_to.lower() in own else ''
        return f'✓ נוסף כלל: {label}.{extra}{loop}'

    def post_test_send(self, f):
        accounts = load_json(config.ACCOUNTS_FILE, [])
        if not accounts:
            return 'קודם צריך לחבר תיבה'
        results = []
        for acc in accounts:
            msg = EmailMessage()
            msg['From'] = msg['To'] = acc['email']
            msg['Subject'] = '✉️ MailBrief — בדיקת שליחה'
            msg['X-MailBrief-Forwarded'] = '1'
            msg.set_content('אם המייל הזה הגיע — MailBrief יכול לשלוח מהתיבה הזו, וההעברות לפי כללים יעבדו.')
            try:
                smtp.send_mail(acc, msg)
                results.append(f'✓ {acc["email"]}')
            except Exception as exc:
                results.append(f'⚠️ {acc["email"]}: {friendly_error(exc, acc)}')
        save_json(config.ACCOUNTS_FILE, accounts)
        return ' · '.join(results)

    def post_rule_delete(self, f):
        save_json(config.RULES_FILE, [r for r in load_json(config.RULES_FILE, []) if r['id'] != f.get('id')])
        return 'הכלל נמחק (תוויות קיימות ב-Gmail נשארות)'

    def post_unsubscribe(self, f):
        unsubs = load_json(config.UNSUBS_FILE, {})
        entry = unsubs.get(f.get('id', ''))
        if not entry:
            return 'השולח לא נמצא'
        kind, value = unsubscribe(entry)
        if kind == 'done' and value.startswith('✓'):
            entry['done'] = dt.date.today().strftime('%d/%m')
            save_json(config.UNSUBS_FILE, unsubs)
        return (value, None) if kind == 'open' else value

    def _save_telegram(self, **changes):
        settings = load_json(config.SETTINGS_FILE, {})
        settings['telegram'] = (settings.get('telegram') or {}) | changes
        save_json(config.SETTINGS_FILE, settings)

    def post_tg_save(self, f):
        token = f.get('token', '').strip()
        if not re.fullmatch(r'\d{5,}:[\w-]{20,}', token):
            return 'ה-token לא נראה תקין (צריך להיראות כמו 123456789:ABC-def...)'
        me = telegram_api(token, 'getMe', {})
        self._save_telegram(token=encrypt(token), chat_id=None)
        return f'✓ הבוט @{me.get("username")} נשמר. עכשיו לשלוח לו הודעה בטלגרם וללחוץ „חיבור”.'

    def post_tg_connect(self, f):
        token, _, _ = telegram_cfg()
        if not token:
            return 'קודם לשמור את ה-token'
        updates = telegram_api(token, 'getUpdates', {'timeout': 0})
        chats = [u['message']['chat'] for u in updates if u.get('message', {}).get('chat', {}).get('type') == 'private']
        if not chats:
            return 'לא מצאתי הודעה — לפתוח את הבוט בטלגרם, לשלוח לו „היי”, ולנסות שוב'
        self._save_telegram(chat_id=chats[-1]['id'])
        telegram_send('✓ MailBrief מחובר! מעכשיו ההתראות יגיעו גם לכאן 📬')
        return f'✓ טלגרם מחובר ({chats[-1].get("first_name", "")}) — נשלחה הודעת אישור'

    def post_tg_test(self, f):
        telegram_send('🧪 הודעת ניסיון מ-MailBrief', 'https://mail.google.com/')
        return '✓ נשלחה הודעת ניסיון לטלגרם'

    def post_tg_mirror(self, f):
        _, _, mirror = telegram_cfg()
        self._save_telegram(mirror=not mirror)
        return '✓ ההתראות ישוכפלו לטלפון' if not mirror else '✓ ההתראות יופיעו רק במחשב (פעולת טלגרם באוטומציות עדיין תעבוד)'

    def post_remind(self, f):
        days = int(f.get('days', '1')) if f.get('days', '1').isdigit() else 1
        link = f.get('link', '')
        due = add_reminder(days, f.get('subject', '')[:200], f.get('from', '')[:100],
                           link if link.startswith('https://mail.google.com/') else '', f.get('account', ''))
        return ('/today', None) if due else 'שגיאה'

    def post_reminder_delete(self, f):
        save_json(config.REMINDERS_FILE, [r for r in load_json(config.REMINDERS_FILE, []) if r['id'] != f.get('id')])
        return ('/today', None)

    def post_search_download(self, f):
        query = f.get('q', '').strip()[:200]
        if not query:
            return 'אין מה לחפש'
        folder, count, errors = download_search_attachments(query)
        if count:
            os.startfile(folder)
        return (f'✓ נשמרו {count} קבצים בתיקייה „{os.path.basename(folder)}” (בתוך „הורדות”)' if count else 'לא נמצאו קבצים מצורפים')\
            + (' · ' + ' | '.join(errors) if errors else '')

    def post_health(self, f):
        self._send(health_page())
        return None

    def post_backup_now(self, f):
        path = make_backup('manual')
        return ('/help?msg=' + quote(f'✓ נשמר גיבוי: {os.path.basename(path)}'), None)

    def post_restore(self, f):
        count = restore_backup(f.get('name', ''))
        return ('/help?msg=' + quote(f'✓ שוחזרו {count} קבצים. גיבוי של המצב הקודם נשמר למקרה שתרצי לחזור.'), None)

    def post_news_archive_now(self, f):
        moved, errors = archive_old_newsletters(3)
        return ('/reading?msg=' + quote(f'✓ {moved} ניוזלטרים הועברו לארכיון (לא נמחקו)' + (' · ' + ' | '.join(errors) if errors else '')), None)

    def post_news_auto(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        settings['auto_archive_news'] = not settings.get('auto_archive_news', False)
        save_json(config.SETTINGS_FILE, settings)
        return ('/reading?msg=' + quote('✓ ארכוב אוטומטי הופעל — בכל ריצה שבועית' if settings['auto_archive_news'] else 'ארכוב אוטומטי כובה'), None)

    def post_archive_backfill(self, f):
        count, errors = archive_backfill(90)
        return f'✓ נשמרו {count} הודעות בארכיון המקומי' + (' · ' + ' | '.join(errors) if errors else '')

    def post_open_archive(self, f):
        index = os.path.join(config.ARCHIVE_DIR, 'index.html')
        if not os.path.exists(index):
            write_archive_index(load_json(config.ARCHIVE_MANIFEST, {}))
        os.startfile(index)
        return '🗄️ הארכיון נפתח'

    def post_projects_root(self, f):
        root = f.get('root', '').strip().strip('"')
        if root and not os.path.isdir(root):
            return f'התיקייה „{root}” לא נמצאה'
        settings = load_json(config.SETTINGS_FILE, {})
        settings['projects_root'] = root
        save_json(config.SETTINGS_FILE, settings)
        cache = load_json(config.CACHE_FILE, {})
        cache.pop('projects', None)
        save_json(config.CACHE_FILE, cache)
        return f'✓ תיקיית הפרויקטים: {root}' if root else 'כרטיס הפרויקטים הוסתר'

    def post_vacation(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        if f.get('action') == 'off':
            settings.pop('vacation', None)
            save_json(config.SETTINGS_FILE, settings)
            return '✓ מצב חופשה כובה'
        start, end = f.get('from', ''), f.get('to', '')
        try:
            if dt.date.fromisoformat(end) < dt.date.fromisoformat(start):
                return 'תאריך הסיום לפני תאריך ההתחלה'
        except ValueError:
            return 'צריך לבחור תאריך התחלה וסיום'
        settings['vacation'] = {'from': start, 'to': end, 'message': f.get('message', '').strip()[:2000] or VACATION_DEFAULT}
        save_json(config.SETTINGS_FILE, settings)
        return f'✓ מצב חופשה נשמר: {start[8:10]}/{start[5:7]} עד {end[8:10]}/{end[5:7]}. המענה יוצא בבדיקה השעתית, פעם אחת לכל אדם.'

    def post_template_add(self, f):
        name, text = f.get('name', '').strip()[:40], f.get('text', '').strip()[:3000]
        if not name or not text:
            return 'צריך שם ונוסח'
        settings = load_json(config.SETTINGS_FILE, {})
        settings['templates'] = reply_templates() + [{'id': secrets.token_hex(4), 'name': name, 'text': text}]
        save_json(config.SETTINGS_FILE, settings)
        return f'✓ התבנית „{name}” נוספה'

    def post_template_delete(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        settings['templates'] = [t for t in reply_templates() if t['id'] != f.get('id')]
        save_json(config.SETTINGS_FILE, settings)
        return 'התבנית נמחקה'

    def post_draft(self, f):
        template = next((t for t in reply_templates() if t['id'] == f.get('template')), None)
        if not template:
            return 'התבנית לא נמצאה'
        link = create_draft_reply(f.get('account', ''), f.get('message_id', ''), template['text'])
        return (link, None) if link else ('/today', None)

    def _wf_back(self, msg):
        return ('/automations?msg=' + quote(msg), None)

    def post_wf_add(self, f):
        name = f.get('name', '').strip()[:60]
        trigger = f.get('trigger') if f.get('trigger') in TRIGGERS else 'new_mail'
        conditions = [{'field': f[f'cf{i}'], 'op': f[f'co{i}'], 'value': f[f'cv{i}'].strip()}
                      for i in range(3) if f.get(f'cv{i}', '').strip() and f.get(f'cf{i}') in COND_FIELDS and f.get(f'co{i}') in COND_OPS]
        actions = [{'type': f[f'at{i}'], 'param': f.get(f'ap{i}', '').strip()} for i in range(3) if f.get(f'at{i}') in ACTIONS]
        if not name or not actions:
            return self._wf_back('צריך שם ולפחות פעולה אחת')
        for a in actions:
            if a['type'] in ('forward', 'webhook', 'draft_reply', 'auto_reply') and not a['param']:
                return self._wf_back(f'לפעולה „{ACTIONS[a["type"]][0]}” צריך למלא את השדה שלידה')
            if a['type'] == 'forward' and not re.fullmatch(r'[^@\s<>",;]+@[^@\s<>",;]+\.[^@\s<>",;]+', a['param']):
                return self._wf_back(f'הכתובת „{a["param"]}” לא נראית תקינה')
        if trigger == 'schedule':
            bad = [ACTIONS[a['type']][0] for a in actions if a['type'] not in SCHEDULE_ACTIONS]
            if bad:
                return self._wf_back(f'בתזמון אפשר רק התראה, מייל אליי, Webhook או אקסל (לא: {", ".join(bad)})')
        wf = {'id': secrets.token_hex(4), 'name': name, 'enabled': True, 'trigger': trigger, 'conditions': conditions,
              'actions': actions, 'created': dt.datetime.now().astimezone().isoformat()}
        if trigger == 'waiting':
            wf['wait_days'] = max(1, min(30, int(f.get('wait_days') or 3)))
        if trigger == 'schedule':
            days = [int(d) for d in f['_lists'].get('day', []) if d.isdigit() and int(d) in dict((d, n) for n, d in WEEKDAYS)]
            wf['schedule'] = {'days': days or [6], 'hour': max(7, min(23, int(f.get('hour') or 9)))}
        save_json(config.WF_FILE, workflows() + [wf])
        warn = ' שימי לב: תשובה אוטומטית נשלחת לאנשים אמיתיים.' if any(a['type'] == 'auto_reply' for a in actions) else ''
        return self._wf_back(f'✓ האוטומציה „{name}” נשמרה ופעילה. אפשר ללחוץ 🧪 כדי לראות מה היא הייתה תופסת.{warn}')

    def post_wf_recipe(self, f):
        try:
            recipe = RECIPES[int(f.get('recipe', -1))]
        except (ValueError, IndexError):
            return self._wf_back('מתכון לא נמצא')
        wf = json.loads(json.dumps(recipe)) | {'id': secrets.token_hex(4), 'enabled': True,
                                               'created': dt.datetime.now().astimezone().isoformat()}
        save_json(config.WF_FILE, workflows() + [wf])
        return self._wf_back(f'✓ נוסף: „{wf["name"]}”. אפשר לבדוק אותו עם 🧪 או להשבית.')

    def post_wf_toggle(self, f):
        items = workflows()
        for w in items:
            if w['id'] == f.get('id'):
                w['enabled'] = not w.get('enabled', True)
        save_json(config.WF_FILE, items)
        return self._wf_back('✓ עודכן')

    def post_wf_delete(self, f):
        save_json(config.WF_FILE, [w for w in workflows() if w['id'] != f.get('id')])
        return self._wf_back('האוטומציה נמחקה')

    def post_wf_test(self, f):
        wf = next((w for w in workflows() if w['id'] == f.get('id')), None)
        if not wf:
            return self._wf_back('האוטומציה לא נמצאה')
        if wf['trigger'] == 'schedule':        # a timed automation has nothing to "catch": run it once now
            accounts = load_json(config.ACCOUNTS_FILE, [])
            if not accounts:
                return self._wf_back('קודם צריך לחבר תיבה')
            results = [run_action(a, wf, accounts[0], schedule_context()) for a in wf['actions']]
            save_json(config.ACCOUNTS_FILE, accounts)
            log_run(wf, '🧪 הרצה ידנית', results)
            return self._wf_back('הורץ עכשיו: ' + ' · '.join(results))
        found, errors = test_workflow(wf)
        self._send(automations_page(test=(wf, found, errors)))
        return None

    def post_build_history(self, f):
        count, errors = build_history(30)
        return ('/stats', None) if not errors else f'נבנתה היסטוריה מ-{count} מיילים · ' + ' | '.join(errors)

    def post_set_city(self, f):
        if f.get('city') in CITIES:
            settings = load_json(config.SETTINGS_FILE, {})
            settings['city'] = f['city']
            save_json(config.SETTINGS_FILE, settings)
        return ('/today', None)

    def post_open_receipts(self, f):
        os.makedirs(config.RECEIPTS_DIR, exist_ok=True)
        os.startfile(config.RECEIPTS_DIR)
        return '📂 תיקיית הקבלות נפתחה'

    def post_import_receipts(self, f):
        if not load_json(config.ACCOUNTS_FILE, []):
            return 'קודם צריך לחבר תיבה'
        count, errors = import_receipts(90)
        return f'✓ יובאו {count} קבלות מ-90 הימים האחרונים' + (' · ' + ' | '.join(errors) if errors else '')

    def post_test_toast(self, f):
        notify.toast('📬 MailBrief — התראת ניסיון', ['ככה ייראו התראות על מייל דחוף או חריג.'], f'http://127.0.0.1:{config.PORT}/')
        return '✓ נשלחה התראת ניסיון — היא אמורה להופיע בפינת המסך'

    def post_check(self, f):
        count = check_alerts()
        return f'✓ נמצאו {count} הודעות חדשות להתראה' if count else '✓ נבדק — אין כרגע משהו דחוף או חריג'

    def post_quit(self, f):
        self._send(f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">{FONT}<style>{STYLE}</style></head>'
                   '<body><main><h1>MailBrief נסגר 👋</h1><p class="muted">הריצות המתוזמנות ממשיכות לעבוד. '
                   'לפתיחה מחדש: הקיצור MailBrief בשולחן העבודה.</p></main></body></html>')
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        close_tray()
        return None

    def post_pause(self, f):
        until = pause_for(f.get('mode', 'off'))
        return f'⏸️ האוטומציות וההתראות מושהות עד {until:%d/%m %H:%M}' if until else '▶️ ההשהיה בוטלה — הכול פועל כרגיל'


def serve(start_page=''):
    os.makedirs(config.DATA, exist_ok=True)
    url = f'http://127.0.0.1:{config.PORT}/{start_page}'
    try:
        server = ThreadingHTTPServer(("127.0.0.1", config.PORT), Handler)
    except OSError:                              # already running: just show it
        webbrowser.open(url)
        return
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    webbrowser.open(url)
    try:
        run_tray()                               # returns when the user picks "Exit"
    except Exception:
        with open(os.path.join(config.DATA, 'tray.log'), 'w', encoding='utf-8') as f:
            f.write(traceback.format_exc())
        worker.join()                            # no tray: keep serving until "⏻ Close" on the page
    finally:
        server.shutdown()
