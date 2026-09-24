"""The local web server (127.0.0.1 only, shown as http://mailbrief.localhost) and all its routes."""
import datetime as dt
import json
import os
import re
import secrets
import threading
import subprocess
import traceback
import ctypes
import socket
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse

from mailbrief import config
from mailbrief.address import base_url, link, remember
from mailbrief.profile import FORMS, g, has_profile, save_profile
from mailbrief.features import notify
from mailbrief.mail import imap
from mailbrief.mail import smtp
from mailbrief.features.alerts import check_alerts
from mailbrief.features.archive import archive_backfill, archive_old_newsletters, write_archive_index
from mailbrief.features.automations import ACTIONS, COND_FIELDS, COND_OPS, log_run, RECIPES, run_action, SCHEDULE_ACTIONS, schedule_context, test_workflow, TRIGGERS, WEEKDAYS, workflows
from mailbrief.features.brief import import_receipts, run_all
from mailbrief.features import google_apps
from mailbrief.features.calendar import CITIES, pause_for
from mailbrief.features.history import build_history
from mailbrief.features.invites import event_resource, invite_key
from mailbrief.features.maintenance import make_backup, restore_backup
from mailbrief.features.reminders import add_reminder
from mailbrief.features.replies import create_draft_reply, reply_templates, VACATION_DEFAULT
from mailbrief.features.search import download_search_attachments
from mailbrief.features.unsubscribe import unsubscribe
from mailbrief.mail.accounts import finish_oauth, friendly_error
from mailbrief.mail.domains import guess_host
from mailbrief.mail.oauth import PROVIDERS, start_oauth
from mailbrief.storage import encrypt, load_json, save_json
from mailbrief.tray import close_tray, run_tray
from mailbrief import window
from mailbrief.window import open_window
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
from mailbrief.web.welcome import welcome_page
from mailbrief.web.insights import insights_page
from mailbrief.web.triage import triage_page
from mailbrief.web.compose import compose_page
from mailbrief.web.greetings import greetings_page
from mailbrief.features import greetings, snooze
from mailbrief.features.replies import reply_details, reply_now
from mailbrief.features import migrate, outbox, triage
from mailbrief.features.diag import log_error, problem_report
from mailbrief.features import cleanup, clientcare, cloud_backup, files, security, sharing
from mailbrief.money import budget
from mailbrief.web.files import files_page
from mailbrief.mail.accounts import DRIVE_SCOPE
from mailbrief.money import books
from mailbrief import view
from mailbrief.money import accountant
from mailbrief.util import money
from mailbrief.features.insights import first_look
from mailbrief.features.daily import daily_account, send_daily
from mailbrief.features.update import start_update, update_available
from mailbrief.features import setup
from mailbrief.web.token import TOKEN


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _host_ok(self):
        return self.headers.get('Host', '').lower() in allowed_hosts()

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
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:                      # a page that crashed: say so (instead of an empty window) and keep a log
            log_error(f'GET {urlparse(self.path).path}')
            try:
                self._send(f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>תקלה</title>{FONT}<style>{STYLE}</style></head>'
                           '<body><main><h1>😕 משהו השתבש בדף הזה</h1><p>התקלה נרשמה ביומן השגיאות. אפשר לחזור <a href="/today">להיום שלי</a>, '
                           'ואם זה חוזר — ב<a href="/help#report">מדריך</a> יש כפתור „📋 דוח תקלה” שמכין קובץ לשליחה.</p></main></body></html>', code=500)
            except Exception:
                pass

    def _get(self):
        if not self._host_ok():
            return self._send('forbidden', code=403)
        url = urlparse(self.path)
        nice = urlparse(base_url()).netloc
        if url.path == '/_show':                                  # a second start of MailBrief: show this window
            page = parse_qs(url.query).get('page', [''])[0]
            threading.Thread(target=open_window, args=(link(page if re.fullmatch(r'[\w/?=&.-]*', page) else ''),), daemon=True).start()
            return self._send('ok', 'text/plain')
        if url.path != '/oauth/callback' and self.headers.get('Host', '').lower() != nice:
            return self._redirect(base_url() + self.path)        # old 127.0.0.1:8765 links -> the nice address
        if url.path == '/welcome':
            return self._send(welcome_page())
        if not has_profile() and url.path in ('/', '/today', '/dashboard', '/stats', '/automations', '/clients', '/reading', '/search', '/help', '/insights', '/triage', '/compose', '/greetings'):
            return self._redirect('/welcome')                     # first run: name and form of address first
        if url.path == '/':
            q = parse_qs(url.query)
            month = q.get('month', [''])[0]
            return self._send(settings_page(q.get('msg', [''])[0], q.get('s', ['boxes'])[0],
                                            month if re.fullmatch(r'\d{4}-\d{2}', month) else ''))
        if url.path == '/oauth/callback':
            try:
                msg = finish_oauth(parse_qs(url.query))
            except Exception as exc:
                msg = f'שגיאה: {exc}'
            first = (msg.startswith('✓') and len(load_json(config.ACCOUNTS_FILE, [])) == 1
                     and not os.path.exists(config.INSIGHTS_FILE))
            target = link(('insights?run=1&msg=' if first else '?msg=') + quote(msg))   # first mailbox: show its 30 days
            if window.in_app():
                threading.Thread(target=window.show, args=(target,), daemon=True).start()
                return self._send(f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">{FONT}<style>{STYLE}</style></head>'
                                  f'<body><main style="text-align:center;margin-top:60px"><div style="font-size:60px">📬</div>'
                                  f'<h1>{e(msg)}</h1><p class="muted">אפשר לסגור את הלשונית הזו ולחזור לחלון של MailBrief.</p>'
                                  '<script>setTimeout(function(){ window.close(); }, 2500);</script></main></body></html>')
            return self._redirect(target)
        if url.path == '/triage':
            return self._send(triage_page())
        if url.path == '/greetings':
            return self._send(greetings_page(parse_qs(url.query).get('msg', [''])[0]))
        if url.path == '/compose':
            return self._send(compose_page(parse_qs(url.query).get('msg', [''])[0]))
        if url.path == '/insights':
            q = parse_qs(url.query)
            return self._send(insights_page(q.get('msg', [''])[0], run=q.get('run', [''])[0] == '1'))
        if url.path.startswith('/reports/'):
            name = os.path.basename(unquote(url.path[9:]))
            path = os.path.join(config.REPORTS, name)
            if name.endswith('.html') and os.path.isfile(path):
                with open(path, 'rb') as f:
                    return self._send(f.read())
        if url.path == '/dashboard':
            return self._send(dashboard_page())
        if url.path == '/today':
            q = parse_qs(url.query)
            return self._send(today_page(q.get('msg', [''])[0], show_all=q.get('all', [''])[0] == '1',
                                         print_now=q.get('print', [''])[0] == '1'))
        if url.path == '/stats':
            return self._send(stats_page())
        if url.path == '/notices':               # the licenses of what is inside MailBrief.exe
            try:
                with open(config.NOTICES_FILE, encoding='utf-8') as f:
                    return self._send(f.read(), 'text/plain; charset=utf-8')
            except OSError:
                return self._send('THIRD-PARTY-NOTICES.txt is missing', 'text/plain', code=404)
        if url.path == '/files':
            return self._send(files_page(parse_qs(url.query).get('msg', [''])[0]))
        if url.path == '/snippets.json':             # the text shortcuts, for the page script
            return self._send(json.dumps(load_json(config.SETTINGS_FILE, {}).get('snippets') or [], ensure_ascii=False),
                              'application/json; charset=utf-8')
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
        if length > config.MAX_UPLOAD + 1_000_000:
            return self._redirect('/?msg=' + quote('הקבצים גדולים מדי — עד 20MB ביחד'))
        body = self.rfile.read(length)
        ctype = self.headers.get('Content-Type', '')
        files = []
        if ctype.startswith('multipart/form-data'):
            raw, files = parse_multipart(ctype, body)
        else:
            raw = parse_qs(body.decode('utf-8'))
        form = {k: v[0] for k, v in raw.items()}
        form['_lists'] = raw                     # multi-value fields (checkbox groups)
        form['_files'] = files                   # [(file name, bytes)]
        if not secrets.compare_digest(form.get('t', ''), TOKEN):
            return self._redirect('/?msg=' + quote('הדף היה ישן (MailBrief עודכן או הופעל מחדש) — הפעולה לא בוצעה. אפשר לנסות שוב עכשיו.'))
        route = urlparse(self.path).path
        try:
            msg = getattr(self, 'post_' + route.strip('/'))(form)
        except AttributeError:
            if not hasattr(self, 'post_' + route.strip('/')):
                return self._send('not found', code=404)
            log_error(f'POST {route}')
            msg = 'שגיאה פנימית — נרשמה ביומן השגיאות'
        except Exception as exc:
            log_error(f'POST {route}')
            msg = f'שגיאה: {exc}'
        if msg is None:                         # handler already answered
            return
        if isinstance(msg, tuple):              # (redirect target, None)
            target = msg[0]
            if window.in_app() and target.startswith(('http://', 'https://')) and not target.startswith(base_url()):
                window.open_external(target)
                back = urlparse(self.headers.get('Referer', '')).path or '/'
                sign_in = route in ('/connect', '/gapps_connect')
                note = ('🔐 נפתח חלון התחברות בדפדפן — אחרי האישור שם, MailBrief יתעדכן כאן לבד' if sign_in
                        else '↗ נפתח בדפדפן')
                return self._redirect(back + ('&' if '?' in back else '?') + 'msg=' + quote(note))
            return self._redirect(target)
        ref = urlparse(self.headers.get('Referer', ''))
        sec = parse_qs(ref.query).get('s', [''])[0] if ref.path == '/' else ''
        self._redirect(('/?s=' + quote(sec) + '&' if re.fullmatch(r'[a-z]{2,10}', sec) else '/?') + 'msg=' + quote(msg))

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
        only = f.get('only', '') or view.current_account()
        path, _ = run_all(open_report=False, only=only or None)
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
        loop = f' ({g("שימי לב", "שים לב", "לתשומת לב")}: זו אחת התיבות שלך — שלא ייווצר כלל הפוך שמחזיר אותם.)' if forward_to.lower() in own else ''
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
        if kind == 'open':
            return (value, None)
        if f.get('back') in ('/insights', '/reading'):
            return (f['back'] + '?msg=' + quote(value), None)
        return value

    def post_first_look(self, f):
        if not load_json(config.ACCOUNTS_FILE, []):
            return 'קודם צריך לחבר תיבת מייל'
        first_look()
        return ('/insights', None)

    def post_remind(self, f):
        days = int(f.get('days', '1')) if f.get('days', '1').isdigit() else 1
        link = f.get('link', '')
        due = add_reminder(days, f.get('subject', '')[:200], f.get('from', '')[:100],
                           link if link.startswith('https://mail.google.com/') else '', f.get('account', ''))
        return ('/today', None) if due else 'שגיאה'

    def post_gapps_connect(self, f):
        accounts = load_json(config.ACCOUNTS_FILE, [])
        acc = next((a for a in accounts if a['id'] == f.get('id') and a.get('auth') == 'google'), None)
        return (start_oauth('google', google_apps.SCOPES, acc['email'] if acc else ''), None)

    def post_gapps_choose(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        settings['gapps_account'] = f.get('email', '')
        save_json(config.SETTINGS_FILE, settings)
        google_apps.forget_cache()
        return f'✓ היומן והמשימות יוצגו מ-{f.get("email", "")}'

    def post_gapps_disconnect(self, f):
        accounts = load_json(config.ACCOUNTS_FILE, [])
        for a in accounts:
            if a['id'] == f.get('id'):
                a['gapps'] = False
        save_json(config.ACCOUNTS_FILE, accounts)
        google_apps.forget_cache()
        return 'היומן והמשימות נותקו מ-MailBrief (המייל ממשיך לעבוד). לביטול מלא אצל Google: myaccount.google.com/connections'

    def _gapps_or_back(self):
        acc = google_apps.gapps_account()
        if not acc:
            raise RuntimeError('היומן והמשימות לא מחוברים — „📅 חיבור יומן ומשימות” בדף ההגדרות')
        return acc

    def _today_back(self, msg=''):
        return ('/today' + ('?msg=' + quote(msg) if msg else ''), None)

    def post_gtask_add(self, f):
        title = f.get('title', '').strip()[:300]
        if not title:
            return self._today_back('צריך לכתוב מה המשימה')
        link = f.get('link', '')
        notes = '\n'.join(x for x in (f.get('from', '')[:100], link if link.startswith('https://mail.google.com/') else '') if x)
        due = f.get('due', '') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', f.get('due', '')) else ''
        try:
            google_apps.add_task(self._gapps_or_back(), title, notes, due)
        except Exception as exc:
            return self._today_back(f'⚠️ {exc}')
        return self._today_back(f'✅ נוספה משימה: {title}')

    def post_gtask_done(self, f):
        try:
            google_apps.complete_task(self._gapps_or_back(), f.get('id', ''))
        except Exception as exc:
            return self._today_back(f'⚠️ {exc}')
        return self._today_back()

    def post_gevent_add(self, f):
        title = f.get('title', '').strip()[:300]
        try:
            day = dt.date.fromisoformat(f.get('day', ''))
        except ValueError:
            return self._today_back('צריך לבחור תאריך')
        at = f.get('at', '') if re.fullmatch(r'\d{2}:\d{2}', f.get('at', '')) else None
        if not title:
            return self._today_back('צריך לכתוב כותרת לאירוע')
        try:
            google_apps.add_event(self._gapps_or_back(), title, day, at=at)
        except Exception as exc:
            return self._today_back(f'⚠️ {exc}')
        return self._today_back(f'📅 נוסף ליומן: {title} ({day:%d/%m}{f" {at}" if at else ""})')

    def post_invite_add(self, f):
        invite = next((i for i in load_json(config.SNAPSHOT_FILE, {}).get('invites', []) if invite_key(i) == f.get('key')), None)
        if not invite:
            return self._today_back('ההזמנה כבר לא ברשימה — אולי היא עברה או בוטלה')
        notes = '\n'.join(x for x in (f'הוזמנת על ידי {invite["from"]} ({invite["account"]})', invite.get('link', '')) if x)
        try:
            google_apps.import_invite(self._gapps_or_back(), event_resource(invite, notes))
        except Exception as exc:
            return self._today_back(f'⚠️ {exc}')
        cache = load_json(config.CACHE_FILE, {})
        cache['invites_added'] = (cache.get('invites_added', []) + [invite_key(invite)])[-300:]
        save_json(config.CACHE_FILE, cache)
        return self._today_back(f'📅 נוסף ליומן: {invite["title"]}')

    def post_welcome(self, f):
        me = save_profile(f.get('name', ''), f.get('form', ''), f['_lists'].get('goal', []))
        hello = f'שלום{" " + me["name"] if me["name"] else ""}! '
        if not load_json(config.ACCOUNTS_FILE, []):
            return hello + g('עכשיו נחברי', 'עכשיו נחבר', 'עכשיו מחברים') + ' את תיבת המייל הראשונה 👇'
        return ('/today' if os.path.exists(config.INSIGHTS_FILE) else '/insights', None)

    def post_view_account(self, f):
        view.set_account(f.get('account', ''))
        back = urlparse(self.headers.get('Referer', '')).path or '/today'
        return (back, None)

    def post_triage_done(self, f):
        triage.dismiss(f.get('key', '')[:400])
        self._send('ok', 'text/plain')
        return None

    def post_triage_undo(self, f):
        triage.undo(f.get('key', '')[:400])
        self._send('ok', 'text/plain')
        return None

    def post_schedule_mail(self, f):
        back = lambda m: ('/compose?msg=' + quote(m), None)
        accounts = load_json(config.ACCOUNTS_FILE, [])
        if not any(a['email'] == f.get('account') for a in accounts):
            return back('צריך לבחור תיבה לשליחה')
        try:
            when = outbox.when_for(f.get('when', 'after_holy'), f.get('custom', ''))
            outbox.schedule(f['account'], f.get('to', ''), f.get('subject', ''), f.get('body', ''), when, files=f['_files'])
        except (ValueError, KeyError) as exc:
            return back(f'⚠️ {exc}')
        return back(f'✓ יישלח ב-{when:%d/%m} בשעה {when:%H:%M}')

    def post_greetings(self, f):
        back = lambda m: ('/greetings?msg=' + quote(m), None)
        wanted = set(f['_lists'].get('to', []))
        people = [p for p in greetings.recipients() if p['email'] in wanted]
        try:
            when = outbox.when_for('custom', f"{f.get('day', '')}T{f.get('at', '10:00') or '10:00'}")
            count = greetings.schedule_greetings(f.get('account', ''), people, f.get('subject', ''), f.get('text', ''), when,
                                                 f.get('my_name', '').strip())
        except ValueError as exc:
            return back(f'⚠️ {exc}')
        return ('/compose?msg=' + quote(f'🗓️ {count} ברכות אישיות יישלחו ב-{when:%d/%m} מ-{when:%H:%M} (בקבוצות קטנות). אפשר לבטל כל אחת כאן.'), None)

    def _snooze_until(self, choice):
        if choice == 'week':
            now = dt.datetime.now().astimezone()
            return outbox.out_of_holy((now + dt.timedelta(days=7)).replace(hour=8, minute=0, second=0, microsecond=0))
        return outbox.when_for(choice)

    def post_snooze(self, f):
        back = urlparse(self.headers.get('Referer', '')).path or '/today'
        try:
            until = self._snooze_until(f.get('when', 'tomorrow8'))
            snooze.snooze(f.get('account', ''), f.get('message_id', ''), f.get('subject', ''), until, f.get('link', ''))
            triage.dismiss(f"{f.get('account', '')}|{f.get('message_id', '')}")
        except Exception as exc:
            if f.get('ajax'):
                self._send(str(exc), 'text/plain; charset=utf-8', code=400)
                return None
            return (back + '?msg=' + quote(f'⚠️ {exc}'), None)
        if f.get('ajax'):
            self._send(f'{until:%d/%m %H:%M}', 'text/plain; charset=utf-8')
            return None
        return (back + '?msg=' + quote(f'💤 יחזור לתיבה ב-{until:%d/%m} בשעה {until:%H:%M}'), None)

    def post_snooze_wake(self, f):
        item = snooze.wake_now(f.get('id', ''))
        return ('/today?msg=' + quote(f'💤 „{item["subject"]}” חזר לתיבה' if item else 'כבר חזר'), None)

    def post_reply_now(self, f):
        """From quick sorting: answer now, or schedule the answer (after Shabbat, tomorrow morning), with files."""
        text, when_choice = f.get('text', ''), f.get('when', 'now')
        try:
            if not text.strip():
                raise RuntimeError('התשובה ריקה')
            if when_choice == 'now':
                to = reply_now(f.get('account', ''), f.get('message_id', ''), text, f['_files'])
                result = f'✉️ נשלח ל-{to}'
            else:
                when = outbox.when_for(when_choice)
                d = reply_details(f.get('account', ''), f.get('message_id', ''))
                outbox.schedule(f['account'], d['to'], d['subject'], text, when, files=f['_files'], thread=d)
                result = f'⏳ יישלח ב-{when:%d/%m %H:%M}'
            triage.dismiss(f"{f.get('account', '')}|{f.get('message_id', '')}")
        except Exception as exc:
            self._send(str(exc), 'text/plain; charset=utf-8', code=400)
            return None
        self._send(result, 'text/plain; charset=utf-8')
        return None

    def post_schedule_cancel(self, f):
        outbox.cancel(f.get('id', ''))
        return ('/compose?msg=' + quote('המייל בוטל ולא יישלח'), None)

    def post_accountant(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        email = f.get('email', '').strip()
        if email and not outbox.EMAIL.fullmatch(email):
            return 'כתובת הרו״ח לא נראית תקינה'
        day = int(f['day']) if f.get('day', '').isdigit() and 1 <= int(f['day']) <= 28 else 2
        settings['accountant'] = {'email': email, 'name': f.get('name', '').strip()[:40], 'day': day,
                                  'account': f.get('account', ''), 'on': f.get('action') == 'on' and bool(email)}
        save_json(config.SETTINGS_FILE, settings)
        return (f'✓ ב-{day} לכל חודש תישלח חבילת החודש הקודם ל-{email}' if settings['accountant']['on']
                else 'השליחה האוטומטית לרו״ח כבויה (ההגדרות נשמרו)')

    def post_accountant_package(self, f):
        month = f.get('month') or accountant.previous_month()
        if not re.fullmatch(r'\d{4}-\d{2}', month):
            return 'חודש לא תקין'
        if f.get('action') == 'send':
            cfg = accountant.accountant_cfg()
            accounts = load_json(config.ACCOUNTS_FILE, [])
            acc = next((a for a in accounts if a['email'] == cfg['account']), accounts[0] if accounts else None)
            if not cfg['email'] or not acc:
                return 'קודם למלא את כתובת הרו״ח ולחבר תיבה'
            count, total, big = accountant.send_package(month, acc, cfg['email'], cfg['name'])
            save_json(config.ACCOUNTS_FILE, accounts)
            return (f'✓ נשלח ל-{cfg["email"]}: {count} מסמכים, {money(total)}' +
                    (' (החבילה גדולה מדי למייל — נשלח האקסל בלבד, והחבילה המלאה בתיקיית הקבלות)' if big else ''))
        path, rows, total = accountant.month_package(month)
        os.startfile(os.path.dirname(path))
        return f'📦 החבילה מוכנה: {len(rows)} מסמכים, {money(total)} — התיקייה נפתחה'

    def post_yearly(self, f):
        year = f.get('year', '')
        if not re.fullmatch(r'20\d\d', year):
            return 'שנה לא תקינה'
        path, count = accountant.yearly_report(int(year))
        os.startfile(os.path.dirname(path))
        return f'📊 הסיכום השנתי ל-{year} מוכן ({count} מסמכים) — „סיכום שנתי {year}.xlsx” בתיקיית הקבלות'

    def post_quiet(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        start = int(f['from']) if f.get('from', '').isdigit() and int(f['from']) < 24 else 22
        end = int(f['to']) if f.get('to', '').isdigit() and int(f['to']) < 24 else 7
        vip = [v.strip() for v in re.split(r'[\s,;]+', f.get('vip', '')) if '.' in v.strip()][:100]
        settings['quiet'] = {'on': f.get('action') != 'off', 'from': start, 'to': end, 'vip': vip}
        save_json(config.SETTINGS_FILE, settings)
        return f'🔕 שעות שקטות: {start:02d}:00–{end:02d}:00 — בלי התראות קופצות (הכול עדיין מופיע ב„היום שלי”)' if settings['quiet']['on'] else '🔔 שעות שקטות כבויות'

    def post_migrate(self, f):
        try:
            count = migrate.import_from(f.get('folder', '') or migrate.previous_copy())
        except ValueError as exc:
            return f'⚠️ {exc}'
        return f'✓ הועברו {count} קבצים — התיבות, הקבלות, הכללים וההגדרות כאן. מה שהיה קודם נשמר בגיבוי.'

    def post_note_save(self, f):
        save_json(config.NOTES_FILE, {'text': f.get('text', '')[:20000], 'at': dt.datetime.now().isoformat(timespec='seconds')})
        self._send('ok', 'text/plain; charset=utf-8')
        return None

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

    # ---- money --------------------------------------------------------------------------------------------------------
    def post_vendor_set(self, f):
        key = f.get('key', '')
        if not key:
            return 'ספק לא מוכר'
        book = f.get('book', '') if f.get('book', '') in books.BOOKS else None
        months = books.set_vendor(key, book=book, no_vat='no_vat' in f, account=f.get('account', '').strip()[:20])
        return f'✓ נשמר — {key}: {book or ""}' + (f' (עודכנו {months} חודשים באקסל)' if months else '')

    def post_export_cfg(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        settings['export'] = {'vat_account': f.get('vat_account', '').strip()[:20], 'supplier_account': f.get('supplier_account', '').strip()[:20],
                              'accounts': {b: f.get(f'acc_{i}', '').strip()[:20] for i, b in enumerate(books.BOOKS) if f.get(f'acc_{i}', '').strip()}}
        save_json(config.SETTINGS_FILE, settings)
        return '✓ מספרי החשבונות נשמרו'

    def post_export_month(self, f):
        month = f.get('month', '')
        if not re.fullmatch(r'\d{4}-\d{2}', month):
            return 'חודש לא תקין'
        path, count = books.export_month(month)
        subprocess.Popen(['explorer', '/select,', path])
        return f'✓ נוצר „{os.path.basename(path)}” עם {count} שורות (בתיקיית הקבלות של החודש)'

    # ---- clients ------------------------------------------------------------------------------------------------------
    def _first_account(self, f):
        return f.get('account', '') or next((a['email'] for a in load_json(config.ACCOUNTS_FILE, [])), '')

    def post_debt_add(self, f):
        try:
            d = clientcare.add_debt(self._first_account(f), f.get('email', ''), f.get('name', ''), f.get('amount', ''),
                                    f.get('invoice', ''), f.get('sent', ''), int(f.get('due_days') or 30), int(f.get('every') or 7),
                                    f.get('text', ''))
        except ValueError as exc:
            return f'⚠️ {exc}'
        return f'✓ {d["name"]} במעקב — תזכורת ראשונה ב-{d["due"][8:10]}/{d["due"][5:7]} אם לא יסומן „שולם”'

    def post_debt_set(self, f):
        status = f.get('status', '')
        if status not in ('paid', 'stopped', 'deleted'):
            return 'פעולה לא מוכרת'
        thanks = ''
        if status == 'paid' and 'thanks' in f:
            try:
                clientcare.send_thanks(f.get('id', ''), f.get('_files', []))
                thanks = ' · 💌 מייל תודה' + (' עם הקבלה' if f.get('_files') else '') + ' יוצא בעוד שתי דקות'
            except ValueError as exc:
                thanks = f' · ⚠️ {exc}'
        clientcare.set_debt(f.get('id', ''), status)
        return {'paid': '✓ סומן כשולם — לא יישלחו עוד תזכורות 🎉', 'stopped': '⏹ התזכורות הופסקו', 'deleted': 'נמחק'}[status] + thanks

    def post_date_add(self, f):
        try:
            d = clientcare.add_date(self._first_account(f), f.get('email', ''), f.get('name', ''), f.get('day', ''),
                                    f.get('kind', 'birthday'), f.get('text', ''))
        except ValueError as exc:
            return f'⚠️ {exc}'
        return f'✓ נשמר — ב-{d["day"]:02d}/{d["month"]:02d} תצא ברכה ל{d["name"]}'

    def post_date_remove(self, f):
        clientcare.remove_date(f.get('id', ''))
        return 'נמחק'

    # ---- tidy ---------------------------------------------------------------------------------------------------------
    def _days(self, f):
        return int(f['days']) if f.get('days', '').isdigit() and int(f['days']) >= 7 else 30

    def post_clean_preview(self, f):
        days = self._days(f)
        rows = cleanup.inbox_preview(days, view.current_account() or None)
        cache = load_json(config.CACHE_FILE, {})
        cache['clean_preview'] = {'at': dt.datetime.now().strftime('%d/%m %H:%M'), 'days': days, 'rows': rows}
        save_json(config.CACHE_FILE, cache)
        return f'🔍 יועברו לארכיון {sum(n for _, n, _ in rows)} מיילים (ישנים מ-{days} ימים, בלי מסומנים ובלי ממתינים). שום דבר לא זז עדיין.'

    def post_clean_inbox(self, f):
        days = self._days(f)
        moved, errors = cleanup.clean_inbox(days, view.current_account() or None)
        cache = load_json(config.CACHE_FILE, {})
        cache.pop('clean_preview', None)
        save_json(config.CACHE_FILE, cache)
        return f'🧹 {moved} מיילים עברו לארכיון — תיבת הדואר הנכנס נקייה יותר ✨' + (' · ' + ' | '.join(errors) if errors else '')

    def post_never_opened(self, f):
        rows = cleanup.never_opened()
        return f'🔍 נמצאו {len(rows)} ניוזלטרים שאף פעם לא נפתחו' if rows else '✓ לא נמצאו ניוזלטרים שלא נפתחו'

    def post_unsub_many(self, f):
        ids = f['_lists'].get('ids', [])
        done, pages = cleanup.unsubscribe_many(ids)
        cache = load_json(config.CACHE_FILE, {})
        if cache.get('never_opened'):
            unsubs = load_json(config.UNSUBS_FILE, {})
            cache['never_opened']['rows'] = [r for r in cache['never_opened']['rows'] if not (unsubs.get(r['id']) or {}).get('done')]
            save_json(config.CACHE_FILE, cache)
        for _, url in pages[:10]:
            window.open_external(url)
        return f'✂️ {done} מנויים בוטלו' + (f' · {len(pages)} נפתחו בדפדפן לסיום הביטול באתר של השולח' if pages else '')

    # ---- budgets, suppliers, tax -------------------------------------------------------------------------------------
    def post_budgets(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        settings['budgets'] = {b: float(f[f'b_{i}']) for i, b in enumerate(books.BOOKS)
                               if re.fullmatch(r'\d{1,7}(\.\d+)?', f.get(f'b_{i}', '').strip()) and float(f[f'b_{i}']) > 0}
        save_json(config.SETTINGS_FILE, settings)
        return f'✓ נשמרו {len(settings["budgets"])} תקציבים'

    def post_tax_collect(self, f):
        year = int(f['year']) if f.get('year', '').isdigit() else dt.date.today().year
        folder, count = budget.collect_tax_documents(year)
        os.startfile(folder)
        return f'📁 נאספו {count} קבצים להחזר מס {year} — עם אקסל מסכם'

    # ---- snippets -----------------------------------------------------------------------------------------------------
    def post_snippet_add(self, f):
        key, text = f.get('key', '').strip().lstrip(';')[:20], f.get('text', '').strip()[:3000]
        if not key or not text or re.search(r'[\s;]', key):
            return 'צריך קיצור בלי רווחים ונוסח'
        settings = load_json(config.SETTINGS_FILE, {})
        settings['snippets'] = [s for s in settings.get('snippets') or [] if s['key'] != key] + [{'key': key, 'text': text}]
        save_json(config.SETTINGS_FILE, settings)
        return f'✓ הקיצור ;{key} נשמר — כותבים ;{key} ורווח'

    def post_snippet_delete(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        settings['snippets'] = [s for s in settings.get('snippets') or [] if s['key'] != f.get('key')]
        save_json(config.SETTINGS_FILE, settings)
        return 'הקיצור נמחק'

    # ---- leaks, sharing -----------------------------------------------------------------------------------------------
    def post_hibp(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        if f.get('action') == 'off':
            settings.pop('hibp', None)
            save_json(config.SETTINGS_FILE, settings)
            return 'המפתח הוסר'
        if f.get('key', '').strip():
            settings['hibp'] = {'key': encrypt(f['key'].strip())}
            save_json(config.SETTINGS_FILE, settings)
        if f.get('action') == 'check' or f.get('key', '').strip():
            fresh, error = security.check_leaks(force=True)
            if error:
                return f'⚠️ {error}'
            found = sum(len(v) for v in (load_json(config.CACHE_FILE, {}).get('leaks') or {}).get('results', {}).values())
            return f'🔓 נמצאו {found} דליפות ישנות או חדשות — הפרטים למטה. כדאי להחליף סיסמה בשירותים האלה.' if found else '✓ הכתובות שלך לא נמצאו בדליפות ידועות'
        return 'צריך מפתח'

    def post_share(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        labels = [l for l in f['_lists'].get('label', []) if l]
        before = (settings.get('share') or {}).get('on', False)
        settings['share'] = {'on': True if f.get('action') == 'on' else False if f.get('action') == 'off' else before,
                             'email': f.get('email', '').strip(), 'name': f.get('name', '').strip()[:40], 'labels': labels,
                             'account': f.get('account', '')}
        save_json(config.SETTINGS_FILE, settings)
        if f.get('action') == 'test':
            try:
                count = sharing.send_share(load_json(config.ACCOUNTS_FILE, []))
            except RuntimeError as exc:
                return f'⚠️ {exc}'
            return f'📨 נשלח לניסיון ל-{settings["share"]["email"]} ({count} מיילים בשבוע האחרון)'
        return ('✓ הדוח השבועי פעיל — כל יום ראשון בבוקר' if settings['share']['on'] else 'הדוח השבועי כבוי')

    # ---- attachments --------------------------------------------------------------------------------------------------
    def post_files_scan(self, f):
        rows, errors = files.scan_files()
        return ('/files?msg=' + quote(f'📎 {len(rows)} קבצים ב-30 הימים האחרונים' + (' · ' + ' | '.join(errors) if errors else '')), None)

    def post_file_get(self, f):
        try:
            folder = files.save_message_files(f.get('account', ''), f.get('message_id', ''))
        except RuntimeError as exc:
            return ('/files?msg=' + quote(f'⚠️ {exc}'), None)
        os.startfile(folder)
        return ('/files?msg=' + quote(f'⬇️ נשמר בתיקייה „{os.path.basename(folder)}” (בתוך „הורדות”)'), None)

    # ---- Google Drive backup ------------------------------------------------------------------------------------------
    def post_drive_connect(self, f):
        accounts = load_json(config.ACCOUNTS_FILE, [])
        acc = next((a for a in accounts if a['id'] == f.get('id') and a.get('auth') == 'google'), None)
        return (start_oauth('google', DRIVE_SCOPE, acc['email'] if acc else ''), None)

    def post_cloud_upload(self, f):
        password = f.get('password', '')
        try:
            name = cloud_backup.upload(password)
        except RuntimeError as exc:
            return f'⚠️ {exc}'
        cloud_backup.save_cfg('auto' in f, password if 'auto' in f else '')
        return f'☁️ הגיבוי המוצפן נשמר ב-Google Drive ({name})' + (' · מעכשיו גם אוטומטית כל שבוע' if 'auto' in f else '')

    def post_cloud_list(self, f):
        acc = cloud_backup.drive_account()
        if not acc:
            return 'קודם צריך לחבר את Google Drive'
        files = cloud_backup.remote_backups(acc)
        cache = load_json(config.CACHE_FILE, {})
        cache['cloud_files'] = files
        save_json(config.CACHE_FILE, cache)
        return f'☁️ {len(files)} גיבויים ב-Drive' if files else 'עוד אין גיבויים ב-Drive'

    def post_cloud_restore(self, f):
        try:
            name = cloud_backup.download(f.get('id', ''), f.get('password', ''))
        except (RuntimeError, ValueError) as exc:
            return f'⚠️ {exc}'
        count = restore_backup(name)
        return f'✓ שוחזרו {count} קבצים מהגיבוי ב-Drive. אם זה מחשב חדש — צריך להתחבר מחדש לתיבות (בלשונית 📬 תיבות).'

    def post_problem_report(self, f):
        path = problem_report()
        subprocess.Popen(['explorer', '/select,', path])
        return ('/help?msg=' + quote(f'✓ הדוח נשמר בשולחן העבודה: {os.path.basename(path)} — בלי תוכן מיילים, סיסמאות או מפתחות, '
                                     'והכתובות מוסתרות. אפשר לצרף אותו לפנייה.') + '#report', None)

    def post_backup_now(self, f):
        path = make_backup('manual')
        return ('/help?msg=' + quote(f'✓ נשמר גיבוי: {os.path.basename(path)}'), None)

    def post_restore(self, f):
        count = restore_backup(f.get('name', ''))
        return ('/help?msg=' + quote(f'✓ שוחזרו {count} קבצים. גיבוי של המצב הקודם נשמר, למקרה שצריך לחזור אליו.'), None)

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

    def post_daily(self, f):
        settings = load_json(config.SETTINGS_FILE, {})
        hour = int(f['hour']) if f.get('hour', '').isdigit() and 5 <= int(f['hour']) <= 22 else 7
        settings['daily'] = {'on': f.get('action') != 'off', 'hour': hour, 'account': f.get('account', '')}
        save_json(config.SETTINGS_FILE, settings)
        if f.get('action') == 'off':
            return 'הסיכום היומי כבוי'
        return f'✓ כל יום ב-{hour:02d}:00 יגיע סיכום קצר ל-{f.get("account", "")} (לא בשבת ובחג)'

    def post_daily_test(self, f):
        accounts = load_json(config.ACCOUNTS_FILE, [])
        acc = daily_account(accounts)
        if not acc:
            return 'קודם צריך לחבר תיבת מייל'
        subject = send_daily(acc)
        save_json(config.ACCOUNTS_FILE, accounts)
        return f'✓ נשלח ל-{acc["email"]}: „{subject}” — אפשר לבדוק בטלפון'

    def post_profile(self, f):
        me = save_profile(f.get('name', ''), f.get('form', ''), f['_lists'].get('goal', []))
        return f'✓ נשמר — {me["name"] or "בלי שם"}, {FORMS[me["form"]][1]}'

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
                return self._wf_back(f'בתזמון אפשר רק: {", ".join(ACTIONS[k][0] for k in sorted(SCHEDULE_ACTIONS))} (לא: {", ".join(bad)})')
        wf = {'id': secrets.token_hex(4), 'name': name, 'enabled': True, 'trigger': trigger, 'conditions': conditions,
              'actions': actions, 'created': dt.datetime.now().astimezone().isoformat()}
        if trigger == 'waiting':
            wf['wait_days'] = max(1, min(30, int(f.get('wait_days') or 3)))
        if trigger == 'schedule':
            days = [int(d) for d in f['_lists'].get('day', []) if d.isdigit() and int(d) in dict((d, n) for n, d in WEEKDAYS)]
            wf['schedule'] = {'days': days or [6], 'hour': max(7, min(23, int(f.get('hour') or 9)))}
        save_json(config.WF_FILE, workflows() + [wf])
        warn = f' {g("שימי לב", "שים לב", "לתשומת לב")}: תשובה אוטומטית נשלחת לאנשים אמיתיים.' if any(a['type'] == 'auto_reply' for a in actions) else ''
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
        notify.toast('📬 MailBrief — התראת ניסיון', ['ככה ייראו התראות על מייל דחוף או חריג.'], link())
        return '✓ נשלחה התראת ניסיון — היא אמורה להופיע בפינת המסך'

    def post_check(self, f):
        only = f.get('only', '') or view.current_account()
        count = check_alerts(only=only or None)
        if only:
            return (f'✓ {only} נבדקה — ' + (f'{count} הודעות להתראה' if count else 'אין כרגע משהו דחוף או חריג'))
        return f'✓ נמצאו {count} הודעות חדשות להתראה' if count else '✓ נבדק — אין כרגע משהו דחוף או חריג'

    def post_quit(self, f):
        self._send(f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">{FONT}<style>{STYLE}</style></head>'
                   '<body><main><h1>MailBrief נסגר 👋</h1><p class="muted">הריצות המתוזמנות ממשיכות לעבוד. '
                   'לפתיחה מחדש: הקיצור MailBrief בשולחן העבודה.</p></main></body></html>')
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        close_tray()
        window.quit_app()
        return None

    def post_update(self, f):
        rel = update_available()
        if not rel:
            return 'יש כבר את הגרסה האחרונה ✓'
        start_update(rel)
        self._send(f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">{FONT}<style>{STYLE}</style></head>'
                   f'<body><main style="text-align:center;margin-top:60px"><div style="font-size:64px" class="floaty">✨</div>'
                   f'<h1>מתעדכן לגרסה {e(rel["version"])}…</h1><p class="muted">MailBrief ייפתח מחדש בעוד רגע. אפשר לסגור את הלשונית הזו.</p>'
                   '<script>setTimeout(function(){ setInterval(function(){ fetch("/today", {cache: "no-store"}).then(function(r){ if (r.ok) location.href = "/today"; }).catch(function(){}); }, 1500); }, 4000);</script>'
                   '</main></body></html>')
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        close_tray()
        threading.Timer(1.5, window.quit_app).start()      # let the page above show first
        return None

    def post_setup(self, f):
        if f.get('action') == 'remove':
            setup.remove()
            return 'התזמונים הוסרו — MailBrief ירוץ רק כשפותחים אותו. אפשר להחזיר באותו כפתור.'
        setup.install()
        return '✓ התזמונים נרשמו: תדריך ביום ראשון 8:00, בדיקה כל שעה 7:00–23:00, „היום שלי” בכניסה ל-Windows'

    def post_pause(self, f):
        until = pause_for(f.get('mode', 'off'))
        return f'⏸️ האוטומציות וההתראות מושהות עד {until:%d/%m %H:%M}' if until else '▶️ ההשהיה בוטלה — הכול פועל כרגיל'


def _ensure_setup():
    try:
        setup.ensure()
    except Exception:
        with open(os.path.join(config.DATA, 'setup.log'), 'w', encoding='utf-8') as f:
            f.write(traceback.format_exc())


def allowed_hosts():
    ports = {config.PORT, config.NICE_PORT}
    hosts = {f'{h}:{p}' for h in ('127.0.0.1', 'localhost', config.NICE_HOST) for p in ports}
    return hosts | ({config.NICE_HOST} if config.NICE_PORT == 80 else set())


def parse_multipart(ctype, body):
    """Fields and files of a multipart form — with the standard email parser (the cgi module is gone since 3.13)."""
    import email
    from email import policy
    msg = email.message_from_bytes(b'Content-Type: ' + ctype.encode('latin-1') + b'\r\n\r\n' + body, policy=policy.HTTP)
    fields, files = {}, []
    for part in msg.iter_parts():
        name = part.get_param('name', header='content-disposition')
        filename = part.get_filename()
        data = part.get_payload(decode=True) or b''
        if filename:
            if data:
                files.append((filename, data))
        elif name:
            fields.setdefault(name, []).append(data.decode('utf-8', 'replace'))
    return fields, files


class LocalServer(ThreadingHTTPServer):
    """On Windows, SO_REUSEADDR lets a second program bind the same port — that is how two MailBriefs (and two icons
    next to the clock) could run at once. Exclusive binding makes the second attempt fail instead."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


_INSTANCE = []      # keeps the mutex handle for the life of the process


def first_instance():
    """One MailBrief window/tray per Windows user: a named mutex, released automatically when the process ends."""
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, 'Local\\MailBrief-app')
        already = ctypes.get_last_error() == 183          # ERROR_ALREADY_EXISTS
    except Exception:
        return True
    _INSTANCE.append(handle)
    return not already


def serve(start_page=''):
    os.makedirs(config.DATA, exist_ok=True)
    if not first_instance():                     # already running: ask it to show its window
        _show_running_copy(start_page)
        return
    try:
        server = LocalServer(("127.0.0.1", config.PORT), Handler)
    except OSError:                              # the port is taken (an older copy still running): just show it
        open_window(link(start_page))
        return
    servers = [server]
    try:                                         # the port-less address, when nothing else uses port 80
        servers.append(LocalServer(("127.0.0.1", config.NICE_PORT), Handler))
        remember(config.NICE_PORT)
    except OSError:
        remember(config.PORT)
    workers = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for worker in workers:
        worker.start()
    threading.Thread(target=_ensure_setup, daemon=True).start()    # a new computer: scheduled runs + Start menu
    threading.Thread(target=_outbox_timer, daemon=True).start()
    worker = workers[0]
    try:
        if window.available():                   # a real window (WebView2) on the main thread, the tray icon beside it
            threading.Thread(target=_tray_thread, daemon=True).start()
            window.run_app(link(start_page), on_hidden=_hidden_hint)
            close_tray()
        else:                                    # from source without pywebview: browser window + tray
            open_window(link(start_page))
            try:
                run_tray()                       # returns when the user picks "Exit"
            except Exception:
                _log_tray()
                worker.join()                    # no tray: keep serving until "⏻ Close" on the page
    finally:
        for s in servers:
            s.shutdown()


def _outbox_timer():
    import time
    while True:
        time.sleep(120)
        try:
            if any(it['status'] == 'waiting' for it in outbox.outbox()):
                outbox.send_due()
            if snooze.snoozed():
                snooze.wake_due()
        except Exception:
            pass


def _log_tray():
    with open(os.path.join(config.DATA, 'tray.log'), 'w', encoding='utf-8') as f:
        f.write(traceback.format_exc())


def _tray_thread():
    try:
        run_tray(on_exit=window.quit_app)
    except Exception:
        _log_tray()


def _hidden_hint():
    notify.toast('📬 MailBrief ממשיך לעבוד ליד השעון', ['לחיצה כפולה על הסמל מחזירה את החלון. יציאה מלאה — מהתפריט של הסמל.'])


def _show_running_copy(start_page):
    import urllib.request
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{config.PORT}/_show?page={quote(start_page)}',
                                     headers={'Host': f'127.0.0.1:{config.PORT}'})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        open_window(link(start_page))            # an older copy without /_show: at least open a window
