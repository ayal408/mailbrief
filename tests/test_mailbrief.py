"""Offline regression tests for MailBrief — no network, no mailbox, no real sending.

    python -m unittest discover -s tests -v
"""
import datetime as dt
import email
import os
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from email.policy import default
from unittest import mock

from mailbrief import config, net, storage
from mailbrief.features import automations, calendar, forwarding, google_apps, maintenance, notify, replies
from mailbrief.mail import accounts, classify as sorting, imap, message, smtp
from mailbrief.money import ledger

IL = dt.timezone(dt.timedelta(hours=3))


def mk(frm, subject, text, when='Wed, 23 Sep 2026 10:00:00 +0300', html=None, headers=None, attach=None):
    m = EmailMessage()
    m['From'], m['To'], m['Subject'], m['Date'] = frm, 'me@gmail.com', subject, when
    m['Message-ID'] = f'<{abs(hash(frm + subject + when))}@test>'
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype='html')
    if attach:
        name, data = attach
        m.add_attachment(data, maintype='application', subtype='octet-stream', filename=name)
    return email.message_from_bytes(m.as_bytes(), policy=default)


class Isolated(unittest.TestCase):
    """Every test writes into a throwaway data folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = []
        for name in dir(config):
            value = getattr(config, name)
            if name.isupper() and isinstance(value, str) and value.startswith(config.HERE) and name != 'HERE':
                self.patches.append(mock.patch.object(config, name, value.replace(config.HERE, self.tmp, 1)))
        for p in self.patches:
            p.start()
        os.makedirs(config.DATA, exist_ok=True)
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'me@gmail.com', 'host': 'imap.gmail.com'}])

    def tearDown(self):
        for p in self.patches:
            p.stop()


class Classification(Isolated):
    def test_categories(self):
        cases = [
            (mk('Anthropic <invoice+statements@mail.anthropic.com>', 'Your receipt', 'Receipt ₪59.00 paid'), 'receipts'),
            (mk('Google <no-reply@accounts.google.com>', 'התראת אבטחה', 'נתת לאפליקציה Make גישה'), 'signins'),
            (mk('Ruben <ruben@substack.com>', 'Pareto.', 'hi', headers={'List-Unsubscribe': '<mailto:u@s.com>'}), 'newsletters'),
            (mk('Dana <dana@client.co.il>', 'פגישה', 'נפגש מחר?'), 'people'),
        ]
        for msg, cat in cases:
            self.assertIn(cat, sorting.classify(msg, 'me@gmail.com')['cats'], msg['Subject'])

    def test_amount_and_book(self):
        it = sorting.classify(mk('פז <billing@paz.co.il>', 'חשבונית מס על תדלוק', 'סה"כ 312.40 ש"ח'), 'me@gmail.com')
        self.assertEqual((it['amount'], it['book']), ('₪312.40', 'רכב'))

    def test_short_plain_body_is_read(self):              # regression: text-only mail used to come back empty
        it = sorting.classify(mk('Supplier <billing@supplier.co.il>', 'חשבונית 77', 'סה"כ ₪1,250.00', attach=('a.pdf', b'%PDF')), 'me@gmail.com')
        self.assertEqual(it['amount'], '₪1,250.00')

    def test_html_placeholder_falls_back_to_html(self):
        plain = 'This message was designed to be viewed as HTML. ' * 5
        msg = mk('Isracard <info@isracard.co.il>', 'פירוט', plain, html='<p>חיוב של ₪100.00</p>')
        self.assertIn('₪100.00', message.body_text(msg))

    def test_auto_reply_and_bulk_are_not_people(self):
        auto = mk('X <x@gmail.com>', 'Re: שאלה', 'auto', headers={'Auto-Submitted': 'auto-replied'})
        self.assertNotIn('people', sorting.classify(auto, 'me@gmail.com')['cats'])

    def test_repeated_company_sender_is_demoted(self):
        items = [sorting.classify(mk('Yossi <yossi@jobsite.co.il>', f'משרה {i}', 'x'), 'me@gmail.com') for i in range(3)]
        self.assertTrue(all('people' in i['cats'] for i in items))      # each one alone looks personal
        sorting.demote_automated(items, ['me@gmail.com'])
        self.assertTrue(all('newsletters' in i['cats'] and 'people' not in i['cats'] for i in items))

    def test_unusual_security_only_for_real_changes(self):
        self.assertTrue(sorting.RX['unusual'].search('מספר הטלפון לשחזור חשבון השתנה'))
        self.assertFalse(sorting.RX['unusual'].search('אם לא ביקשת קוד אישור, יש להתעלם. כניסה ממכשיר חדש'))


class Phishing(Isolated):
    def test_fakes_are_caught(self):
        fake = mk('בנק לאומי <leumi.security@gmail.com>', 'החשבון שלך יושעה', 'אמתו את החשבון',
                  html='<a href="http://185.22.1.9/x">www.leumi.co.il</a>')
        self.assertIn('phishing', sorting.classify(fake, 'me@gmail.com')['cats'])
        exe = mk('A <a@b.co.il>', 'Invoice', 'x', headers={'Authentication-Results': 'mx; spf=fail; dmarc=fail'},
                 attach=('invoice.pdf.exe', b'MZ'))
        self.assertIn('phishing', sorting.classify(exe, 'me@gmail.com')['cats'])

    def test_legit_mail_scores_low(self):
        github = mk('GitHub <notifications@github.com>', 'Re: PR', 'x', html='<a href="https://github.com/a/b">firestore.rules</a>')
        news = mk('Ruben <ruben@substack.com>', 'News', 'x', html='<a href="https://substack.com/redirect/1">claude.ai</a>',
                  headers={'Authentication-Results': 'mx; dkim=pass; spf=pass; dmarc=pass'})
        isracard = mk('בנק לאומי מגיע מישראכרט <info@isracard.co.il>', 'פירוט', 'x')
        for msg in (github, news, isracard):
            self.assertLess(sorting.classify(msg, 'me@gmail.com')['phish'], sorting.PHISH_THRESHOLD, msg['From'])


class Dates(Isolated):
    def test_due_dates(self):
        soon = dt.date.today() + dt.timedelta(days=30)
        self.assertEqual(sorting.find_due_date(f'לתשלום עד {soon:%d/%m/%Y}'), soon.isoformat())
        self.assertEqual(sorting.find_due_date(f'Payment due {soon:%b} {soon.day}, {soon.year}'), soon.isoformat())
        self.assertEqual(sorting.find_due_date(f'תאריך: {soon:%d/%m/%Y}'), '')
        far = dt.date.today() + dt.timedelta(days=400)
        self.assertEqual(sorting.find_due_date(f'לתשלום עד {far:%d/%m/%Y}'), '')             # more than a year ahead
        self.assertEqual(sorting.find_due_date('לתשלום עד 15/10/2019'), '')

    def test_holy_windows_merge_and_margin(self):
        items = {'items': [{'category': 'candles', 'date': '2026-09-25T18:12:00+03:00'},
                           {'category': 'havdalah', 'date': '2026-09-26T19:07:00+03:00'}]}
        with mock.patch.object(net, 'cached_json', return_value=items):
            self.assertTrue(calendar.is_holy_time(dt.datetime(2026, 9, 25, 17, 50, tzinfo=IL)))     # 30-minute margin
            self.assertTrue(calendar.is_holy_time(dt.datetime(2026, 9, 26, 12, 0, tzinfo=IL)))
            self.assertFalse(calendar.is_holy_time(dt.datetime(2026, 9, 26, 19, 30, tzinfo=IL)))
            self.assertFalse(calendar.is_holy_time(dt.datetime(2026, 9, 27, 10, 0, tzinfo=IL)))     # Chol HaMoed

    def test_offline_fallback_is_conservative(self):
        with mock.patch.object(calendar, 'holy_windows', return_value=None):
            self.assertTrue(calendar.is_holy_time(dt.datetime(2026, 9, 25, 15, 0, tzinfo=IL)))
            self.assertFalse(calendar.is_holy_time(dt.datetime(2026, 9, 23, 12, 0, tzinfo=IL)))


class Money(Isolated):
    def test_duplicates_only_same_kind_within_five_days(self):
        book = {'a': {'date': '2026-09-01', 'vendor_key': 'github.com', 'amount': 4.0, 'subject': 'Invoice 1'}}
        self.assertEqual(ledger.find_duplicate(book, 'b', 'github.com', 4.0, '2026-09-03', 'Invoice 2'), '2026-09-01')
        self.assertEqual(ledger.find_duplicate(book, 'b', 'github.com', 4.0, '2026-09-03', 'Receipt 2'), '')
        self.assertEqual(ledger.find_duplicate(book, 'b', 'github.com', 4.0, '2026-10-01', 'Invoice 3'), '')

    def test_free_mail_senders_are_not_one_vendor(self):
        self.assertNotEqual(ledger.vendor_key('a@gmail.com'), ledger.vendor_key('b@gmail.com'))
        self.assertEqual(ledger.vendor_key('x@billing.paz.co.il'), 'paz.co.il')

    def test_xlsx_is_a_valid_workbook(self):
        book = {'x': {'date': '2026-09-01', 'vendor': 'GitHub', 'email': 'b@github.com', 'vendor_key': 'github.com',
                        'subject': 'Invoice', 'amount': 4.0, 'currency': '$', 'rate': 3.012, 'amount_ils': 12.05,
                        'book': 'תוכנה ומנויים', 'account': 'me', 'files': [], 'rules': []}}
        ledger.write_month_xlsx('2026-09', book)
        path = os.path.join(config.RECEIPTS_DIR, '2026-09', 'קבלות 2026-09.xlsx')
        with zipfile.ZipFile(path) as z:
            self.assertIn('xl/worksheets/sheet1.xml', z.namelist())
            sheet = z.read('xl/worksheets/sheet1.xml').decode('utf-8')
        self.assertIn('rightToLeft="1"', sheet)
        self.assertIn('SUM(H2:H2)', sheet)


class Sending(Isolated):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.patches += [mock.patch.object(smtp, 'send_mail', lambda acc, m: self.sent.append(m)),
                         mock.patch.object(notify, 'toast', lambda *a, **k: None)]
        for p in self.patches[-2:]:
            p.start()

    def test_forward_only_after_rule_and_once(self):
        created = dt.datetime(2026, 9, 22, 12, 0, tzinfo=dt.timezone.utc).isoformat()
        rules = [{'id': '1', 'field': 'from', 'contains': 'client.co.il', 'label': 'לקוח', 'forward_to': 'cpa@x.com', 'created': created}]
        pending = []
        for msg in (mk('C <c@client.co.il>', 'after', 'x', 'Tue, 22 Sep 2026 20:00:00 +0000'),
                    mk('C <c@client.co.il>', 'before', 'x', 'Mon, 21 Sep 2026 20:00:00 +0000'),
                    mk('C <c@client.co.il>', 'ours', 'x', 'Tue, 22 Sep 2026 21:00:00 +0000', headers={'X-MailBrief-Forwarded': '1'})):
            it = sorting.classify(msg, 'me@gmail.com', rules)
            it['message_id'] = msg['Message-ID']
            pending.append((it, msg))
        state = {}
        self.assertEqual(forwarding.process_forwards({'email': 'me@gmail.com'}, pending, state), 1)
        self.assertEqual(forwarding.process_forwards({'email': 'me@gmail.com'}, pending, state), 0)

    def test_auto_reply_guards(self):
        wf = {'id': 'w', 'name': 'מענה', 'enabled': True, 'trigger': 'new_mail', 'created': '2026-09-01T00:00:00+03:00',
              'conditions': [], 'actions': [{'type': 'auto_reply', 'param': 'תודה {from_name}'}]}
        storage.save_json(config.WF_FILE, [wf])
        pairs = []
        for msg in (mk('Dana <dana@client.co.il>', 'שאלה', 'x'), mk('Dana <dana@client.co.il>', 'עוד', 'x'),
                    mk('Shop <n@shop.com>', 'מבצע', 'x', headers={'List-Unsubscribe': '<mailto:u@s.com>'}),
                    mk('Bot <b@y.com>', 'Re', 'x', headers={'Auto-Submitted': 'auto-replied'})):
            it = sorting.classify(msg, 'me@gmail.com')
            it['uid'] = '1'
            pairs.append((it, msg))
        automations.run_workflows(None, {'email': 'me@gmail.com'}, pairs, {}, {}, [40])
        self.assertEqual([m['To'] for m in self.sent], ['dana@client.co.il'])
        self.assertEqual(self.sent[0]['Auto-Submitted'], 'auto-replied')

    def test_vacation_once_per_person(self):
        today = dt.date.today()
        storage.save_json(config.SETTINGS_FILE, {'vacation': {'from': (today - dt.timedelta(days=1)).isoformat(),
                                                     'to': (today + dt.timedelta(days=3)).isoformat(), 'message': ''}})
        now = email.utils.format_datetime(dt.datetime.now().astimezone())
        pairs = [(sorting.classify(m, 'me@gmail.com'), m) for m in (mk('Dana <dana@client.co.il>', 'a', 'x', now),
                                                               mk('Dana <dana@client.co.il>', 'b', 'x', now))]
        state = {}
        self.assertEqual(replies.vacation_replies({'email': 'me@gmail.com'}, pairs, state), 1)
        self.assertEqual(replies.vacation_replies({'email': 'me@gmail.com'}, pairs, state), 0)


class Safety(Isolated):
    def test_unsubscribe_links_must_be_public_https(self):
        self.assertFalse(net.safe_public_https('http://example.com/u'))
        self.assertFalse(net.safe_public_https('https://127.0.0.1/u'))
        self.assertFalse(net.safe_public_https('https://192.168.1.1/u'))

    def test_dpapi_round_trip(self):
        self.assertEqual(storage.decrypt(storage.encrypt('סוד-123')), 'סוד-123')

    def test_utf7_folder_names(self):
        self.assertEqual(imap.utf7('A&B'), 'A&-B')
        self.assertTrue(imap.utf7('אוטומטי').startswith('&'))

    def test_backup_and_restore(self):
        storage.save_json(config.RULES_FILE, [{'id': '1', 'label': 'לפני'}])
        with mock.patch.object(config, 'RULES_FILE', os.path.join(config.DATA, 'rules.json')):
            storage.save_json(config.RULES_FILE, [{'id': '1', 'label': 'לפני'}])
            name = os.path.basename(maintenance.make_backup('manual'))
            storage.save_json(config.RULES_FILE, [])
            maintenance.restore_backup(name)
            self.assertEqual(storage.load_json(config.RULES_FILE, [])[0]['label'], 'לפני')
            self.assertTrue(any('before-restore' in b for b in maintenance.list_backups()))


class GoogleApps(Isolated):
    G = {'id': 'g1', 'email': 'me@gmail.com', 'auth': 'google', 'gapps': True, 'refresh': 'x'}

    def test_bodies(self):
        self.assertEqual(google_apps.task_body('לשלם', due='2026-10-15')['due'], '2026-10-15T00:00:00.000Z')
        self.assertNotIn('due', google_apps.task_body('בלי תאריך'))
        allday = google_apps.event_body('חשבון', dt.date(2026, 10, 15))
        self.assertEqual((allday['start'], allday['end']), ({'date': '2026-10-15'}, {'date': '2026-10-16'}))
        timed = google_apps.event_body('פגישה', dt.date(2026, 10, 15), at='09:30')
        self.assertEqual(timed['end']['dateTime'], '2026-10-15T10:30:00')

    def test_actions_use_due_date_and_skip_shabbat(self):
        storage.save_json(config.ACCOUNTS_FILE, [self.G])
        wf = {'id': 'w', 'name': 'בדיקה'}
        ctx = {'subject': 'חשבון חשמל', 'from': 'b@iec.co.il', 'from_name': 'חברת החשמל', 'amount': '₪300', 'due': '2026-10-15', 'link': ''}
        with mock.patch.object(google_apps, 'add_task') as task, mock.patch.object(google_apps, 'add_event') as event:
            self.assertTrue(automations.run_action({'type': 'gtask', 'param': 'לשלם ל-{from_name}'}, wf, self.G, ctx).startswith('✓'))
            self.assertEqual(task.call_args[0][1:], ('לשלם ל-חברת החשמל', 'חברת החשמל <b@iec.co.il>\nסכום: ₪300\n⚡ בדיקה', '2026-10-15'))
            automations.run_action({'type': 'gevent'}, wf, self.G, ctx)
            self.assertEqual(event.call_args[0][1:3], ('חשבון חשמל', dt.date(2026, 10, 15)))
            friday = dt.date(2026, 9, 25)
            with mock.patch.object(automations.dt, 'date', wraps=dt.date) as fake:
                fake.today.return_value = friday
                automations.run_action({'type': 'gevent'}, wf, self.G, ctx | {'due': ''})
            self.assertEqual(event.call_args[0][2], dt.date(2026, 9, 27))      # Sunday, not Shabbat

    def test_not_connected_is_a_clear_message(self):
        result = automations.run_action({'type': 'gtask'}, {'id': 'w', 'name': 'x'}, self.G, {'subject': 's'})
        self.assertIn('לא מחוברים', result)

    def test_reconnect_keeps_settings_and_reads_granted_scopes(self):
        storage.save_json(config.ACCOUNTS_FILE, [{'id': 'keep', 'email': 'me@gmail.com', 'auth': 'google', 'tag': False,
                                                  'refresh': 'old', 'last': {'error': 'פגה'}}])
        from mailbrief.mail import oauth
        oauth.PENDING['s'] = ('google', 'v', google_apps.SCOPES)
        token = {'refresh_token': 'new', 'id_token': 'h.' + message_b64({'email': 'me@gmail.com'}) + '.s',
                 'scope': 'openid https://mail.google.com/ ' + google_apps.SCOPES}
        with mock.patch.object(accounts, 'token_request', return_value=token), mock.patch.object(imap, 'connect'):
            self.assertIn('מחוברים', accounts.finish_oauth({'state': ['s'], 'code': ['c']}))
        acc = storage.load_json(config.ACCOUNTS_FILE, [])[0]
        self.assertEqual((acc['id'], acc['tag'], acc['gapps'], 'last' in acc), ('keep', False, True, False))

    def test_disabled_api_explained(self):
        import io
        import urllib.error
        err = urllib.error.HTTPError('u', 403, 'x', {}, io.BytesIO(b'{"error":{"reason":"accessNotConfigured"}}'))
        with mock.patch.object(google_apps, '_token', return_value='t'),                 mock.patch.object(google_apps.urllib.request, 'urlopen', side_effect=err):
            with self.assertRaisesRegex(RuntimeError, 'להפעיל את Google Tasks API'):
                google_apps.open_tasks(self.G)

    def test_overview_keeps_one_failure_separate(self):
        storage.save_json(config.ACCOUNTS_FILE, [self.G])
        with mock.patch.object(google_apps, 'events_on', return_value=[{'title': 'x'}]),                 mock.patch.object(google_apps, 'open_tasks', side_effect=RuntimeError('כבוי')):
            view = google_apps.today_overview()
        self.assertEqual((view['events'], view['tasks_error']), ([{'title': 'x'}], 'כבוי'))
        storage.save_json(config.ACCOUNTS_FILE, [self.G | {'gapps': False}])
        self.assertIsNone(google_apps.today_overview())


ICS = ('BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nBEGIN:VTIMEZONE\r\nTZID:Israel Standard Time\r\nEND:VTIMEZONE\r\n'
       'BEGIN:VEVENT\r\nUID:abc-123@outlook\r\nSUMMARY:פגישת רבעון\\, סיכום\r\n'
       'DTSTART;TZID=Israel Standard Time:20261005T100000\r\nDTEND;TZID=Israel Standard Time:20261005T113000\r\n'
       'LOCATION:משרד\\, קומה 3\r\nORGANIZER;CN=Dana:mailto:dana@client.co.il\r\nDESCRIPTION:long line that is\r\n  folded\r\n'
       'END:VEVENT\r\nEND:VCALENDAR\r\n')


class Invites(Isolated):
    def test_outlook_invite(self):
        from mailbrief.features import invites
        inv = invites.parse_ics(ICS)
        self.assertEqual((inv['title'], inv['start'], inv['end'], inv['zone'], inv['where'], inv['organizer'], inv['cancelled']),
                         ('פגישת רבעון, סיכום', '2026-10-05T10:00', '2026-10-05T11:30', 'Asia/Jerusalem', 'משרד, קומה 3',
                          'dana@client.co.il', False))
        body = invites.event_resource(inv)
        self.assertEqual((body['iCalUID'], body['start']), ('abc-123@outlook', {'dateTime': '2026-10-05T10:00:00', 'timeZone': 'Asia/Jerusalem'}))

    def test_utc_all_day_and_cancel(self):
        from mailbrief.features import invites
        utc = invites.parse_ics('BEGIN:VEVENT\nDTSTART:20261005T070000Z\nSUMMARY:x\nEND:VEVENT')
        local = dt.datetime(2026, 10, 5, 7, tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
        self.assertEqual(utc['start'], local.isoformat(timespec='minutes'))
        day = invites.parse_ics('BEGIN:VEVENT\nDTSTART;VALUE=DATE:20261005\nSUMMARY:חופש\nEND:VEVENT')
        self.assertEqual((day['all_day'], day['end']), (True, '2026-10-06'))
        gone = invites.parse_ics('METHOD:CANCEL\nBEGIN:VEVENT\nDTSTART:20261005T070000Z\nEND:VEVENT')
        self.assertFalse(invites.upcoming(gone, now=dt.datetime(2026, 1, 1)))
        self.assertIsNone(invites.parse_ics('not a calendar'))

    def test_invite_found_in_mail(self):
        from mailbrief.features import invites
        msg = mk('Dana <dana@client.co.il>', 'Invitation', 'see attached', attach=('invite.ics', ICS.encode('utf-8')))
        self.assertEqual(invites.find_invite(msg)['uid'], 'abc-123@outlook')
        self.assertIsNone(invites.find_invite(mk('a <a@b.co>', 'hi', 'no invite')))


class Followups(Isolated):
    def test_only_unanswered_conversations_i_started(self):
        from mailbrief.features import followups
        old = 'Mon, 14 Sep 2026 10:00:00 +0300'

        def sent(to, subject, when=old, reply_to=None):
            m = mk('me@gmail.com', subject, 'x', when=when, headers={'In-Reply-To': reply_to} if reply_to else None)
            del m['To']
            m['To'] = to
            return (None, 1, m)
        mails = [sent('Dana <dana@client.co.il>', 'הצעת מחיר'),                       # waiting
                 sent('Avi <avi@x.co.il>', 'חוזה'),                                     # answered
                 sent('noreply@bank.co.il', 'בקשה'),                                   # robot address
                 sent('Dana <dana@client.co.il>', 'Re: שאלה', reply_to='<q@x>'),      # my answer to someone
                 sent('Rina <rina@x.co.il>', 'חדש', when=dt.datetime.now().astimezone().strftime('%a, %d %b %Y %H:%M:%S %z'))]  # too fresh
        fake = mock.Mock()
        with mock.patch.object(followups, 'special_folder', return_value='Sent'), \
                mock.patch.object(followups, 'fetch_recent', return_value=mails), \
                mock.patch.object(followups, 'replied', side_effect=lambda m, mid: mid == mails[1][2]['Message-ID'].strip()):
            waiting = followups.awaiting_replies(fake, {'email': 'me@gmail.com', 'host': 'imap.gmail.com'}, {'me@gmail.com'})
        self.assertEqual([(w['to'], w['subject']) for w in waiting], [('Dana', 'הצעת מחיר')])

    def test_weekly_run_keeps_hourly_findings(self):
        from mailbrief.features import alerts
        future = (dt.datetime.now() + dt.timedelta(days=2)).isoformat(timespec='minutes')
        storage.save_json(config.SNAPSHOT_FILE, {'awaiting': [{'to': 'Dana', 'days': 5}],
                                                 'invites': [{'title': 'x', 'start': future, 'end': future, 'all_day': False, 'cancelled': False}]})
        alerts.save_snapshot([('me@gmail.com', [])])
        snap = storage.load_json(config.SNAPSHOT_FILE, {})
        self.assertEqual((len(snap['awaiting']), len(snap['invites'])), (1, 1))
        alerts.save_snapshot([('me@gmail.com', [])], awaiting=[])
        self.assertEqual(storage.load_json(config.SNAPSHOT_FILE, {})['awaiting'], [])


class Pages(Isolated):
    def test_every_page_renders(self):                    # regression: a name clash crashed "My day"
        from mailbrief.web import automations as wa, clients, dashboard, help as wh, reading, search, settings, today
        future = (dt.datetime.now() + dt.timedelta(days=2)).isoformat(timespec='minutes')
        storage.save_json(config.ACCOUNTS_FILE, [{'id': 'a1', 'email': 'me@gmail.com', 'host': 'imap.gmail.com', 'auth': 'google', 'gapps': True}])
        storage.save_json(config.SNAPSHOT_FILE, {
            'at': 'now', 'waiting': [{'account': 'me@gmail.com', 'from': 'Dana', 'subject': 's', 'link': '', 'message_id': '<m>', 'days': 4}],
            'urgent': [], 'due': [], 'awaiting': [{'account': 'me@gmail.com', 'to': 'Avi', 'to_email': 'a@x.co', 'subject': 'q', 'days': 5, 'link': ''}],
            'invites': [{'account': 'me@gmail.com', 'from': 'Dana', 'subject': 'inv', 'link': '', 'title': 'פגישה', 'start': future,
                         'end': future, 'zone': 'Asia/Jerusalem', 'all_day': False, 'where': 'Zoom', 'uid': 'u', 'cancelled': False}]})
        with mock.patch.object(net, 'cached_json', return_value=None), \
                mock.patch.object(today, 'today_overview', return_value={'account': 'me@gmail.com', 'events': [], 'tasks': []}):
            pages = [today.today_page('hi'), settings.settings_page(), wa.automations_page(), clients.clients_page(),
                     dashboard.dashboard_page(), dashboard.stats_page(), wh.help_page(), reading.reading_page(), search.search_page('')]
        for html in pages:
            self.assertIn('mb-pal', html)                 # the shared header (palette, loader, theme) is on every page
        from mailbrief.web import insights as wi, welcome
        from mailbrief.features import insights as fi
        with mock.patch.object(net, 'cached_json', return_value=None):
            self.assertIn('איך קוראים לך', welcome.welcome_page())
            self.assertIn('first_look', wi.insights_page())                    # before the first scan: the start button
            storage.save_json(config.INSIGHTS_FILE, fi.summarize([], {}, {}))
            self.assertIn('ניוזלטרים לביטול', wi.insights_page())
        self.assertIn('📅 הוספה ליומן', pages[0])
        self.assertIn('📤 מחכה לתשובה מהם', pages[0])


class Personal(Isolated):
    def test_profile_wording_and_goals(self):
        from mailbrief import profile
        self.assertFalse(profile.has_profile())
        self.assertEqual(profile.goals(), list(profile.GOALS))                   # nothing chosen yet: show everything
        profile.save_profile('  רחל  ', 'f', ['money', 'nonsense'])
        self.assertEqual((profile.profile()['name'], profile.goals()), ('רחל', ['money']))
        self.assertEqual((profile.g('שימי לב', 'שים לב', 'לתשומת לב'), profile.welcome_back()), ('שימי לב', 'ברוכה השבה'))
        profile.save_profile('דוד', 'm')                                         # goals kept when not sent
        self.assertEqual((profile.welcome_back(), profile.goals()), ('ברוך השב', ['money']))
        profile.save_profile('', 'x')
        self.assertEqual(profile.g('א', 'ב', 'ג'), 'ג')

    def test_daily_email_once_a_day_after_the_hour(self):
        from mailbrief.features import daily
        storage.save_json(config.SETTINGS_FILE, {'daily': {'on': True, 'hour': 7, 'account': 'me@gmail.com'}})
        storage.save_json(config.SNAPSHOT_FILE, {'urgent': [{'subject': 'חשבון חסום', 'from': 'בנק', 'why': 'דחוף', 'link': ''}],
                                                 'waiting': [{'subject': 'הצעת מחיר', 'from': 'דנה', 'days': 4, 'link': ''}]})
        accounts = [{'email': 'me@gmail.com', 'host': 'imap.gmail.com'}]
        state = {}
        with mock.patch.object(smtp, 'send_mail') as send, mock.patch.object(daily.google_apps, 'today_overview', return_value=None):
            self.assertIsNone(daily.maybe_send_daily(state, accounts, now=dt.datetime(2026, 9, 24, 6, 30)))   # too early
            self.assertIn('היום שלך', daily.maybe_send_daily(state, accounts, now=dt.datetime(2026, 9, 24, 8, 0)))
            self.assertIsNone(daily.maybe_send_daily(state, accounts, now=dt.datetime(2026, 9, 24, 9, 0)))   # once a day
        msg = send.call_args[0][1]
        body = msg.get_body(('plain',)).get_content()
        self.assertEqual((send.call_count, msg['To'], msg['X-MailBrief-Forwarded']), (1, 'me@gmail.com', '1'))
        self.assertIn('חשבון חסום', body)
        self.assertIn('הצעת מחיר', body)

    def test_first_look_summary(self):
        from mailbrief.features import insights, unsubscribe
        news = sorting.classify(mk('Shop <news@shop.co.il>', 'מבצע', 'x', headers={'List-Unsubscribe': '<https://shop.co.il/u>'}), 'me@gmail.com')
        person = sorting.classify(mk('Dana <dana@client.co.il>', 'שאלה', 'x'), 'me@gmail.com')
        person['answered'], person['waiting_days'] = False, 3
        results = [{'email': 'me@gmail.com', 'items': [news, news, person], 'error': None}]
        unsubscribe.remember_unsubs(results)
        ledger = {'a': {'vendor_key': 'netflix.com', 'vendor': 'Netflix', 'date': '2026-08-02', 'amount': 50.0, 'currency': '₪', 'book': '', 'recurring': True},
                  'b': {'vendor_key': 'netflix.com', 'vendor': 'Netflix', 'date': '2026-09-02', 'amount': 50.0, 'currency': '₪', 'book': '', 'recurring': True}}
        data = insights.summarize(results, ledger, storage.load_json(config.UNSUBS_FILE, {}))
        self.assertEqual((data['emails'], data['newsletter_emails'], len(data['newsletters']), data['waiting_count']), (3, 2, 1, 1))
        self.assertEqual((len(data['subs']), data['subs_month_ils']), (1, 50.0))

    def test_update_versions(self):
        from mailbrief.features import update
        self.assertTrue(update.version_tuple('v1.10.0') > update.version_tuple('1.9.3'))
        self.assertEqual(update.version_tuple('2'), (2, 0, 0))
        release = {'tag_name': 'v9.0.0', 'html_url': 'https://github.com/x', 'body': '',
                   'assets': [{'name': 'MailBrief.exe', 'browser_download_url': 'https://github.com/x/MailBrief.exe', 'size': 10,
                               'digest': 'sha256:ab'}]}
        update._FAILED[0] = 0
        with mock.patch.object(net, 'cached_json', return_value=release):
            self.assertEqual(update.update_available()['sha256'], 'ab')
        with mock.patch.object(net, 'cached_json', return_value=release | {'tag_name': 'v0.1'}):
            self.assertIsNone(update.update_available())
        with mock.patch.object(net, 'cached_json', return_value=None) as offline:
            self.assertIsNone(update.latest_release())
            self.assertIsNone(update.latest_release())                         # no second network try right away
            self.assertEqual(offline.call_count, 1)
        update._FAILED[0] = 0


class Setup(Isolated):
    def test_runs_registered_only_when_missing_or_moved(self):
        from mailbrief.features import setup
        exe = r'C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\Ayal408.MailBrief\MailBrief.exe'
        with mock.patch.object(setup, 'program_path', return_value=exe), mock.patch.object(setup, 'install') as install:
            with mock.patch.object(setup, 'installed_paths', return_value=[exe] * 3):
                self.assertFalse(setup.ensure())
            with mock.patch.object(setup, 'installed_paths', return_value=[r'C:\old\MailBrief.exe'] * 3):
                self.assertTrue(setup.ensure())
            with mock.patch.object(setup, 'installed_paths', return_value=['-', '-', '-']):
                self.assertTrue(setup.ensure())
        self.assertEqual(install.call_count, 2)
        with mock.patch.object(setup, 'program_path', return_value=''), mock.patch.object(setup, 'install') as install:
            self.assertFalse(setup.ensure())                                    # from source: never touches Task Scheduler
        install.assert_not_called()


class Address(Isolated):
    def test_nice_address_with_and_without_port(self):
        from mailbrief import address
        from mailbrief.web import server
        self.assertEqual(address.base_url(), 'http://mailbrief.localhost:8765')      # before the server ever ran
        address.remember(80)
        self.assertEqual(address.link('today'), 'http://mailbrief.localhost/today')
        address.remember(8765)
        self.assertEqual(address.link(), 'http://mailbrief.localhost:8765/')
        hosts = server.allowed_hosts()
        self.assertTrue({'mailbrief.localhost', '127.0.0.1:8765', 'localhost:8765'} <= hosts)
        self.assertNotIn('evil.example', hosts)


def message_b64(claims):
    import base64
    import json
    return base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')


if __name__ == '__main__':
    unittest.main()
