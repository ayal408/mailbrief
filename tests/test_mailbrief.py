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
net._STATE.update(ok=True, until=float('inf'))     # no real connectivity check: the tests mock the network


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
        self.patches.append(mock.patch.object(config, 'HERE', self.tmp))      # code that joins HERE itself too
        for p in self.patches:
            p.start()
        real = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        assert not os.path.normcase(os.path.abspath(config.DATA)).startswith(real), 'tests must never touch the real data folder'
        os.makedirs(config.DATA, exist_ok=True)
        storage.save_json(config.ACCOUNTS_FILE, [{'id': 'test0001', 'email': 'me@gmail.com', 'host': 'imap.gmail.com'}])

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
        from mailbrief.web import compose, greetings as wg, triage as wt
        with mock.patch.object(net, 'cached_json', return_value=None):
            self.assertIn('tri-reply', wt.triage_page())
            self.assertIn('multipart/form-data', compose.compose_page())
            self.assertIn('gr-preview', wg.greetings_page())
            self.assertIn('ביטול מנויים', reading.reading_page())
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
        setup_asset = {'name': 'MailBrief-Setup.exe', 'browser_download_url': 'https://github.com/x/MailBrief-Setup.exe', 'size': 20}
        with mock.patch.object(net, 'cached_json', return_value=release | {'assets': release['assets'] + [setup_asset]}), \
                mock.patch.object(config, 'INSTALLED', True):
            rel = update.update_available()
            self.assertEqual((rel['url'], rel['setup']), ('https://github.com/x/MailBrief-Setup.exe', True))   # installed copy: new setup
        with mock.patch.object(net, 'cached_json', return_value=release | {'tag_name': 'v0.1'}):
            self.assertIsNone(update.update_available())
        with mock.patch.object(net, 'cached_json', return_value=None) as offline:
            self.assertIsNone(update.latest_release())
            self.assertIsNone(update.latest_release())                         # no second network try right away
            self.assertEqual(offline.call_count, 1)
        update._FAILED[0] = 0


class Accountant(Isolated):
    def book(self):
        def row(key, vendor, day, amount, cur='₪', book='תוכנה ומנויים', files=()):
            return {'vendor_key': key, 'vendor': vendor, 'date': day, 'amount': amount, 'currency': cur, 'amount_ils': amount if cur == '₪' else amount * 3.7,
                    'book': book, 'subject': 'Invoice', 'account': 'me@gmail.com', 'email': f'billing@{key}', 'files': list(files), 'recurring': True}
        today = dt.date.today()
        this, prev = today.replace(day=1), (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        return {'a': row('netflix.com', 'Netflix', prev.isoformat(), 55.0), 'b': row('netflix.com', 'Netflix', this.isoformat(), 65.0),
                'c': row('paz.co.il', 'פז', prev.replace(day=3).isoformat(), 300.0, book='רכב', files=[f'{prev:%Y-%m}/paz.pdf'])}

    def test_month_package_zip(self):
        from mailbrief.money import accountant
        book = self.book()
        month = book['c']['date'][:7]
        os.makedirs(os.path.join(config.RECEIPTS_DIR, month), exist_ok=True)
        with open(os.path.join(config.RECEIPTS_DIR, month, 'paz.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 test')
        path, rows, total = accountant.month_package(month, book)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        self.assertEqual((len(rows), total), (2, 355.0))
        self.assertIn(f'קבלות {month}.xlsx', names)
        self.assertIn('קבצים/paz.pdf', names)

    def test_monthly_send_once(self):
        from mailbrief.money import accountant
        storage.save_json(config.LEDGER_FILE, self.book())
        storage.save_json(config.SETTINGS_FILE, {'accountant': {'on': True, 'email': 'cpa@x.co.il', 'day': 2, 'account': 'me@gmail.com'}})
        state, accounts = {}, [{'email': 'me@gmail.com', 'host': 'imap.gmail.com'}]
        today = dt.date.today()
        with mock.patch.object(smtp, 'send_mail') as send:
            self.assertIsNone(accountant.maybe_send_monthly(state, accounts, today.replace(day=1)))      # before the day
            self.assertIsNotNone(accountant.maybe_send_monthly(state, accounts, today.replace(day=2)))
            self.assertIsNone(accountant.maybe_send_monthly(state, accounts, today.replace(day=5)))      # once a month
        msg = send.call_args[0][1]
        self.assertEqual((send.call_count, msg['To']), (1, 'cpa@x.co.il'))
        self.assertTrue(any(p.get_filename().endswith('.zip') for p in msg.iter_attachments()))

    def test_price_increase_and_yearly(self):
        from mailbrief.money import accountant
        book = self.book()
        changes = accountant.price_changes(book)
        self.assertEqual([(c['vendor'], c['old'], c['new'], c['percent']) for c in changes], [('Netflix', 55.0, 65.0, 18)])
        path, count = accountant.yearly_report(dt.date.today().year, book)
        with zipfile.ZipFile(path) as z:
            sheet = z.read('xl/worksheets/sheet1.xml').decode('utf-8')
        self.assertIn('סה״כ לשנה', sheet)
        self.assertIn('Netflix', sheet)


class Outbox(Isolated):
    SAT = (dt.datetime(2026, 9, 25, 17, 42, tzinfo=IL), dt.datetime(2026, 9, 26, 19, 7, tzinfo=IL))

    def test_times_never_on_shabbat(self):
        from mailbrief.features import outbox
        friday = dt.datetime(2026, 9, 25, 12, 0, tzinfo=IL)
        after = outbox.when_for('after_holy', now=friday, windows=[self.SAT])
        self.assertEqual(after, dt.datetime(2026, 9, 26, 19, 27, tzinfo=IL))
        inside = outbox.when_for('custom', '2026-09-26T10:00', now=friday, windows=[self.SAT])
        self.assertEqual(inside, after)                                   # a time on Shabbat moves to after havdalah
        self.assertEqual(outbox.when_for('sunday8', now=friday, windows=[self.SAT]).isoformat()[:16], '2026-09-27T08:00')
        with self.assertRaises(ValueError):
            outbox.when_for('custom', '2020-01-01T10:00', now=friday, windows=[])

    def test_send_due_once_and_not_on_shabbat(self):
        from mailbrief.features import outbox
        acc = {'email': 'me@gmail.com', 'host': 'imap.gmail.com'}
        outbox.schedule('me@gmail.com', 'a@x.co.il, b@y.co.il', 'שלום', 'גוף', dt.datetime(2026, 9, 25, 10, 0, tzinfo=IL))
        with self.assertRaises(ValueError):
            outbox.schedule('me@gmail.com', 'not-an-address', 's', 'b', dt.datetime(2026, 9, 25, 10, 0, tzinfo=IL))
        with mock.patch.object(smtp, 'send_mail') as send:
            with mock.patch.object(outbox, 'is_holy_time', return_value=True):
                self.assertEqual(outbox.send_due([acc], now=dt.datetime(2026, 9, 26, 12, 0, tzinfo=IL)), 0)
            with mock.patch.object(outbox, 'is_holy_time', return_value=False):
                self.assertEqual(outbox.send_due([acc], now=dt.datetime(2026, 9, 27, 9, 0, tzinfo=IL)), 1)
                self.assertEqual(outbox.send_due([acc], now=dt.datetime(2026, 9, 27, 10, 0, tzinfo=IL)), 0)
        self.assertEqual(send.call_args[0][1]['To'], 'a@x.co.il, b@y.co.il')
        self.assertEqual(outbox.outbox()[0]['status'], 'sent')


class Comfort(Isolated):
    def test_quiet_hours_cross_midnight(self):
        storage.save_json(config.SETTINGS_FILE, {'quiet': {'on': True, 'from': 22, 'to': 7}})
        self.assertTrue(notify.quiet_now(dt.datetime(2026, 9, 24, 23, 0)))
        self.assertTrue(notify.quiet_now(dt.datetime(2026, 9, 24, 6, 0)))
        self.assertFalse(notify.quiet_now(dt.datetime(2026, 9, 24, 12, 0)))
        with mock.patch.object(notify.subprocess, 'run') as run, mock.patch.object(notify, 'is_holy_time', return_value=False), \
                mock.patch.object(notify, 'quiet_now', return_value=True):
            notify.toast('x', ['y'])
        run.assert_not_called()

    def test_triage_done_hides_from_queue(self):
        from mailbrief.features import triage
        storage.save_json(config.SNAPSHOT_FILE, {'waiting': [{'account': 'me@gmail.com', 'message_id': '<a>', 'subject': 'א', 'from': 'דנה', 'days': 3}],
                                                 'awaiting': [{'account': 'me@gmail.com', 'message_id': '<b>', 'subject': 'ב', 'to': 'אבי', 'days': 5}]})
        self.assertEqual([q['kind'] for q in triage.queue()], ['mine', 'theirs'])
        triage.dismiss('me@gmail.com|<a>')
        self.assertEqual([q['from'] for q in triage.queue()], ['אבי'])
        triage.undo('me@gmail.com|<a>')
        self.assertEqual(len(triage.queue()), 2)

    def test_import_previous_copy(self):
        from mailbrief.features import migrate
        old = tempfile.mkdtemp()
        os.makedirs(os.path.join(old, 'data', 'window'))
        storage.save_json(os.path.join(old, 'data', 'accounts.json'), [{'email': 'old@gmail.com'}])
        storage.save_json(os.path.join(old, 'data', 'url.txt.json'), {})
        with open(os.path.join(old, 'data', 'window', 'cache.bin'), 'w') as f:
            f.write('x')
        os.makedirs(os.path.join(old, 'קבלות', '2026-09'))
        with open(os.path.join(old, 'קבלות', '2026-09', 'r.pdf'), 'wb') as f:
            f.write(b'%PDF')
        migrate.remember_previous(os.path.join(old, 'MailBrief.exe'))
        self.assertEqual(migrate.previous_copy(), old)
        with mock.patch('mailbrief.features.maintenance.make_backup'):
            migrate.import_from(old + '\\MailBrief.exe')
        self.assertEqual(storage.load_json(config.ACCOUNTS_FILE, [])[0]['email'], 'old@gmail.com')
        self.assertTrue(os.path.isfile(os.path.join(config.RECEIPTS_DIR, '2026-09', 'r.pdf')))
        self.assertFalse(os.path.exists(os.path.join(config.DATA, 'window')))         # the program's own cache stays behind
        self.assertEqual(migrate.previous_copy(), '')
        with self.assertRaises(ValueError):
            migrate.import_from(tempfile.mkdtemp())


def make_pdf(content, cmap=None):
    """A minimal PDF: one compressed content stream (+ an optional ToUnicode table)."""
    import zlib
    objs = []
    if cmap:
        objs.append(b'<< /Length %d >>\nstream\n' % len(cmap) + cmap + b'\nendstream')
    packed = zlib.compress(content)
    objs.append(b'<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(packed) + packed + b'\nendstream')
    return b'%PDF-1.4\n' + b''.join(b'%d 0 obj\n' % (n + 1) + o + b'\nendobj\n' for n, o in enumerate(objs)) + b'%%EOF'


class PdfTotals(Isolated):
    def test_plain_text_pdf(self):
        from mailbrief.money import pdftext
        pdf = make_pdf(b'BT /F1 12 Tf 72 700 Td (Subtotal ILS 1,000.00) Tj 0 -20 Td (VAT ILS 180.00) Tj 0 -20 Td (Total ILS 1,180.00) Tj ET')
        self.assertEqual(pdftext.total_from_pdf(pdf), '₪1,180.00')

    def test_glyph_by_glyph_with_tounicode(self):             # Chrome-style: every character placed on its own
        from mailbrief.money import pdftext
        cmap = (b'/CIDInit /ProcSet findresource begin begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange\n'
                b'3 beginbfchar <0001> <20AA> <0002> <05E1> <0003> <05D4> endbfchar\n'
                b'1 beginbfrange <0010> <0019> <0030> endbfrange\n'
                b'2 beginbfchar <0020> <002E> <0021> <002C> endbfchar endcmap')
        glyphs = {'₪': '0001', '5': '0015', '9': '0019', '.': '0020', '0': '0010', ',': '0021', '2': '0012'}
        line = ' '.join(f'<{glyphs[c]}> Tj 4.5 0 Td' for c in '₪59.00').encode()
        date = ' '.join(f'<{glyphs[c]}> Tj 4.5 0 Td' for c in '2,020').encode()
        pdf = make_pdf(b'BT 1 0 0 -1 540 100 Tm ' + line + b' ET BT 1 0 0 -1 540 130 Tm ' + date + b' ET', cmap)
        self.assertIn('₪59.00', pdftext.pdf_text(pdf))
        self.assertEqual(pdftext.total_from_pdf(pdf), '₪59.00')

    def test_hebrew_visual_order_and_dates(self):
        from mailbrief.money import pdftext
        pdf = make_pdf('BT 72 700 Td (22-09-2026₪ 20.16) Tj 0 -20 Td (ח"ש 1,960.00:םוכס) Tj ET'.encode('utf-8'))
        with mock.patch.object(pdftext, '_decode', side_effect=lambda code, table, widths: code.decode('utf-8', 'replace')):
            self.assertEqual(pdftext.total_from_pdf(pdf), '₪1,960.00')
        self.assertEqual(pdftext.total_from_pdf(b'not a pdf'), '')

    def test_ledger_backfills_from_saved_pdf(self):
        from mailbrief.money import ledger as book
        os.makedirs(os.path.join(config.RECEIPTS_DIR, '2026-09'))
        with open(os.path.join(config.RECEIPTS_DIR, '2026-09', 'a.pdf'), 'wb') as f:
            f.write(make_pdf(b'BT 72 700 Td (Total ILS 99.90) Tj ET'))
        storage.save_json(config.LEDGER_FILE, {'k': {'date': '2026-09-10', 'vendor': 'X', 'email': 'b@x.co.il', 'vendor_key': 'x.co.il',
                                                     'subject': 'חשבונית', 'amount': None, 'currency': '', 'book': 'אחר',
                                                     'account': 'me@gmail.com', 'files': ['2026-09/a.pdf']}})
        rows = book.update_ledger([])
        self.assertEqual((rows['k']['amount'], rows['k']['currency'], rows['k']['amount_from']), (99.9, '₪', 'pdf'))


class Greetings(Isolated):
    def test_recipients_and_personal_mail(self):
        from mailbrief.features import greetings, outbox
        today = dt.date.today().isoformat()
        history = {f'm{i}': {'date': today, 'cats': ['people'], 'sender': 'dana@client.co.il', 'name': 'דנה כהן', 'answered': True,
                             'rules': ['לקוח כהן']} for i in range(2)}
        history['robot'] = {'date': today, 'cats': ['people'], 'sender': 'noreply@shop.co.il', 'name': 'Shop'}
        history['news'] = {'date': today, 'cats': ['newsletters'], 'sender': 'news@x.co.il', 'name': 'News'}
        storage.save_json(config.HISTORY_FILE, history)
        people = greetings.recipients()
        self.assertEqual([(p['email'], p['first_name'], p['suggested']) for p in people], [('dana@client.co.il', 'דנה', True)])
        when = dt.datetime(2026, 9, 11, 10, 0, tzinfo=IL)
        self.assertEqual(greetings.schedule_greetings('me@gmail.com', people, 'שנה טובה', 'שלום {first_name},\nשנה טובה!\n{my_name}', when, 'רחל'), 1)
        item = outbox.outbox()[0]
        self.assertEqual((item['to'], item['body']), (['dana@client.co.il'], 'שלום דנה,\nשנה טובה!\nרחל\n'))
        self.assertEqual(greetings.personal('שלום {first_name},', {'first_name': ''}, ''), 'שלום,\n')
        with self.assertRaises(ValueError):
            greetings.schedule_greetings('me@gmail.com', [], 's', 't', when)


class SnoozeAndReplies(Isolated):
    def fake_imap(self):
        m = mock.Mock()
        m.uid.side_effect = lambda cmd, *a: ('OK', [b'42']) if cmd == 'SEARCH' else ('OK', [None])
        m.list.return_value = ('OK', [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"'])
        return m

    def test_snooze_and_wake(self):
        from mailbrief.features import snooze
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'me@gmail.com', 'host': 'imap.gmail.com'}])
        m = self.fake_imap()
        with mock.patch.object(imap, 'connect', return_value=m):
            snooze.snooze('me@gmail.com', '<a@x>', 'הצעת מחיר', dt.datetime(2026, 9, 30, 8, 0, tzinfo=IL))
            self.assertIn(mock.call('STORE', b'42', '-X-GM-LABELS', r'(\Inbox)'), m.uid.call_args_list)
            with mock.patch.object(snooze, 'is_holy_time', return_value=False), mock.patch.object(notify, 'toast') as toast:
                self.assertEqual(snooze.wake_due(dt.datetime(2026, 9, 29, 8, 0, tzinfo=IL)), 0)       # not yet
                self.assertEqual(snooze.wake_due(dt.datetime(2026, 9, 30, 9, 0, tzinfo=IL)), 1)
        self.assertIn(mock.call('STORE', b'42', '+X-GM-LABELS', r'(\Inbox)'), m.uid.call_args_list)
        self.assertIn(mock.call('STORE', b'42', '-FLAGS', r'(\Seen)'), m.uid.call_args_list)
        self.assertEqual((snooze.snoozed(), toast.call_count), ([], 1))

    def test_scheduled_reply_keeps_thread_and_files(self):
        from mailbrief.features import outbox
        item = outbox.schedule('me@gmail.com', 'dana@client.co.il', 'Re: הצעה', 'תודה!', dt.datetime(2026, 9, 27, 8, 0, tzinfo=IL),
                               files=[('הצעה.pdf', b'%PDF-1.4 x')], thread={'in_reply_to': '<a@x>', 'references': '<a@x>'})
        msg = outbox.build(item, {'email': 'me@gmail.com'})
        self.assertEqual((msg['In-Reply-To'], [p.get_filename() for p in msg.iter_attachments()]), ('<a@x>', ['הצעה.pdf']))

    def test_multipart_form(self):
        from mailbrief.web.server import parse_multipart
        body = ('--XX\r\nContent-Disposition: form-data; name="to"\r\n\r\nדנה@x.co.il\r\n'
                '--XX\r\nContent-Disposition: form-data; name="files"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF\r\n'
                '--XX--\r\n').encode('utf-8')
        fields, files = parse_multipart('multipart/form-data; boundary=XX', body)
        self.assertEqual((fields['to'], files), (['דנה@x.co.il'], [('a.pdf', b'%PDF')]))


class Mailboxes(Isolated):
    def test_run_one_mailbox_keeps_the_others(self):
        from mailbrief.features import alerts
        storage.save_json(config.SNAPSHOT_FILE, {
            'waiting': [{'account': 'a@gmail.com', 'subject': 'ישן-א', 'days': 9}, {'account': 'b@gmail.com', 'subject': 'ב', 'days': 2}],
            'awaiting': [{'account': 'b@gmail.com', 'subject': 'ממתין-ב', 'days': 5}], 'urgent': [], 'due': [], 'invites': []})
        fresh = sorting.classify(mk('Dana <dana@client.co.il>', 'חדש-א', 'x'), 'a@gmail.com')
        fresh['answered'], fresh['waiting_days'] = False, 1
        alerts.save_snapshot([('a@gmail.com', [fresh])], only='a@gmail.com')
        snap = storage.load_json(config.SNAPSHOT_FILE, {})
        self.assertEqual(sorted(w['subject'] for w in snap['waiting']), ['ב', 'חדש-א'])        # a's old row replaced, b's kept
        self.assertEqual([w['subject'] for w in snap['awaiting']], ['ממתין-ב'])                 # not counted twice

    def test_view_one_mailbox(self):
        from mailbrief import view
        from mailbrief.features import triage
        self.assertEqual(view.switcher(), '')                                    # one mailbox: no switcher
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'a@gmail.com'}, {'email': 'b@gmail.com'}])
        storage.save_json(config.SNAPSHOT_FILE, {'waiting': [{'account': 'a@gmail.com', 'subject': 'א', 'from': 'x', 'days': 1},
                                                             {'account': 'b@gmail.com', 'subject': 'ב', 'from': 'y', 'days': 2}]})
        self.assertIn('כל התיבות', view.switcher())
        self.assertEqual(len(triage.queue()), 2)
        self.assertEqual(view.set_account('b@gmail.com'), 'b@gmail.com')
        self.assertEqual([q['subject'] for q in triage.queue()], ['ב'])
        self.assertNotEqual(view.color('a@gmail.com'), view.color('b@gmail.com'))
        self.assertEqual(view.set_account('stranger@x.com'), '')                 # unknown: back to all
        self.assertEqual(len(triage.queue()), 2)


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


class Diagnostics(Isolated):
    def test_redact_hides_addresses_and_tokens(self):
        from mailbrief.features.diag import redact
        out = redact('failed for dana.levi@gmail.com token ya29.' + 'A' * 60)
        self.assertIn('d***@gmail.com', out)
        self.assertNotIn('dana.levi', out)
        self.assertNotIn('A' * 40, out)

    def test_problem_report_is_masked(self):
        import logging
        from mailbrief.features import diag
        os.makedirs(diag.log_dir(), exist_ok=True)
        with open(diag.log_file(), 'w', encoding='utf-8') as f:
            f.write('ERROR POST /check\nRuntimeError: login failed for someone.private@walla.co.il\n')
        with mock.patch('mailbrief.features.maintenance.health_checks', return_value=[('תיבה me@gmail.com', True, 'מחובר')]):
            path = diag.problem_report(self.tmp)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            text = ''.join(z.read(n).decode('utf-8') for n in names)
        self.assertIn('about.txt', names)
        self.assertIn('logs/mailbrief.log', names)
        self.assertNotIn('someone.private', text)
        self.assertNotIn('me@gmail.com', text)
        self.assertIn('s***@walla.co.il', text)
        logging.shutdown()

    def test_built_in_google_key(self):
        from mailbrief.mail import oauth
        from mailbrief.mail import builtin_key
        built_in = oauth.client_for('google')                                                  # the key inside the code
        self.assertEqual(built_in, builtin_key.google())
        self.assertTrue(built_in[0].endswith('.apps.googleusercontent.com') and built_in[1])
        storage.save_json(config.BUNDLED_GOOGLE, {'installed': {'client_id': 'built-in.apps.googleusercontent.com', 'client_secret': 's1'}})
        self.assertEqual(oauth.client_for('google'), ('built-in.apps.googleusercontent.com', 's1'))
        self.assertEqual(oauth.client_for('microsoft'), ('', ''))
        storage.save_json(config.SETTINGS_FILE, {'google': {'client_id': 'own.apps.googleusercontent.com', 'client_secret': storage.encrypt('s2')}})
        self.assertEqual(oauth.client_for('google'), ('own.apps.googleusercontent.com', 's2'))     # the user's own key wins
        from mailbrief.web import settings
        storage.save_json(config.SETTINGS_FILE, {})
        storage.save_json(config.ACCOUNTS_FILE, [])
        with mock.patch.object(net, 'cached_json', return_value=None):
            html = settings.settings_page()
            keys = settings.settings_page(sec='connect')
        self.assertIn('value="google" >🔵', html)                                            # the button is enabled
        self.assertIn('מפתח Google משלך (לא חובה)', keys)

    def test_external_pages_open_in_the_open_browser(self):
        from mailbrief import window
        with mock.patch.object(window, '_running', return_value={'msedge.exe', 'chrome.exe'}),                 mock.patch.object(window, '_exe_path', side_effect=lambda n: 'C:/b/' + n),                 mock.patch.object(window.subprocess, 'Popen') as popen:
            window.open_browser_tab('https://accounts.google.com/x')
        self.assertEqual(popen.call_args[0][0], ['C:/b/chrome.exe', 'https://accounts.google.com/x'])   # not Edge
        with mock.patch.object(window, '_running', return_value=set()), mock.patch.object(window.webbrowser, 'open') as default:
            window.open_browser_tab('https://example.com')
        default.assert_called_once_with('https://example.com')

    def test_help_has_report_privacy_about(self):
        from mailbrief.web import help as wh
        html = wh.help_page()
        for part in ('/problem_report', 'id="privacy"', '/notices'):
            self.assertIn(part, html)

    def test_notices_ship_with_the_program(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'THIRD-PARTY-NOTICES.txt'), encoding='utf-8') as f:
            text = f.read()
        for name in ('pywebview', 'pythonnet', 'clr_loader', 'bottle', 'cffi', 'pycparser', 'typing_extensions', 'PyInstaller'):
            self.assertIn(name, text)


class Books(Isolated):
    def ledger(self):
        rows = {}
        for n, (month, day) in enumerate((('2026-06', 4), ('2026-07', 5), ('2026-08', 6))):
            rows[f'e{n}'] = {'date': f'{month}-{day:02d}', 'vendor': 'חברת החשמל', 'email': 'bill@iec.co.il', 'vendor_key': 'iec.co.il',
                             'subject': 'חשבון חשמל', 'amount': 118.0, 'currency': '₪', 'book': 'אחר', 'account': 'me@gmail.com', 'files': []}
        rows['x'] = {'date': '2026-08-10', 'vendor': 'Figma', 'email': 'b@figma.com', 'vendor_key': 'figma.com', 'subject': 'Receipt',
                     'amount': 15.0, 'currency': '$', 'amount_ils': 55.0, 'book': 'תוכנה ומנויים', 'account': 'me@gmail.com', 'files': []}
        storage.save_json(config.LEDGER_FILE, rows)
        return rows

    def test_vat_and_vendor_category(self):
        from mailbrief.money import books
        self.ledger()
        s = books.vat_summary('2026-08')
        self.assertEqual((s['total'], s['vat'], s['foreign']), (173.0, 18.0, 55.0))       # 118 incl. 18% VAT; foreign has none
        books.set_vendor('iec.co.il', book='חשמל ומים')
        self.assertEqual(storage.load_json(config.LEDGER_FILE, {})['e2']['book'], 'חשמל ומים')    # old rows follow
        self.assertTrue(os.path.isfile(os.path.join(config.RECEIPTS_DIR, '2026-08', 'קבלות 2026-08.xlsx')))
        books.set_vendor('iec.co.il', no_vat=True)
        self.assertEqual(books.vat_summary('2026-08')['vat'], 0.0)

    def test_missing_invoice(self):
        from mailbrief.money import books
        self.ledger()
        self.assertEqual([m['key'] for m in books.missing_invoices(today=dt.date(2026, 9, 12))], ['iec.co.il'])
        self.assertEqual(books.missing_invoices(today=dt.date(2026, 9, 6)), [])             # not late yet (usually by the 5th + 3)

    def test_export_for_hashavshevet(self):
        from mailbrief.money import books
        self.ledger()
        storage.save_json(config.SETTINGS_FILE, {'export': {'vat_account': '18000', 'supplier_account': '40000', 'accounts': {'אחר': '70000'}}})
        path, count = books.export_month('2026-08')
        with open(path, encoding='cp1255') as f:
            lines = f.read().splitlines()
        self.assertEqual(count, 2)
        self.assertIn('חשבון הוצאה', lines[0])
        self.assertIn('06/08/2026,202608001,חשבון חשמל,חברת החשמל,אחר,70000,40000,18000,118.00,18.00,100.00,₪,118.00', lines)
        self.assertIn('10/08/2026,202608002,Receipt,Figma,תוכנה ומנויים,,40000,,55.00,0.00,55.00,$,15.00', lines)   # abroad: no VAT


class ClientCare(Isolated):
    def test_payment_reminders(self):
        from mailbrief.features import clientcare, outbox
        d = clientcare.add_debt('me@gmail.com', 'dana@client.co.il', 'דנה כהן', '₪1,200', '1043', '2026-08-01', 30, 7)
        with mock.patch.object(clientcare, 'out_of_holy', side_effect=lambda w: w), mock.patch.object(clientcare, 'profile', return_value={'name': 'רחל'}):
            self.assertEqual(clientcare.chase_due(dt.date(2026, 8, 20)), 0)            # not due yet
            self.assertEqual(clientcare.chase_due(dt.date(2026, 9, 1)), 1)
            self.assertEqual(clientcare.chase_due(dt.date(2026, 9, 2)), 0)             # next one only a week later
            self.assertEqual(clientcare.chase_due(dt.date(2026, 9, 8)), 1)
        mail = outbox.outbox()[0]
        self.assertEqual(mail['to'], ['dana@client.co.il'])
        self.assertIn('חשבונית 1043 על סך ₪1,200', mail['body'])
        self.assertIn('שלום דנה', mail['body'])
        clientcare.set_debt(d['id'], 'paid')
        self.assertEqual(clientcare.chase_due(dt.date(2026, 10, 1)), 0)

    def test_birthday_greeting_once(self):
        from mailbrief.features import clientcare, outbox
        clientcare.add_date('me@gmail.com', 'yossi@x.co.il', 'יוסי לוי', '1990-10-05', 'birthday')
        with mock.patch.object(clientcare, 'out_of_holy', side_effect=lambda w: w):
            self.assertEqual(clientcare.greet_due(dt.date(2026, 10, 1)), 0)
            self.assertEqual(clientcare.greet_due(dt.date(2026, 10, 4)), 1)            # the day before: queued for 09:00 on the day
            self.assertEqual(clientcare.greet_due(dt.date(2026, 10, 5)), 0)            # never twice a year
        mail = outbox.outbox()[0]
        self.assertTrue(mail['send_at'].startswith('2026-10-05T09:00'))
        self.assertIn('מזל טוב יוסי', mail['body'])


class Comforts(Isolated):
    def test_template_fields_in_hebrew(self):
        from mailbrief.features.automations import fill, wf_context
        it = sorting.classify(mk('דנה כהן <dana@client.co.il>', 'חשבונית מס 20391', 'סה"כ ₪590.00'), 'me@gmail.com')
        with mock.patch('mailbrief.profile.profile', return_value={'name': 'רחל'}):
            ctx = wf_context({'email': 'me@gmail.com'}, it)
        self.assertEqual(fill('שלום {שם_פרטי}, קיבלנו את חשבונית {מספר_חשבונית} על {סכום}. {השם_שלי}', ctx),
                         'שלום דנה, קיבלנו את חשבונית 20391 על ₪590.00. רחל')

    def test_vip_breaks_quiet_hours_only(self):
        with mock.patch.object(notify, 'is_holy_time', return_value=False), mock.patch.object(notify, 'paused_until', return_value=None), \
                mock.patch.object(notify, 'quiet_now', return_value=True), mock.patch.object(notify.subprocess, 'run') as run:
            notify.toast('x', ['y'])
            self.assertFalse(run.called)
            notify.toast('x', ['y'], vip=True)
            self.assertTrue(run.called)
        with mock.patch.object(notify, 'is_holy_time', return_value=True), mock.patch.object(notify.subprocess, 'run') as run:
            notify.toast('x', ['y'], vip=True)
            self.assertFalse(run.called)                                               # never on Shabbat, VIP or not
        storage.save_json(config.SETTINGS_FILE, {'quiet': {'vip': ['Boss@Corp.co.il', '@client.co.il']}})
        self.assertEqual(notify.vip_list(), {'boss@corp.co.il', 'client.co.il'})

    def test_encrypted_cloud_backup(self):
        from mailbrief.features import cloud_backup
        blob = cloud_backup.seal(b'secret settings' * 1000, 'long password 1')
        self.assertNotIn(b'secret settings', blob)
        self.assertEqual(cloud_backup.unseal(blob, 'long password 1'), b'secret settings' * 1000)
        with self.assertRaises(ValueError):
            cloud_backup.unseal(blob, 'wrong password!')
        with self.assertRaises(ValueError):
            cloud_backup.unseal(blob[:-1] + bytes([blob[-1] ^ 1]), 'long password 1')    # tampered
        self.assertFalse(cloud_backup.maybe_weekly({}))                                 # off by default

    def test_clean_inbox_keeps_starred_and_waiting(self):
        from mailbrief.features import cleanup

        class FakeImap:
            capabilities = ('IMAP4REV1',)

            def __init__(self):
                self.stored = []

            def select(self, *a, **k):
                return 'OK', [b'3']

            def uid(self, cmd, *args):
                if cmd == 'SEARCH':
                    self.search = args
                    return 'OK', [b'11 12 13']
                if cmd == 'FETCH':
                    return 'OK', [(b'1 (UID 12 BODY[HEADER.FIELDS (MESSAGE-ID)] {20}', b'Message-ID: <wait@x>\r\n\r\n'), b')']
                if cmd == 'STORE':
                    self.stored.append(args)
                    return 'OK', []
                return 'NO', []

            def logout(self):
                pass
        fake = FakeImap()
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'me@gmail.com', 'host': 'imap.gmail.com'}])
        storage.save_json(config.SNAPSHOT_FILE, {'waiting': [{'message_id': '<wait@x>'}]})
        with mock.patch.object(cleanup.imap, 'connect', return_value=fake):
            moved, errors = cleanup.clean_inbox(30)
        self.assertEqual((moved, errors), (2, []))
        self.assertIn('UNFLAGGED', fake.search)                                        # starred mail is never picked
        self.assertEqual([s[1:] for s in fake.stored][1], ('-X-GM-LABELS', r'(\Inbox)'))
        self.assertEqual({s[0] for s in fake.stored}, {b'11,13'})                                  # the waiting one stays
        self.assertTrue(fake.stored[0][2].startswith('("MailBrief cleanup '))                     # marked, so it can be undone

    def test_weekly_summary(self):
        from mailbrief.features.digest import summary_lines, weekly_summary
        today = dt.date(2026, 9, 20)
        storage.save_json(config.HISTORY_FILE, {
            'a': {'date': '2026-09-15', 'cats': ['people'], 'answered': True, 'sender': 'a@x.co', 'name': 'Avi', 'account': 'me@gmail.com'},
            'b': {'date': '2026-09-16', 'cats': ['people'], 'answered': False, 'sender': 'b@x.co', 'name': 'Bat', 'account': 'me@gmail.com'},
            'c': {'date': '2026-09-08', 'cats': ['newsletters'], 'sender': 'n@x.co', 'name': 'News', 'account': 'me@gmail.com'}})
        s = weekly_summary(today)
        self.assertEqual((s['this']['total'], s['last']['total'], s['rate'], s['change']), (2, 1, 50, 1))
        self.assertIn('💬 ענית ל-50% מהמיילים האישיים (1 מתוך 2)', summary_lines(s))

    def test_settings_sections_and_accessibility(self):
        from mailbrief.web import settings
        storage.save_json(config.ACCOUNTS_FILE, [{'id': 'a1', 'email': 'me@gmail.com', 'host': 'imap.gmail.com', 'auth': 'google'}])
        with mock.patch.object(net, 'cached_json', return_value=None):
            for key, _, title in settings.SECTIONS:
                html = settings.settings_page(sec=key)
                self.assertIn(f'href="/?s={key}" aria-current=page', html)
                self.assertIn('mb-a11y-btn', html)                                     # the accessibility button on every page
            self.assertIn('id="debts"', settings.settings_page(sec='clients'))
            self.assertIn('id="unopened"', settings.settings_page(sec='tidy'))
            self.assertIn('id="cloud"', settings.settings_page(sec='data'))
            self.assertIn('id="vat"', settings.settings_page(sec='money', month='2026-08'))
        self.assertTrue(set(settings.ANCHORS.values()) <= {k for k, _, _ in settings.SECTIONS})


class MoreFeatures(Isolated):
    def test_promises_in_sent_mail(self):
        from mailbrief.features.promises import find_promises
        thursday = dt.date(2026, 9, 24)
        self.assertEqual(find_promises('שלום, קיבלתי. אחזור אליך עד יום ראשון עם הצעה.', thursday)[0][1], dt.date(2026, 9, 27))
        self.assertEqual(find_promises('אשלח את החשבונית מחר בבוקר', thursday)[0][1], dt.date(2026, 9, 25))
        self.assertEqual(find_promises('I will send the file by Monday.', thursday)[0][1], dt.date(2026, 9, 28))
        self.assertEqual(find_promises('אעדכן עד 3/10', thursday)[0][1], dt.date(2026, 10, 3))
        self.assertEqual(find_promises('אבדוק ואעדכן', thursday)[0][1], dt.date(2026, 9, 26))       # no date: two days
        self.assertEqual(find_promises('תודה רבה, נדבר', thursday), [])
        self.assertEqual(find_promises('בסדר\n\nOn Tue, Dana wrote:\nאשלח מחר', thursday), [])        # someone else's promise, quoted

    def test_budget_compare_and_tax(self):
        from mailbrief.money import budget
        rows = {
            'a': {'date': '2026-09-02', 'vendor': 'פרטנר', 'email': 'b@partner.co.il', 'vendor_key': 'partner.co.il', 'subject': 'חשבונית',
                  'amount': 120.0, 'currency': '₪', 'book': 'תקשורת', 'account': 'me@gmail.com', 'files': []},
            'b': {'date': '2026-09-03', 'vendor': 'סלקום', 'email': 'b@cellcom.co.il', 'vendor_key': 'cellcom.co.il', 'subject': 'חשבונית',
                  'amount': 90.0, 'currency': '₪', 'book': 'תקשורת', 'account': 'me@gmail.com', 'files': []},
            'c': {'date': '2026-03-01', 'vendor': 'מכבי שירותי בריאות', 'email': 'x@maccabi4u.co.il', 'vendor_key': 'maccabi4u.co.il',
                  'subject': 'קבלה על תשלום', 'amount': 50.0, 'currency': '₪', 'book': 'אחר', 'account': 'me@gmail.com', 'files': ['2026-03/k.pdf']},
            'd': {'date': '2026-04-01', 'vendor': 'עמותת לתת', 'email': 'x@latet.org.il', 'vendor_key': 'latet.org.il',
                  'subject': 'קבלה לפי סעיף 46 על תרומתך', 'amount': 180.0, 'currency': '₪', 'book': 'אחר', 'account': 'me@gmail.com', 'files': []}}
        storage.save_json(config.LEDGER_FILE, rows)
        storage.save_json(config.SETTINGS_FILE, {'budgets': {'תקשורת': 150}})
        with mock.patch('mailbrief.money.budget.dt') as fake_dt:
            fake_dt.date.today.return_value = dt.date(2026, 9, 20)
            fake_dt.timedelta = dt.timedelta
            status = budget.budget_status('2026-09')
            compare = budget.compare_suppliers()
        self.assertEqual(status, [{'book': 'תקשורת', 'budget': 150.0, 'spent': 210.0, 'pct': 140, 'over': True}])
        self.assertEqual([r['vendor'] for r in compare['תקשורת']], ['סלקום', 'פרטנר'])           # the cheaper one first
        self.assertEqual(set(budget.tax_documents(2026)), {'medical', 'donation'})
        os.makedirs(os.path.join(config.RECEIPTS_DIR, '2026-03'))
        with open(os.path.join(config.RECEIPTS_DIR, '2026-03', 'k.pdf'), 'wb') as f:
            f.write(b'%PDF')
        folder, count = budget.collect_tax_documents(2026)
        self.assertEqual(count, 1)
        self.assertTrue(os.path.isfile(os.path.join(folder, 'הוצאות רפואיות', 'k.pdf')))
        self.assertTrue(os.path.isfile(os.path.join(folder, 'סיכום להחזר מס 2026.xlsx')))

    def test_stranger_asking_for_money(self):
        from mailbrief.features.security import stranger_asks_money
        ask = sorting.classify(mk('CFO <cfo@new-supplier.biz>', 'עדכון פרטי חשבון בנק', 'שלום, פרטי הבנק שלנו השתנו. נא להעביר את התשלום לחשבון החדש'), 'me@gmail.com')
        self.assertTrue(stranger_asks_money(ask, set()))
        self.assertFalse(stranger_asks_money(ask, {'cfo@new-supplier.biz'}))                    # someone you know
        self.assertFalse(stranger_asks_money(ask, {'ceo@new-supplier.biz'}))                    # a colleague of someone you know
        hello = sorting.classify(mk('Stranger <s@x.co>', 'שאלה', 'מתי אתם פתוחים?'), 'me@gmail.com')
        self.assertFalse(stranger_asks_money(hello, set()))

    def test_risky_attachments(self):
        import io as _io
        from mailbrief.features.security import attachment_risks
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('invoice.pdf.exe', b'MZ')
        with_exe = mk('A <a@b.co>', 'Invoice', 'x', attach=('invoice.zip', buf.getvalue()))
        self.assertIn('בתוך invoice.zip יש קובץ מסוכן (invoice.pdf.exe)', attachment_risks(with_exe))
        macro = mk('A <a@b.co>', 'Invoice', 'x', attach=('report.xlsm', b'PK'))
        self.assertTrue(attachment_risks(macro)[0].startswith('קובץ Office עם מאקרו'))
        self.assertIn('phishing', sorting.classify(macro, 'me@gmail.com')['cats'])
        self.assertEqual(attachment_risks(mk('A <a@b.co>', 'x', 'x', attach=('report.pdf', b'%PDF'))), [])

    def test_meeting_followup_and_holiday(self):
        from mailbrief.features import meetings
        events = [{'title': 'פגישה עם דנה', 'time': '10:00', 'link': '', 'attendees': ['dana@client.co.il']},
                  {'title': 'לבד', 'time': '12:00', 'link': '', 'attendees': []}]
        state = {}
        with mock.patch.object(meetings.google_apps, 'gapps_account', return_value={'email': 'me@gmail.com'}), \
                mock.patch.object(meetings.google_apps, 'events_on', return_value=events):
            self.assertEqual(meetings.meeting_followups(state, dt.date(2026, 9, 21)), 1)
            self.assertEqual(meetings.meeting_followups(state, dt.date(2026, 9, 21)), 0)          # once a day
        self.assertIn('לשלוח סיכום פגישה: פגישה עם דנה', storage.load_json(config.REMINDERS_FILE, [])[0]['subject'])
        now = dt.datetime(2026, 10, 5, 12, 0, tzinfo=IL)                                          # Monday; a Yom Tov starts Tuesday
        yomtov = (dt.datetime(2026, 10, 6, 17, 30, tzinfo=IL), dt.datetime(2026, 10, 7, 18, 40, tzinfo=IL))
        shabbat = (dt.datetime(2026, 10, 9, 17, 30, tzinfo=IL), dt.datetime(2026, 10, 10, 18, 40, tzinfo=IL))
        with mock.patch.object(meetings, 'holy_windows', return_value=[yomtov, shabbat]):
            self.assertEqual(meetings.next_holiday(now)[:2], yomtov)
            self.assertIsNone(meetings.next_holiday(dt.datetime(2026, 10, 8, 12, 0, tzinfo=IL)))  # only a plain Shabbat ahead

    def test_thanks_with_receipt(self):
        from mailbrief.features import clientcare, outbox
        d = clientcare.add_debt('me@gmail.com', 'dana@client.co.il', 'דנה כהן', '₪1,200', '1043', '2026-08-01')
        with mock.patch.object(clientcare, 'out_of_holy', side_effect=lambda w: w):
            clientcare.send_thanks(d['id'], [('receipt-1043.pdf', b'%PDF')])
        mail = outbox.outbox()[0]
        self.assertEqual((mail['to'], mail['files']), (['dana@client.co.il'], ['receipt-1043.pdf']))
        self.assertIn('תודה רבה על התשלום של חשבונית 1043 על סך ₪1,200', mail['body'])

    def test_partner_report_only_chosen_labels(self):
        from mailbrief.features import sharing
        storage.save_json(config.HISTORY_FILE, {
            'a': {'date': '2026-09-20', 'cats': ['people'], 'rules': ['לקוח כהן'], 'answered': False, 'sender': 'a@cohen.co.il', 'name': 'כהן', 'subject': 'הצעה'},
            'b': {'date': '2026-09-20', 'cats': ['people'], 'rules': ['פרטי'], 'answered': True, 'sender': 'mom@x.co', 'name': 'אמא', 'subject': 'שבת'}})
        subject, text, html, count = sharing.build_share({'on': True, 'email': 'p@x.co', 'name': 'יוסי', 'labels': ['לקוח כהן'], 'account': ''},
                                                         dt.date(2026, 9, 21))
        self.assertEqual(count, 1)
        self.assertIn('הצעה', text)
        self.assertNotIn('שבת', text + html)                                                    # nothing outside the chosen labels

    def test_attachment_names_and_threads(self):
        from mailbrief.features.files import _names, kind_of
        structure = (b'1 (UID 7 BODYSTRUCTURE (("text" "plain" ("charset" "utf-8") NIL NIL "7bit" 10 1)'
                     b'("application" "pdf" ("name" "=?UTF-8?B?15fXqdeR15XXoNeZ16o=?=.pdf") NIL NIL "base64" 900 NIL ("attachment" ("filename*" "utf-8\'\'%D7%A7%D7%91%D7%9C%D7%94.pdf")))'
                     b'("image" "png" ("name" "image001.png") NIL NIL "base64" 10 NIL) "mixed"))')
        self.assertEqual(_names(structure), ['חשבונית.pdf', 'קבלה.pdf'])                         # the signature image is skipped
        self.assertEqual((kind_of('a.XLSX'), kind_of('scan.jpeg'), kind_of('x.bin')), ('excel', 'image', 'other'))
        from mailbrief.web.today import by_thread
        rows = [{'account': 'a', 'subject': 'Re: הצעת מחיר', 'from': 'Dana', 'days': 5},
                {'account': 'a', 'subject': 'הצעת מחיר', 'from': 'Dana', 'days': 3},
                {'account': 'a', 'subject': 'אחר', 'from': 'Dana', 'days': 1}]
        grouped = by_thread(rows)
        self.assertEqual([(r['subject'], r.get('thread', 1)) for r in grouped], [('Re: הצעת מחיר', 2), ('אחר', 1)])

    def test_busy_hours(self):
        from mailbrief.web.dashboard import answer_tip, heatmap
        rows = [{'date': '2026-09-20', 'hour': h} for h in ['09'] * 5 + ['14'] * 4 + ['11']]
        self.assertIn('10:00 וב-15:00', answer_tip(rows))
        self.assertIn('ראשון 09:00 — 5 מיילים', heatmap(rows))


class Undo(Isolated):
    def test_undo_rule_and_paid(self):
        from mailbrief.features import clientcare, outbox, undo
        rule = {'id': 'r1', 'field': 'from', 'contains': 'client.co.il', 'label': 'לקוח'}
        undo.record('rule', 'הכלל נמחק', rule)
        item = undo.last()
        self.assertEqual(undo.undo(item['id']), '↩️ הכלל חזר')
        self.assertEqual(storage.load_json(config.RULES_FILE, []), [rule])
        self.assertIsNone(undo.last())                                                            # once only
        d = clientcare.add_debt('me@gmail.com', 'dana@client.co.il', 'דנה', '₪100', '7', '2026-08-01')
        with mock.patch.object(clientcare, 'out_of_holy', side_effect=lambda w: w):
            mail = clientcare.send_thanks(d['id'])
        clientcare.set_debt(d['id'], 'paid')
        undo.record('debt_paid', 'דנה סומנה כשולם', {'id': d['id'], 'outbox': mail['id']})
        self.assertIn('ומייל התודה בוטל', undo.undo(undo.last()['id']))
        self.assertEqual(clientcare.debts()[0]['status'], 'open')
        self.assertEqual(outbox.outbox()[0]['status'], 'cancelled')

    def test_undo_expires(self):
        from mailbrief.features import undo
        undo.record('rule', 'x', {'id': 'r'})
        self.assertIsNone(undo.last(dt.datetime.now() + dt.timedelta(minutes=6)))
        self.assertIn('↩️ ביטול', __import__('mailbrief.web.layout', fromlist=['undo_banner']).undo_banner())

    def test_undo_cleanup_puts_mail_back(self):
        from mailbrief.features import cleanup

        class FakeImap:
            def __init__(self):
                self.calls = []

            def select(self, box, *a):
                self.calls.append(('select', box))
                return 'OK', [b'2']

            def uid(self, cmd, *args):
                self.calls.append((cmd,) + args)
                return ('OK', [b'5 6']) if cmd == 'SEARCH' else ('OK', [])

            def close(self):
                pass

            def delete(self, box):
                self.calls.append(('delete', box))

            def logout(self):
                pass
        fake = FakeImap()
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'me@gmail.com', 'host': 'imap.gmail.com'}])
        with mock.patch.object(cleanup.imap, 'connect', return_value=fake):
            back = cleanup.restore_cleaned({'accounts': [{'email': 'me@gmail.com', 'gmail': True, 'label': 'MailBrief cleanup X',
                                                          'folder': '', 'uids': ''}]})
        self.assertEqual(back, 2)
        self.assertIn(('STORE', b'5,6', '+X-GM-LABELS', r'(\Inbox)'), fake.calls)
        self.assertIn(('delete', '"MailBrief cleanup X"'), fake.calls)


class Batch3(Isolated):
    def test_out_of_office(self):
        from mailbrief.features import away
        msg = mk('Dana <dana@client.co.il>', 'Automatic reply: הצעת מחיר', 'שלום, אני בחופשה עד 12/10 ואחזור לענות אז.',
                 headers={'Auto-Submitted': 'auto-replied'})
        self.assertEqual(away.note(msg, 'Dana@Client.co.il', dt.date(2026, 10, 1)), dt.date(2026, 10, 12))
        self.assertEqual(away.away('dana@client.co.il', dt.date(2026, 10, 5)), dt.date(2026, 10, 12))
        self.assertIsNone(away.away('dana@client.co.il', dt.date(2026, 10, 13)))                  # back already
        self.assertIsNone(away.note(mk('A <a@b.co>', 'שאלה', 'מתי נפגשים?'), 'a@b.co'))           # a normal mail
        self.assertEqual(away.away_until('Out of office', dt.date(2026, 10, 1)), dt.date(2026, 10, 8))   # no date: a week

    def test_streak(self):
        from mailbrief.features.streak import update_streak
        d = dt.date(2026, 10, 1)
        self.assertEqual(update_streak(True, d), 1)
        self.assertEqual(update_streak(True, d), 1)                                               # same day
        self.assertEqual(update_streak(True, d + dt.timedelta(days=1)), 2)
        self.assertEqual(update_streak(False, d + dt.timedelta(days=2)), 2)                       # today isn't over yet
        self.assertEqual(update_streak(False, d + dt.timedelta(days=4)), 0)                       # a day was missed

    def test_simple_mode_and_new_pages(self):
        from mailbrief.web import compose, layout, search, settings
        storage.save_json(config.SETTINGS_FILE, {'simple': True, 'saved_searches': ['חשבונית']})
        bar = layout.top_bar('/today')
        self.assertIn('href="/search"', bar)
        self.assertNotIn('href="/automations"', bar)
        with mock.patch.object(net, 'cached_json', return_value=None):
            html = settings.settings_page(sec='me')
        self.assertIn('להציג הכול', html)
        self.assertNotIn('href="/?s=money"', html)
        self.assertIn('🔖 חשבונית', search.search_page(''))
        self.assertIn('c-tmpl', compose.compose_page())


class Tls(unittest.TestCase):
    def test_filtered_networks_still_verified(self):
        import inspect
        import ssl
        from mailbrief import net
        from mailbrief.features import unsubscribe
        from mailbrief.mail import imap, oauth, smtp
        self.assertEqual(net.TLS.verify_mode, ssl.CERT_REQUIRED)                     # certificates are still checked
        self.assertTrue(net.TLS.check_hostname)
        self.assertFalse(net.TLS.verify_flags & ssl.VERIFY_X509_STRICT)              # NetFree's certificate is accepted
        for module in (imap, oauth, smtp, unsubscribe):                               # every connection uses it
            self.assertIn('TLS', inspect.getsource(module))


class Batch4(Isolated):
    def test_phone_from_signature(self):
        from mailbrief.features import contacts
        text = 'שלום, מצורף.\n\nבברכה,\nדנה כהן\nנייד: 050-123 4567\n\nOn Mon, someone wrote:\n> 052-9999999'
        self.assertEqual(contacts.find_phone(text), '0501234567')                   # the quoted part is someone else's
        self.assertEqual(contacts.find_phone('תודה\n+972-54-7654321'), '0547654321')
        self.assertEqual(contacts.find_phone('הזמנה 123456789012'), '')
        self.assertEqual(contacts.whatsapp('0501234567'), 'https://wa.me/972501234567')
        self.assertEqual(contacts.whatsapp('031234567'), '')                          # a landline has no WhatsApp

    def test_learn_keeps_a_number_typed_by_hand(self):
        from mailbrief.features import contacts
        msg = mk('Dana <dana@client.co.il>', 'פגישה', 'נדבר\nדנה\n050-1234567')
        contacts.learn([({'cats': ['people'], 'sender': 'dana@client.co.il'}, msg)])
        self.assertEqual(contacts.phone_of('Dana@client.co.il'), '0501234567')
        contacts.set_phone('dana@client.co.il', '054-1111111')
        contacts.learn([({'cats': ['people'], 'sender': 'dana@client.co.il'}, msg)])
        self.assertEqual(contacts.phone_of('dana@client.co.il'), '0541111111')
        contacts.learn([({'cats': ['newsletters'], 'sender': 'news@shop.com'}, mk('news@shop.com', 'x', 'call 050-2222222'))])
        self.assertEqual(contacts.phone_of('news@shop.com'), '')

    def _due(self):
        from mailbrief.features import outbox
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'me@gmail.com', 'host': 'imap.gmail.com', 'signature': 'דנה · 050-1234567'}])
        past = dt.datetime.now().astimezone() - dt.timedelta(minutes=5)
        return outbox.schedule('me@gmail.com', 'a@b.co.il', 'שלום', 'גוף', past)

    def test_outbox_waits_without_internet(self):
        from mailbrief.features import outbox
        item = self._due()
        with mock.patch.object(outbox, 'is_holy_time', return_value=False), mock.patch.object(net, 'online', return_value=False), \
                mock.patch.object(outbox.smtp, 'send_mail') as send:
            self.assertEqual(outbox.send_due(), 0)
            send.assert_not_called()
        with mock.patch.object(outbox, 'is_holy_time', return_value=False), \
                mock.patch.object(outbox.smtp, 'send_mail', side_effect=OSError('network is unreachable')):
            self.assertEqual(outbox.send_due(), 0)                                  # dropped midway: tries again later
        it = next(m for m in outbox.outbox() if m['id'] == item['id'])
        self.assertEqual(it['status'], 'waiting')
        self.assertIn('network', it['retry'])
        with mock.patch.object(outbox, 'is_holy_time', return_value=False), mock.patch.object(outbox.smtp, 'send_mail') as send:
            self.assertEqual(outbox.send_due(), 1)
        body = send.call_args[0][1].get_body(('plain',)).get_content()
        self.assertIn('-- \nדנה · 050-1234567', body)                              # the mailbox's signature

    def test_outbox_edit(self):
        from mailbrief.features import outbox
        item = self._due()
        later = dt.datetime.now().astimezone() + dt.timedelta(days=3)
        with mock.patch.object(outbox, 'holy_windows', return_value=[]):
            it = outbox.update(item['id'], 'x@y.com, z@y.com', 'חדש', 'טקסט', later)
        self.assertEqual((it['to'], it['subject'], it['body']), (['x@y.com', 'z@y.com'], 'חדש', 'טקסט'))
        with self.assertRaises(ValueError):
            outbox.update(item['id'], to='not an address')
        outbox.cancel(item['id'])
        with self.assertRaises(ValueError):
            outbox.update(item['id'], subject='x')
        self.assertEqual(outbox.with_signature('שלום\n-- \nסיג', {'signature': 'סיג'}), 'שלום\n-- \nסיג')   # not twice

    def test_month_report(self):
        from mailbrief.web.month_report import month_report_page
        storage.save_json(config.LEDGER_FILE, {'1': {'date': '2026-08-03', 'vendor': 'Bezeq', 'vendor_key': 'bezeq.co.il', 'amount': 118.0,
                                                     'currency': '₪', 'subject': 'חשבונית', 'files': ['a.pdf']}})
        html = month_report_page('2026-08')
        self.assertIn('08/2026', html)
        self.assertIn('Bezeq', html)
        self.assertIn('₪18', html)                                                    # VAT inside 118
        self.assertIn('window.print()', html)

    def test_names_and_previews(self):
        from mailbrief import view
        from mailbrief.web.files import preview_page
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'a.b@gmail.com', 'host': 'imap.gmail.com', 'display_name': 'דנה'}])
        self.assertIn('דנה', view.label('a.b@gmail.com'))
        self.assertIn('a.b', view.label('a.b@gmail.com'))
        self.assertIn('כבר לא זמינה', preview_page('../../etc'))
        self.assertIn('כבר לא זמינה', preview_page('0123456789abcdef'))


class Batch5(Isolated):
    def test_income_from_payment_notices(self):
        from mailbrief.features import income
        got = income.parse('Bit <noreply@bit.co.il>', 'קיבלת כסף בביט', 'דנה כהן העבירה לך ₪350 בביט')
        self.assertEqual((got['service'], got['amount'], got['currency'], got['payer']), ('Bit', 350.0, '₪', 'דנה כהן'))
        got = income.parse('service@paypal.com', "You've received $120.00 USD", 'John Smith sent you $120.00 USD')
        self.assertEqual((got['service'], got['amount'], got['currency']), ('PayPal', 120.0, '$'))
        self.assertIsNone(income.parse('Bit <noreply@bit.co.il>', 'שילמת בביט', 'שילמת ₪50 לדנה'))        # money going out
        self.assertIsNone(income.parse('shop@store.com', 'קיבלת הנחה', '₪20 הנחה'))                     # not a payment service

    def test_income_marks_the_invoice_paid(self):
        from mailbrief.features import clientcare, income, undo
        d = clientcare.add_debt('me@gmail.com', 'dana@client.co.il', 'דנה כהן', '₪1,200', '101', '2026-09-01')
        clientcare.add_debt('me@gmail.com', 'yossi@x.co.il', 'יוסי', '₪1,200', '102', '2026-09-01')
        msg = mk('Bit <noreply@bit.co.il>', 'קיבלת כסף', 'דנה כהן העבירה לך ₪1,200 בביט')
        rows = income.learn([({'sender': 'noreply@bit.co.il', 'subject': 'קיבלת כסף', 'iso': '2026-09-20T10:00:00+03:00'}, msg)], 'me@gmail.com')
        self.assertEqual(rows[0]['debt'], d['id'])
        self.assertEqual(next(x for x in clientcare.debts() if x['id'] == d['id'])['status'], 'paid')
        self.assertEqual(next(x for x in clientcare.debts() if x['name'] == 'יוסי')['status'], 'open')    # same amount, other person
        self.assertEqual(income.learn([({'sender': 'noreply@bit.co.il', 'subject': 'x'}, msg)], 'me@gmail.com'), [])  # once
        self.assertEqual(income.month_total('2026-09'), (1200.0, {'Bit': 1200.0}))
        undo.undo(undo.last()['id'])
        self.assertEqual(next(x for x in clientcare.debts() if x['id'] == d['id'])['status'], 'open')

    def test_recurring(self):
        from mailbrief.features import outbox, recurring
        with self.assertRaises(ValueError):
            recurring.add('me@gmail.com', 'a@b.co.il', 'x', '', 'weekly', 6)                              # never Shabbat
        r = recurring.add('me@gmail.com', 'a@b.co.il', 'תזכורת ל{חודש}', 'שלום, {היום}', 'monthly', 1, '09:00')
        now = dt.datetime(2026, 10, 1, 8, 0, tzinfo=IL)
        with mock.patch.object(outbox, 'holy_windows', return_value=[]):
            self.assertEqual(recurring.run_recurring(now), 0)                                           # before its hour
            self.assertEqual(recurring.run_recurring(now.replace(hour=10)), 1)
            self.assertEqual(recurring.run_recurring(now.replace(hour=11)), 0)                          # once a day
        sent = outbox.outbox()[-1]
        self.assertEqual((sent['subject'], sent['body']), ('תזכורת לאוקטובר', 'שלום, 01/10/2026'))
        recurring.set_item(r['id'], 'off')
        self.assertFalse(recurring.items()[0]['on'])
        self.assertEqual(recurring.when_text(r), 'כל 1 בחודש ב-09:00')

    def test_deadlines(self):
        from mailbrief.features import deadlines
        today = dt.date(2026, 9, 27)                                                                     # a Sunday
        self.assertEqual(deadlines.find_deadline('נא לשלוח עד 15/10. תודה', today)[0], dt.date(2026, 10, 15))
        self.assertEqual(deadlines.find_deadline('צריך את זה עד יום חמישי', today)[0], dt.date(2026, 10, 1))
        self.assertEqual(deadlines.find_deadline('Deadline: 3.11.2026', today)[0], dt.date(2026, 11, 3))
        self.assertEqual(deadlines.find_deadline('עד סוף החודש בבקשה', today)[0], dt.date(2026, 9, 30))
        self.assertIsNone(deadlines.find_deadline('נפגשנו ב-15/10 שעבר, מחיר 3.5', dt.date(2026, 10, 20))[0])
        when, sentence = deadlines.find_deadline('שלום\nאפשר להגיש עד 15/10 לכל המאוחר\nתודה', today)
        self.assertEqual(sentence, 'אפשר להגיש עד 15/10 לכל המאוחר')

    def test_pin_lock(self):
        from mailbrief.features import lock
        self.assertFalse(lock.enabled())
        with self.assertRaises(ValueError):
            lock.set_pin('12a4')
        lock.set_pin('4321', idle=10)
        self.assertTrue(lock.enabled())
        self.assertNotIn('4321', str(storage.load_json(config.SETTINGS_FILE, {})))                    # only a hash is kept
        self.assertFalse(lock.check('1111'))
        self.assertTrue(lock.check('4321'))
        ticket = lock.ticket('k', now=1000)
        self.assertTrue(lock.valid(ticket, 'k', now=1000 + 9 * 60))
        self.assertFalse(lock.valid(ticket, 'k', now=1000 + 11 * 60))                                   # idle too long
        self.assertFalse(lock.valid(ticket, 'other-run', now=1000))
        self.assertFalse(lock.valid('1000.forged', 'k', now=1000))
        for _ in range(5):
            lock.check('0000')
        with self.assertRaises(RuntimeError):                                                            # 5 wrong: wait
            lock.check('4321')
        lock._FAILS.update(count=0, until=0)
        lock.clear_pin()
        self.assertFalse(lock.enabled())

    def test_backup_check(self):
        from mailbrief.features import maintenance
        self.assertFalse(maintenance.verify_backup()[0])                                                 # none yet
        storage.save_json(config.SETTINGS_FILE, {'x': 1})
        maintenance.make_backup('test')
        ok, detail = maintenance.verify_backup()
        self.assertTrue(ok, detail)
        broken = os.path.join(config.BACKUP_DIR, 'mailbrief-2099-01-01-000000-bad.zip')
        with open(broken, 'wb') as f:
            f.write(b'not a zip')
        self.assertFalse(maintenance.verify_backup()[0])
        state = {}
        with mock.patch.object(maintenance, 'verify_cloud', return_value=(None, '')):
            ok, lines = maintenance.check_backups(state)
            self.assertFalse(ok)                                                                         # the broken newest one...
            self.assertIn('גם', ''.join(lines))                                                          # ...still sorts first
            self.assertEqual(maintenance.check_backups(state), (None, []))                               # once a month

    def test_contacts_and_template_files(self):
        from mailbrief.features import contacts, replies
        from mailbrief.web.contacts import contacts_page, export_csv, people
        storage.save_json(config.HISTORY_FILE, {
            '1': {'sender': 'dana@client.co.il', 'name': 'דנה', 'cats': ['people'], 'date': '2026-09-20', 'account': 'me@gmail.com'},
            '2': {'sender': 'news@shop.com', 'name': 'Shop', 'cats': ['newsletters'], 'date': '2026-09-21', 'account': 'me@gmail.com'}})
        contacts.set_phone('dana@client.co.il', '050-1234567')
        rows = people()
        self.assertEqual([(p['name'], p['phone']) for p in rows], [('דנה', '0501234567')])
        self.assertIn('050-1234567', contacts_page())
        with open(export_csv(), encoding='utf-8-sig') as f:
            self.assertIn('דנה,dana@client.co.il,050-1234567', f.read())
        os.makedirs(replies.template_dir('abcd1234'))
        with open(os.path.join(replies.template_dir('abcd1234'), 'מחירון.pdf'), 'wb') as f:
            f.write(b'%PDF')
        self.assertEqual(replies.template_files('abcd1234'), [('מחירון.pdf', b'%PDF')])
        self.assertEqual(replies.template_files('../../x'), [])

    def test_new_settings_render(self):
        from mailbrief.web.settings import settings_page
        for sec, marker in (('money', 'id="income"'), ('auto', 'id="recurring"'), ('me', 'id="pin"'), ('data', 'id="backupcheck"')):
            self.assertIn(marker, settings_page('', sec))


class Batch6(Isolated):
    def _history(self):
        today = dt.date.today()
        day = lambda n: (today - dt.timedelta(days=n)).isoformat()
        rows = {}
        for i in range(8):                                     # Dana: many emails, slow answers, one waiting
            rows[f'd{i}'] = {'sender': 'dana@client.co.il', 'name': 'דנה', 'cats': ['people'], 'date': day(i * 3), 'account': 'me@gmail.com',
                             'answered': i != 0, 'reply_hours': 30.0 if i else None, 'rules': [], 'subject': f's{i}'}
        for i in range(2):                                     # Yossi: few, fast
            rows[f'y{i}'] = {'sender': 'yossi@x.co.il', 'name': 'יוסי', 'cats': ['people'], 'date': day(i * 10), 'account': 'me@gmail.com',
                             'answered': True, 'reply_hours': 0.5, 'rules': [], 'subject': f'y{i}'}
        storage.save_json(config.HISTORY_FILE, rows)

    def test_client_stats(self):
        from mailbrief.features.client_stats import client_stats, fmt_hours, top_priorities
        self._history()
        stats = client_stats()
        dana, yossi = stats[0], stats[1]
        self.assertEqual((dana['name'], dana['emails'], dana['waiting'], dana['median_hours']), ('דנה', 8, 1, 30.0))
        self.assertEqual(yossi['median_hours'], 0.5)
        self.assertEqual(top_priorities(stats)[0]['name'], 'דנה')
        self.assertIn('מייל אחד מחכה לתשובה', dana['why'])
        self.assertEqual((fmt_hours(0.5), fmt_hours(5), fmt_hours(72)), ('30 דק׳', '5 שע׳', '3 ימים'))
        from mailbrief.web.clients import client_page, client_stats_page
        html = client_stats_page()
        self.assertIn('כדאי לתת עדיפות', html)
        self.assertIn('דנה', html)
        self.assertIn('/client_docs', client_page(dana['key']))

    def test_reply_time_is_kept(self):
        from mailbrief.features import history
        from mailbrief.money.ledger import item_key
        it = {'iso': '2026-09-20T10:00:00+03:00', 'cats': ['people'], 'sender': 'a@b.co.il', 'sender_name': 'A', 'subject': 's',
              'message_id': '<1@x>', 'answered': True, 'reply_hours': 3.5}
        history.update_history([{'email': 'me@gmail.com', 'items': [it]}])
        history.update_history([{'email': 'me@gmail.com', 'items': [dict(it, reply_hours=None)]}])        # a later look without it
        self.assertEqual(storage.load_json(config.HISTORY_FILE, {})[item_key('me@gmail.com', it)]['reply_hours'], 3.5)

    def test_reply_hours_from_sent(self):
        m = mock.Mock()
        m.uid.return_value = ('OK', [b'5 (UID 5 INTERNALDATE "20-Sep-2026 15:30:00 +0300")'])
        self.assertEqual(imap.reply_hours(m, b'5', '2026-09-20T10:00:00+03:00'), 5.5)
        m.uid.return_value = ('NO', [None])
        self.assertIsNone(imap.reply_hours(m, b'5', '2026-09-20T10:00:00+03:00'))

    def test_client_zip(self):
        import zipfile
        from mailbrief.features import client_docs
        self._history()
        key = next(k for k, g in client_docs.client_groups().items() if g['name'] == 'דנה')
        pdf = b'%PDF' + b'x' * 3000
        mails = [('2026-09-01', 'חשבונית.pdf', pdf), ('2026-09-02', 'חשבונית.pdf', pdf),          # the same file twice
                 ('2026-09-03', 'חשבונית.pdf', pdf + b'2')]                                      # same name, other content
        with mock.patch.object(client_docs, '_mail_files', return_value=iter(mails)):
            path, count, errors = client_docs.client_zip(key)
        self.assertEqual((count, errors), (2, []))
        with zipfile.ZipFile(path) as z:
            self.assertEqual(sorted(z.namelist()), ['מהמייל/2026-09-01 חשבונית.pdf', 'מהמייל/2026-09-03 חשבונית.pdf'])
        with mock.patch.object(client_docs, '_mail_files', side_effect=OSError('offline')):
            path, count, errors = client_docs.client_zip(key)
        self.assertEqual((path, count), ('', 0))
        self.assertTrue(errors)


class NetFree(Isolated):
    def test_block_is_named(self):
        import io
        import urllib.error
        err = urllib.error.HTTPError('https://www.googleapis.com/calendar/v3/x', 418, 'Error in NetFree', {}, io.BytesIO(b''))
        self.assertIn('נטפרי', net.netfree_block(err))
        self.assertIn('www.googleapis.com', net.netfree_block(err))
        self.assertEqual(net.netfree_block(urllib.error.HTTPError('https://x.com', 500, 'oops', {}, io.BytesIO(b''))), '')
        self.assertEqual(net.explain(ValueError('other')), 'other')
        with mock.patch.object(google_apps, '_token', return_value='t'),                 mock.patch.object(google_apps.urllib.request, 'urlopen', side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                google_apps.api({'email': 'me@gmail.com'}, 'GET', 'calendar/v3/x')
        self.assertIn('נטפרי', str(ctx.exception))
        self.assertIn('נטפרי', accounts.friendly_error(err, {'email': 'me@gmail.com'}))


class Batch7(Isolated):
    def test_mail_merge(self):
        from mailbrief.features import mailmerge, outbox
        from mailbrief.money.excel import write_xlsx
        path = os.path.join(config.DATA, 'list.xlsx')
        write_xlsx(path, 'לקוחות', ['שם', 'מייל'], [['דנה כהן', 'dana@client.co.il'], ['יוסי', 'yossi@x.co.il'],
                                                    ['כפול', 'DANA@client.co.il'], ['בלי', 'not-an-address']], [20, 30])
        with open(path, 'rb') as f:
            rows = mailmerge.recipients_from_table(mailmerge.read_table('list.xlsx', f.read()))
        self.assertEqual(rows, [('dana@client.co.il', 'דנה כהן'), ('yossi@x.co.il', 'יוסי')])
        csv_rows = mailmerge.read_table('a.csv', 'a@b.co.il,רחל\nc@d.co.il,\n'.encode('cp1255'))
        self.assertEqual(mailmerge.recipients_from_table(csv_rows), [('a@b.co.il', 'רחל'), ('c@d.co.il', '')])
        when = dt.datetime.now().astimezone() + dt.timedelta(hours=1)
        self.assertEqual(mailmerge.send_merge('me@gmail.com', rows, 'היי {שם_פרטי}', 'שלום {שם_פרטי},\nעדכון', when), 2)
        sent = outbox.outbox()
        self.assertEqual([(m['to'], m['subject']) for m in sent], [(['dana@client.co.il'], 'היי דנה'), (['yossi@x.co.il'], 'היי יוסי')])
        with self.assertRaises(ValueError):
            mailmerge.send_merge('me@gmail.com', [], 'x', 'y', when)

    def test_follow_up(self):
        from mailbrief.features import autofollow, outbox
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'me@gmail.com', 'host': 'imap.gmail.com'}])
        past = dt.datetime.now().astimezone() - dt.timedelta(minutes=5)
        item = outbox.schedule('me@gmail.com', 'a@b.co.il', 'הצעת מחיר', 'מצורפת', past, follow={'days': 3, 'text': 'עדיין רלוונטי?'})
        with mock.patch.object(outbox, 'is_holy_time', return_value=False), mock.patch.object(outbox.smtp, 'send_mail') as send:
            outbox.send_due()
        mid = send.call_args[0][1]['Message-ID']
        row = autofollow.items()[0]
        self.assertEqual((row['message_id'], row['status']), (mid, 'waiting'))
        later = dt.datetime.now().astimezone() + dt.timedelta(days=4)
        m = mock.Mock()
        m.uid.return_value = ('OK', [b''])                                         # no reply found
        with mock.patch.object(imap, 'connect', return_value=m), mock.patch('mailbrief.mail.imap.special_folder', return_value='[Gmail]/All Mail'), \
                mock.patch.object(net, 'online', return_value=True), mock.patch.object(outbox, 'holy_windows', return_value=[]):
            self.assertEqual(autofollow.check_due(later), 1)
        reminder = outbox.outbox()[-1]
        self.assertEqual((reminder['subject'], reminder['body'], reminder['thread']['in_reply_to']), ('Re: הצעת מחיר', 'עדיין רלוונטי?', mid))
        self.assertNotEqual(item['id'], reminder['id'])
        # a reply cancels it
        autofollow.register(dict(item, message_id='<2@x>', follow={'days': 1}), dt.datetime.now().astimezone())
        m.uid.return_value = ('OK', [b'7'])
        with mock.patch.object(imap, 'connect', return_value=m), mock.patch('mailbrief.mail.imap.special_folder', return_value='INBOX'), \
                mock.patch.object(net, 'online', return_value=True):
            self.assertEqual(autofollow.check_due(later), 0)
        self.assertEqual(autofollow.items()[-1]['status'], 'answered')

    def test_free_slots(self):
        from mailbrief.features import slots
        now = dt.datetime(2026, 9, 27, 8, 0, tzinfo=IL)                                    # Sunday morning
        events = [{'day': '2026-09-27', 'time': '10:00', 'end_iso': '2026-09-27T13:00:00+03:00'},
                  {'day': '2026-09-28', 'time': 'כל היום', 'end_iso': '2026-09-29'}]
        found = slots.free_slots(events, now=now, holy=[])
        self.assertTrue(all(s.weekday() not in (4, 5) for s in found))                    # no Friday / Shabbat
        self.assertTrue(all(not (s.date() == now.date() and 10 <= s.hour < 13) for s in found))   # not in the meeting
        self.assertTrue(all(s >= now + dt.timedelta(hours=2) for s in found))
        self.assertLessEqual(len(found), 6)
        self.assertIn('יום ראשון 27/09 בשעה 13:00', slots.slots_text(found))
        self.assertEqual(slots.slots_text([]), '')

    def test_signature_with_logo(self):
        from mailbrief.features import outbox
        acc = {'id': 'abcd1234', 'email': 'me@gmail.com', 'signature': 'דנה', 'signature_logo': 'png',
               'signature_links': {'site': 'https://dana.co.il', 'whatsapp': '0501234567'}}
        os.makedirs(os.path.dirname(outbox.logo_path(acc)), exist_ok=True)
        with open(outbox.logo_path(acc), 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'0' * 50)
        item = {'id': 'x', 'to': ['a@b.co.il'], 'subject': 's', 'body': 'שלום'}
        msg = outbox.build(item, acc)
        html = msg.get_body(('html',)).get_content()
        self.assertIn('cid:mailbrief-logo', html)
        self.assertIn('https://wa.me/972501234567', html)
        self.assertIn('dana.co.il', html)
        self.assertTrue(any(p.get('Content-ID') == '<mailbrief-logo>' for p in msg.walk()))
        self.assertIn('-- \nדנה', msg.get_body(('plain',)).get_content())
        self.assertTrue(item['message_id'].endswith('@gmail.com>'))

    def test_blocking(self):
        from mailbrief.features import blocking
        blocking.block('Spam@Shop.com')
        blocking.block('@ads.co.il')
        self.assertTrue(blocking.is_blocked('spam@shop.com'))
        self.assertTrue(blocking.is_blocked('news@ads.co.il'))
        self.assertFalse(blocking.is_blocked('friend@shop.com'))
        m = mock.Mock()
        items = [{'sender': 'spam@shop.com', 'uid': '5'}, {'sender': 'dana@client.co.il', 'uid': '6'}]
        with mock.patch('mailbrief.mail.imap.is_gmail', return_value=True):
            kept = blocking.archive_blocked(m, {'email': 'me@gmail.com', 'host': 'imap.gmail.com'}, items)
        self.assertEqual([it['sender'] for it in kept], ['dana@client.co.il'])
        m.uid.assert_called_with('STORE', b'5', '-X-GM-LABELS', r'(\Inbox)')
        blocking.unblock('spam@shop.com')
        self.assertFalse(blocking.is_blocked('spam@shop.com'))
        with self.assertRaises(ValueError):
            blocking.block('nothing')

    def test_year_report(self):
        from mailbrief.web.year_report import year_report_page
        storage.save_json(config.LEDGER_FILE, {'1': {'date': '2026-03-03', 'vendor': 'Bezeq', 'vendor_key': 'bezeq.co.il', 'amount': 118.0,
                                                     'currency': '₪', 'subject': 'חשבונית'}})
        storage.save_json(config.INCOME_FILE, {'k': {'date': '2026-03-10', 'service': 'Bit', 'amount': 500.0, 'currency': '₪', 'payer': 'דנה'}})
        html = year_report_page('2026')
        for text in ('סיכום שנת 2026', 'Bezeq', 'דנה', '₪500', '₪382', 'window.print()'):
            self.assertIn(text, html)

    def test_new_pages_render(self):
        from mailbrief.web.compose import compose_page
        from mailbrief.web.merge import merge_page
        from mailbrief.web.settings import settings_page
        self.assertIn('/merge_send', merge_page())
        self.assertIn('/free_slots', compose_page())
        self.assertIn('id="blocked"', settings_page('', 'auto'))
        storage.save_json(config.ACCOUNTS_FILE, [{'id': 'abcd1234', 'email': 'me@gmail.com', 'host': 'imap.gmail.com'}])
        self.assertIn('name="logo"', settings_page('', 'boxes'))


class Batch8(Isolated):
    def test_payment_details_in_reminders(self):
        from mailbrief.features import clientcare, outbox
        self.assertEqual(clientcare.payment_text({}), '')
        text = clientcare.payment_text({'bit': 'https://bit.ly/x', 'bank': 'לאומי 800-12345'})
        self.assertIn('https://bit.ly/x', text)
        self.assertIn('לאומי 800-12345', text)
        body = clientcare.with_payment('שלום דנה,\n\nתזכורת.\n\nבברכה,\nרחל', text)
        self.assertLess(body.index('bit.ly'), body.index('בברכה'))                         # before the sign-off
        self.assertEqual(clientcare.with_payment('א {פרטי_תשלום} ב', 'X'), 'א X ב')
        self.assertEqual(clientcare.with_payment('א {פרטי_תשלום} ב', ''), 'א  ב')
        storage.save_json(config.SETTINGS_FILE, {'payment': {'paybox': 'https://payboxapp.page.link/abc'}})
        clientcare.add_debt('me@gmail.com', 'dana@client.co.il', 'דנה', '₪500', '7', '2026-08-01', due_days=10)
        with mock.patch.object(clientcare, 'out_of_holy', side_effect=lambda w: w):
            self.assertEqual(clientcare.chase_due(dt.date(2026, 9, 1)), 1)
        self.assertIn('https://payboxapp.page.link/abc', outbox.outbox()[-1]['body'])

    def test_yearly_renewals(self):
        from mailbrief.features.renewals import yearly_renewals
        ledger = {'1': {'date': '2025-10-10', 'vendor': 'Domains Ltd', 'vendor_key': 'domains.co.il', 'amount': 99.0, 'currency': '₪'},
                  '2': {'date': '2026-09-01', 'vendor': 'Bezeq', 'vendor_key': 'bezeq.co.il', 'amount': 118.0, 'currency': '₪'},
                  '3': {'date': '2025-09-01', 'vendor': 'Bezeq', 'vendor_key': 'bezeq.co.il', 'amount': 118.0, 'currency': '₪'}}
        found = yearly_renewals(ledger, today=dt.date(2026, 9, 27))
        self.assertEqual([(r['vendor'], r['next'], r['days']) for r in found], [('Domains Ltd', dt.date(2026, 10, 10), 13)])
        self.assertEqual(yearly_renewals(ledger, today=dt.date(2026, 3, 1)), [])

    def test_holiday_reply(self):
        from mailbrief.features import holiday_reply
        items = [{'category': 'holiday', 'title': 'Erev Sukkot', 'date': '2026-09-25'},
                 {'category': 'holiday', 'title': 'Sukkot I', 'date': '2026-09-26'},
                 {'category': 'holiday', 'title': "Sukkot II (CH''M)", 'date': '2026-09-27'},
                 {'category': 'holiday', 'title': "Sukkot VII (Hoshana Raba)", 'date': '2026-10-02'},
                 {'category': 'holiday', 'title': 'Shmini Atzeret', 'date': '2026-10-03'}]
        for n in range(3, 7):
            items.append({'category': 'holiday', 'title': f"Sukkot {n} (CH''M)", 'date': (dt.date(2026, 9, 25) + dt.timedelta(days=n)).isoformat()})
        self.assertEqual(holiday_reply.holiday_period(items, dt.date(2026, 9, 29)), ('סוכות', dt.date(2026, 9, 25), dt.date(2026, 10, 3)))
        self.assertIsNone(holiday_reply.holiday_period(items, dt.date(2026, 10, 5)))
        storage.save_json(config.CACHE_FILE, {'holy': {'data': {'items': items}}})
        self.assertIsNone(holiday_reply.active(dt.date(2026, 9, 29)))                            # off by default
        storage.save_json(config.SETTINGS_FILE, {'holiday_reply': {'on': True, 'message': ''}})
        now = holiday_reply.active(dt.date(2026, 9, 29))
        self.assertEqual((now['holiday'], now['to'], now['message']), ('סוכות', '2026-10-03', holiday_reply.DEFAULT))

    def test_undo_send(self):
        from mailbrief.features import outbox, undo
        later = dt.datetime.now().astimezone() + dt.timedelta(seconds=40)
        item = outbox.schedule('me@gmail.com', 'a@b.co.il', 'x', 'y', later)
        undo.record('send', 'יוצא בעוד רגע', {'ids': [item['id']]})
        self.assertIn('בוטלה', undo.undo(undo.last()['id']))
        self.assertEqual(outbox.outbox()[0]['status'], 'cancelled')
        undo.record('send', 'שוב', {'ids': [item['id']]})
        self.assertIn('כבר נשלח', undo.undo(undo.last()['id']))

    def test_important_only(self):
        from mailbrief.web import today
        storage.save_json(config.SNAPSHOT_FILE, {'waiting': [
            {'account': 'me@gmail.com', 'from': 'דנה', 'sender': 'dana@client.co.il', 'subject': 'שאלה', 'days': 2, 'message_id': '<1>', 'link': ''},
            {'account': 'me@gmail.com', 'from': 'Shop', 'sender': 'hello@shop.com', 'subject': 'מבצע', 'days': 1, 'message_id': '<2>', 'link': ''}]})
        storage.save_json(config.SETTINGS_FILE, {'quiet': {'vip': ['dana@client.co.il']}, 'profile': {'name': 'רחל'}})
        with mock.patch.object(net, 'cached_json', return_value=None), mock.patch.object(today, 'today_overview', return_value=None), \
                mock.patch.object(today, 'holy_windows', create=True, return_value=[]):
            html = today.today_page()
        self.assertIn('id="mb-imp-btn"', html)
        self.assertRegex(html, r'data-imp="1"[^>]*data-name="דנה"')
        self.assertRegex(html, r'data-imp="0"[^>]*data-name="Shop"')

    def test_forgot_attachment_script(self):
        from mailbrief.web import extras
        self.assertIn('mb-attach-note', extras.HTML)
        self.assertIn('מצורפ', extras.HTML)


class Batch9(Isolated):
    def test_settings_search(self):
        from mailbrief.web import settings_search
        settings_search._CACHE.update(at=0.0, rows=[])
        rows = settings_search.index()
        ids = {r['id'] for r in rows}
        for anchor in ('pin', 'income', 'recurring', 'blocked', 'backupcheck', 'holidayreply'):
            self.assertIn(anchor, ids)
        self.assertTrue(any('חתימה' in r['title'] for r in rows))
        self.assertTrue(all('<' not in r['text'] for r in rows))                       # plain text, no markup
        from mailbrief.web.settings import settings_page
        self.assertIn('id="set-q"', settings_page())

    def test_guide_groups(self):
        from mailbrief.web.help import GUIDE, grouped
        groups = grouped()
        self.assertEqual(sum(len(r) for _, r in groups), len(GUIDE))                   # every feature in exactly one group
        names = dict(groups)
        self.assertTrue(any(link == '/merge' for _, link, _ in names['✉️ שליחה, תבניות ואוטומציות']))
        self.assertTrue(any(link == '/year_report' for _, link, _ in names['💰 כסף, קבלות ורו״ח']))

    def test_template_ranking(self):
        from mailbrief.features.replies import rank_templates
        templates = [{'id': 'a', 'name': 'תודה', 'text': 'תודה רבה!'},
                     {'id': 'b', 'name': 'הצעת מחיר', 'text': 'מצורפת הצעת המחיר'},
                     {'id': 'c', 'name': 'בקשת חשבונית', 'text': 'אשמח לקבל חשבונית'}]
        self.assertEqual(rank_templates('בקשה להצעת מחיר לשיפוץ', templates)[0][0]['id'], 'b')
        self.assertEqual(rank_templates('Invoice #123 — חשבונית', templates)[0][0]['id'], 'c')
        self.assertEqual([t['id'] for t, s in rank_templates('שלום', templates)], ['a', 'b', 'c'])   # no match: original order
        from mailbrief.web.triage import best_template
        storage.save_json(config.SETTINGS_FILE, {'templates': templates})
        self.assertEqual(best_template('הצעת מחיר'), 'b')
        self.assertEqual(best_template('שלום'), '')

    def test_pdf_search(self):
        from mailbrief.features import pdfsearch
        self.assertEqual(pdfsearch.words('from:(dana) חשבונית has:attachment OR "ארנונה"'), ['חשבונית', 'ארנונה'])
        os.makedirs(os.path.join(config.RECEIPTS_DIR, '2026-09'))
        path = os.path.join(config.RECEIPTS_DIR, '2026-09', 'bezeq.pdf')
        with open(path, 'wb') as f:
            f.write(b'%PDF-1.4 fake')
        with mock.patch.object(pdfsearch, 'pdf_text', return_value='חשבונית מס 4471 בזק סכום לתשלום 118.00') as read:
            hits = pdfsearch.search('4471 בזק')
            self.assertEqual([h['name'] for h in hits], ['bezeq.pdf'])
            self.assertIn('4471', hits[0]['snippet'])
            pdfsearch.search('בזק')
            self.assertEqual(read.call_count, 1)                                         # read once, then from the index
        self.assertEqual(pdfsearch.search('ארנונה'), [])
        self.assertTrue(pdfsearch.known(path))
        self.assertFalse(pdfsearch.known(os.path.join(config.DATA, 'accounts.json')))    # only indexed PDFs can be opened

    def test_email_notes(self):
        from mailbrief.features import email_notes
        email_notes.set_note('me|<1>', 'דיברנו בטלפון')
        self.assertEqual(email_notes.notes()['me|<1>']['text'], 'דיברנו בטלפון')
        email_notes.set_note('me|<1>', '  ')
        self.assertNotIn('me|<1>', email_notes.notes())

    def test_tour_is_new(self):
        from mailbrief.web import extras
        self.assertIn("'mb-tour-2'", extras.HTML)
        self.assertIn('#mb-imp-btn', extras.HTML)


OCR_PNG = (   # "Invoice 4471 / Total 118.00 ILS", drawn in Arial — for the real Windows text-recognition test
    'iVBORw0KGgoAAAANSUhEUgAAAggAAABuCAYAAABCzusNAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqG'
    'QAAAwRSURBVHhe7d2NUePMEoVhkiELkiAGUiAFMiADIiACEiABEiABAuCrs3Wb6u35Uc+MpLW571M1tayskWWZmj4ayebmGwAAILiJCwAAAAgI'
    'AACgQEAAAAAFAgIAACgQEAAAQIGAAAAACgQEAABQICAAAIACAQEAABQICAAAoEBAAAAABQICAAAoEBAAAECBgAAAAAoEBAAAUNglIDw/P3/f3N'
    'z8ae/v7/Hhq2OvRa/rt3h9ff15XTO2+t/f3/88nm3qk/H5+Tm0PgBgXX20H0RAuGxWYK2NyvQ/KiB8fX19393dpdcHAOyjPtoPIiBcNiuw1kZl'
    '+s8EhIeHh7iZv/hwoEZAAIDz1Ef7Qb8tIPwmT09PRWEesdrf8wX/9vb2z/9bNGsRgwkBAQDOMz/aOwSEy/T29vZTjH2hz1rtHz0+Pv5s4+PjIz'
    '784+Xl5a9gQEAAgPPNj/YOAeHy6OzcF2P/HmWs9o8sbKj1Lt3osoMPBepnly8ICABwnrnRPugFBF8UVHT0r586trPTON3szyLjNiN/Zuq3o2lq'
    'Pabn8M+nZb1t+n1uaW279loi9dV6cQpdxbG3XyOsqNprGC3wq/09HQ87TluXFux5dWxtPQICAJxvfLSvyASEWkGMTYXT+DNYFYue2nr+Y3mtpn'
    '2qscdbAcG/3lZrTaG3ps9923q9W2z/fEEdKfCr/SPfVzMCPTo+/vdACAgAcL7x0b4iExCsaV0rAPrXTynHwuhnBlp8ELDn9ssUSnxR0s8+qNRC'
    'QO8xX+DjtmMoiWfKvq+Kne+rQOGv88djkaXt2DZ8oc0W+NX+kQ96swWegAAA5xsb7RuyAaF19ugLtuevW7f6WsDQ1LX4gqTtxiJtrOioxTNWWx'
    '4DQtx2jV5/rb//LoFe8fcho/WaW/xUfuybKfCr/Wt6vxtZBAQAON/YaN/QKwK23Ap4Ta/4WMGqfWbeF2ydnUttRqHGF+x4qcGWx4CQ3bYFHh8i'
    '/OxAK7QY6197zT0WluLrkd4xNqv9oz1mD4SAAADny4/2HZmA0Ct2veLjH4uF1U/Z2yxA5rKEsUIcC4/1jwFhZNvRSJHrHY8WOxatWZOtba72r/'
    'GBSj/PGjl2AIB95Ef7jkxAiMXW6/X3Z/qxyNTOtEeKib/M4LX2eWTbkW1ztGX4+wZaN0f2Cvxq/5bWpaNRK8cdADBnbeT+n16Bt+Wx2Hq9/mIF'
    'wk/Zt4LDSDH5LQHBH7+RZq9jtX9N9p6LjJXjDgCYk6tAG3oF3pbHYuv1+oufqrZLCa1v9hspJv8iINSu769aLfCr/WtWbraMVo47AGDOVQQEid'
    'uxmxfj2enIfQKj9yD4j2T2+E9f2Oup3bi4l9UCv9q/JnusMggIAHC+9dF7o8Db8lhsvV5/Y4VfBbZ3zTx75jrzKYbstzvWQopfFvc5soLY++TH'
    'KH+MZ4z27336ZBQBAQDOlxvtN/QKvC2Pxdbr9Tc+FNjZae1sPH5XQe2OfPGXF2a+B6FVrPx++tkNH0h6++UDTnz+FaMFPhrp71/rHq+BgAAA59'
    'se7RN6BT5TKHr9PX9XvJp990E08k2KcfZAevvst62C5ffXX1pQiyHA3zehM2xty9ZRUfXHoRciZowU+JqR/jomtm5vFieLgAAA59se7RN6Bd6W'
    '14qt6fX34t8x6BXQ+LXHtVYLB7K1z3E/aq11GcGHhFbbOxzISIGvGemfvRSTRUAAgPNtj/YJvQJvy1vFVnr9PT/Fn7m2rbNyTfPHv7ioZfGygp'
    'fZ59q2VdjVZ6u4W984I6ICGL/rYS8jBb5mpL9fd+tYZBAQAOB826M9AAD4v0NAAAAABQICAAAoEBAAAECBgAAAAAoEBAAAUCAgAACAAgEBAAAU'
    'CAgAAKBAQAAAAAUCAgAAKBAQAABAgYAAAAAKBAQAAFAgIAAAgAIBAQAAFAgIAACgQEAAAAAFAgIAACgQEAAAQIGAAAAACgQEAABQICAAAIACAQ'
    'EAABQICAAAoEBAAAAABQICAAAoLAWE5+fn75ubm6V2lK+vr7hoF7bfeu17+fz8/LPN+/v7+FDKaH+t//j4+H17e/vzevSzlumxVTr2Oj53d3d/'
    'bf/p6Sn1vqz2b/G/r+/v7389pmO31++ktq1j6fdfTf/X8re3t9gFAC7O0mh4qQHh5eXlsG3bfu8VEFTwrJBkC7w32v/19bV4D2LTOrM+Pj7+Ch'
    '61pnVaVvv3HB0Q9F747fSa3rPZ1wEAZ5gfDS80IDw8PBy2bbFt7xEQfHFXyxR4b7S/zTRk2mzximfNrdaaCVjt33N0QMjuu297zNgAwBHmR8MN'
    'fjA+0x4DfY9tezUgqDDEgrJV4L2Z/pretnXV1091q2D6Y6egNcq/55oF8NvXz35mQPsSrfbfcmRAiDMzeq4YsvR/rbf6OgDgDHOjYQIBoc0ugc'
    'S2VeDNbH8rTPq3dQbui9co37d2Zqzn7G1/tf+WIwOC7x+DQRRnflrvBQD8S3OjYQIBoc5fAlHTmbHt81aBl5X+1qe33uz7pqJo/XQzYYs/0/Yz'
    'BKv9M84ICL1j6/nXEfcFAC7B3GiYMFtoTO9O+9qA6p8vtloxtzvN4w1xGuC1fuusrrfNDCskem57jpHistLf1uvNINiZrdYZkS14/j4IfwxX+2'
    'ecERB0/ADgN5gbDRNWAkK8nltr8SxzJCD4a/G9Vpvmbm0zS5cH4nazBV5W+uuM2/Y/3oOgM3hfJPU8I0beb1vP3+ew2j/jyIDgt+3DGwBcq7nR'
    'MGFkwPd8OIhFTD/7a7e1Ir010Pv9UsjwxTYWydoNZL3nnpUt8C0j/XtByh+XUT50bant72r/jCMDQryvQE0BRkErPhcAXIO50TBhJiBokLU+Gm'
    'xbZ2F+MG+dTdee12+/dfa5dSOcLb/WgCC9kDATDqR33KPa/q72zzgyIIh+d/x2YtPvtI7v6L0TAPAvzI+GG2YCwsx16FjQegO9n2LvDdK9bdjy'
    'awwImiGJZ7m11gtnLb1jFtX2d7V/xtEBwbTub/FNj/V+BwHgX1sfDRtmAsLINLMVulgk9hjo/TZiobTl1xgQfDjQDIr/OJ5+9p+QGL3ZbuS41/'
    'Z3tX/GWQHBU5hVEFCQ9c9hbeVbKwHgSPuOhs5MQBgZ+FsDemt5iwqjioWuFdcG8VhIbPm1BQQ/O1O7t8L4922keI2Eu9r+rvbP+BcBIVLgjDfh'
    'xn0BgEtw2Gh4yQFBA3Rmqr02eNvyawsICj+273FWJLL1ekEiGnm/bb3f9CmGUf57H0aOMwCc5bDRcGTAN5lCZ1oDemu58Y9b0zIVG+2zCodfJx'
    'YSW35tAWHruHiZ7UUz94/4Y7jaP+OogDD79z9mjjMAnGVsRBswExBGppln7kHwX1Gs54qfgDC/MSD4Y5udQehtL1r9JsTV/hlHBYTZyzKt32EA'
    'uATjo2HSTEDIDv69TzH0QoYVga0b8Pzd57GQ2PJrCwgxHLX49230NfrjVvt7BPEjpDGorPbfclRA8OGmte+R/12Pv8MAcAnGR8OkmYCwx/cg9J'
    '43ExD8tXq1WEhs+Wjx7MkU+J5Mf39s1TQt7l+bipoPV7Vju8UfezV/Nq3A54t7LaSs9t9yVECQ+DcytH/aZ38M9R5o2epxBoAzzI2GCb1C3TPy'
    'TYq1M69aEbAB2D8WLzFo275IxG0YW35tAUFafwWy1mqvb2t2IZ7h91ot/K3231L73TC1936r+W1of7I3vvpWO44AcAnGqveA2YAg8WNgtVYLB6'
    'JBO65rd7tnBnEVCl9I4zVlW77nwJ4t8C0j/eNZeq21ju1WQBDNRGwV+d4U/Gr/niMDguj3K84k9Nro37sAgDONV++klYAgOrvXWb4vFvo5nvnX'
    'xOlo/3E4DeLatxgU4pS79Y8fpbP1WwVyxkiBrxnt3zu2seh5mYAgtWOs7St4ZM78V/u3HB0QjAJM7Ts11CyArrwOADjDXPUGAAC/GgEBAAAUCA'
    'gAAKBAQAAAAAUCAgAAKBAQAABAgYAAAAAKBAQAAFAgIAAAgAIBAQAAFAgIAACgQEAAAAAFAgIAACgQEAAAQIGAAAAACgQEAABQICAAAIACAQEA'
    'ABQICAAAoEBAAAAABQICAAAoEBAAAECBgAAAAAoEBAAAUCAgAACAwn86iOPfqPdlbwAAAABJRU5ErkJggg==')


class ScannedReceipts(Isolated):
    def test_windows_reads_a_picture(self):
        import base64
        from mailbrief.features import ocr
        path = os.path.join(config.DATA, 'scan.png')
        with open(path, 'wb') as f:
            f.write(base64.b64decode(OCR_PNG))
        text = ocr.ocr_file(path)
        if not text:
            self.skipTest('Windows text recognition is not available on this machine')
        self.assertIn('4471', text)
        self.assertIn('118.00', text)

    def test_amount_of_a_scanned_receipt(self):
        from mailbrief.money import ledger as ledger_mod
        from mailbrief.money.pdftext import total_from_text
        self.assertEqual(total_from_text('Invoice 4471\nTotal 118.00 ILS'), '₪118.00')
        self.assertEqual(total_from_text("pn n'np"), '')
        os.makedirs(os.path.join(config.RECEIPTS_DIR, '2026-09'))
        with open(os.path.join(config.RECEIPTS_DIR, '2026-09', 'scan.jpg'), 'wb') as f:
            f.write(b'fake')
        rows = {'k': {'date': '2026-09-20', 'vendor': 'Shop', 'vendor_key': 'shop.co.il', 'subject': 'קבלה', 'amount': None, 'currency': '',
                      'files': ['2026-09/scan.jpg'], 'book': 'אחר'}}
        storage.save_json(config.LEDGER_FILE, rows)
        found = {os.path.join(config.RECEIPTS_DIR, '2026-09/scan.jpg'): 'RECEIPT Total 118.00 ILS'}
        with mock.patch.object(ledger_mod, 'ocr_files', return_value=found) as read,                 mock.patch.object(ledger_mod, 'write_month_xlsx', create=True):
            result = ledger_mod.update_ledger([])
        row = result['k']
        self.assertEqual((row['amount'], row['currency'], row['amount_from']), (118.0, '₪', 'scan'))
        read.assert_called_once()

    def test_scans_are_searchable(self):
        from mailbrief.features import pdfsearch
        os.makedirs(config.RECEIPTS_DIR)
        path = os.path.join(config.RECEIPTS_DIR, 'photo.jpg')
        with open(path, 'wb') as f:
            f.write(b'fake')
        with mock.patch.object(pdfsearch, 'ocr_files', return_value={path: 'Invoice 4471 Total 118.00'}) as read:
            hits = pdfsearch.search('4471')
            pdfsearch.search('4471')
        self.assertEqual([(h['name'], h['scan']) for h in hits], [('photo.jpg', True)])
        read.assert_called_once()                                                        # read once, then from the index


def message_b64(claims):
    import base64
    import json
    return base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')


if __name__ == '__main__':
    unittest.main()
