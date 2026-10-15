"""Offline regressions for drafts, failed workflows, reminder control and fast rendering."""
import datetime as dt
import threading
import time
from email.message import EmailMessage
from unittest import mock

from mailbrief import background, config, net, storage
from mailbrief.features import automations, autofollow, drafts, google_apps, notify, outbox, reminders, toast_actions
from mailbrief.mail import mailbox, smtp
from mailbrief.web import inbox
from tests.test_mailbrief import Isolated

_SUBMIT = background.submit


def draft_message():
    message = EmailMessage()
    message['To'] = 'Dana Levi <dana@example.com>'
    message['Subject'] = 'Proposal'
    message['In-Reply-To'] = '<original@example.com>'
    message['References'] = '<root@example.com> <original@example.com>'
    message.set_content('Proposal')
    message.add_alternative('<b>Proposal</b>', subtype='html')
    message.add_attachment(b'%PDF receipt', maintype='application', subtype='pdf', filename='receipt.pdf')
    return message


class DraftIntegrity(Isolated):
    def setUp(self):
        super().setUp()
        self.acc = {'email': 'me@gmail.com', 'signature': 'My signature'}
        self.form = {'a': self.acc['email'], 'to': 'Dana Levi <dana@example.com>', 'subject': 'Proposal',
                     'body': 'Proposal', 'html': '<b>Proposal</b>', 'mode': 'new', '_files': [('receipt.pdf', b'%PDF receipt')]}
        self.enterContext(mock.patch.object(mailbox, 'account', return_value=self.acc))
        self.saved = self.enterContext(mock.patch.object(mailbox, 'save_draft', return_value=('Drafts', 42)))
        self.deleted = self.enterContext(mock.patch.object(mailbox, 'delete_for_good'))

    def test_uploaded_files_survive_repeated_draft_saves_without_duplicates(self):
        result = drafts.save(self.form)
        first = self.saved.call_args.args[1]
        self.assertEqual([p.get_filename() for p in first.iter_attachments()], ['receipt.pdf'])
        self.assertNotIn('My signature', first.as_string())
        form = dict(self.form, draft_a=self.acc['email'], draft_f=result['folder'], draft_u=str(result['uid']))
        with mock.patch.object(mailbox, 'fetch_raw', return_value=first.as_bytes()):
            drafts.save(form)
        second = self.saved.call_args.args[1]
        self.assertEqual([p.get_filename() for p in second.iter_attachments()], ['receipt.pdf'])
        self.assertEqual(second.get_body(('html',)).get_content(), first.get_body(('html',)).get_content())

    def test_account_switch_never_replaces_another_accounts_uid(self):
        form = dict(self.form, a='other@example.com', mode='edit', draft_a='original@example.com', draft_f='OldDrafts', draft_u='7')
        with mock.patch.object(mailbox, 'fetch_raw', return_value=draft_message().as_bytes()), \
                mock.patch.object(mailbox, 'account', return_value={'email': 'other@example.com'}):
            result = drafts.save(form)
        self.assertEqual(result['account'], 'other@example.com')
        self.assertIsNone(self.saved.call_args.args[2])
        self.deleted.assert_called_once_with('original@example.com', 'OldDrafts', [7])

    def test_original_folder_is_used_when_deleting_replaced_draft(self):
        form = dict(self.form, mode='edit', draft_a='me@gmail.com', draft_f='CustomDrafts', draft_u='7')
        with mock.patch.object(mailbox, 'fetch_raw', return_value=draft_message().as_bytes()):
            drafts.save(form)
        self.assertIsNone(self.saved.call_args.args[2])
        self.deleted.assert_called_once_with('me@gmail.com', 'CustomDrafts', [7])

    def test_old_draft_deletion_failure_does_not_hide_successful_save(self):
        form = dict(self.form, mode='edit', draft_a='me@gmail.com', draft_f='Drafts', draft_u='7')
        with mock.patch.object(mailbox, 'fetch_raw', return_value=draft_message().as_bytes()), \
                mock.patch.object(mailbox, 'delete_for_good', side_effect=RuntimeError('no UIDPLUS')):
            result = drafts.save(form)
        self.assertEqual(result['uid'], 42)
        self.assertIn('warning', result)

    def test_failed_copy_keeps_original_draft(self):
        form = dict(self.form, mode='edit', draft_a='original@example.com', draft_f='Drafts', draft_u='7')
        with mock.patch.object(mailbox, 'fetch_raw', return_value=draft_message().as_bytes()), \
                mock.patch.object(mailbox, 'save_draft', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                drafts.save(form)
        self.deleted.assert_not_called()

    def test_reopen_preserves_html_attachments_and_thread_on_send(self):
        message = draft_message()
        with mock.patch.object(mailbox, 'fetch_raw', return_value=message.as_bytes()), \
                mock.patch.object(mailbox, 'accounts', return_value=[self.acc]):
            fields = inbox.compose_data('edit', self.acc['email'], 'Drafts', 9)
            self.assertEqual(fields['to'], 'dana@example.com')
            self.assertIn('<b>Proposal</b>', fields['html'])
            self.assertEqual(fields['files'], ['receipt.pdf'])
            form = dict(self.form, mode='edit', draft_a=self.acc['email'], draft_f='Drafts', draft_u='9', html=fields['html'])
            extra = drafts.message_fields(form)
            with mock.patch.object(outbox, 'holy_windows', return_value=[]):
                item = outbox.schedule(self.acc['email'], fields['to'], fields['subject'], fields['body'],
                                       dt.datetime.now().astimezone(), html=fields['html'], **extra)
            result = outbox.build(item, self.acc)
        self.assertEqual(result['In-Reply-To'], message['In-Reply-To'])
        self.assertEqual(result['References'], message['References'])
        self.assertEqual([p.get_filename() for p in result.iter_attachments()], ['receipt.pdf'])
        self.assertIn('<b>Proposal</b>', result.get_body(('html',)).get_content())

    def test_named_recipients_are_accepted_in_to_cc_and_bcc(self):
        now = dt.datetime.now().astimezone()
        item = outbox.schedule('me@gmail.com', '"Dana, Levi" <dana@example.com>', 's', 'b', now,
                               cc='Yossi <yossi@example.com>', bcc='secret@example.com')
        self.assertEqual(item['to'], ['dana@example.com'])
        self.assertEqual(item['cc'], ['yossi@example.com'])
        self.assertEqual(item['bcc'], ['secret@example.com'])

    def test_sent_draft_is_removed_from_its_original_account(self):
        message = outbox.build({'to': ['x@example.com'], 'subject': 's', 'body': 'b'}, self.acc)
        with mock.patch.object(mailbox, 'keeps_sent_copy', return_value=True), mock.patch('mailbrief.features.live.bump'):
            outbox.after_send(self.acc, {'draft': {'account': 'original@example.com', 'folder': 'Drafts', 'uid': 4}}, message)
        self.deleted.assert_called_once_with('original@example.com', 'Drafts', [4])


class RetryIntegrity(Isolated):
    def test_failed_action_retries_without_repeating_successful_action(self):
        wf = {'id': 'wf', 'name': 'test', 'trigger': 'new_mail', 'actions': [{'type': 'webhook'}, {'type': 'email_me'}]}
        state, calls = {}, []
        def action(a, *args):
            calls.append(a['type'])
            return '⚠️ offline' if a['type'] == 'email_me' and calls.count('email_me') == 1 else '✓ done'
        with mock.patch.object(automations, 'workflows', return_value=[wf]), mock.patch.object(automations, 'workflows_need_write', return_value=False), \
                mock.patch.object(automations, 'matches', return_value=True), mock.patch.object(automations, 'wf_context', return_value={}), \
                mock.patch.object(automations, 'item_key', return_value='mail'), mock.patch.object(automations, 'log_run'), \
                mock.patch.object(automations, 'run_action', side_effect=action):
            for _ in range(3):
                automations.run_workflows(None, {'email': 'me@example.com'}, [({'subject': 's'}, EmailMessage())], state, {}, [10])
        self.assertEqual(calls, ['webhook', 'email_me', 'email_me'])
        self.assertEqual(state['_wf_done'], ['wf|mail'])

    def test_scheduled_action_failure_is_not_marked_completed(self):
        wf = {'id': 'wf', 'name': 'test', 'trigger': 'schedule', 'schedule': {'days': list(range(7)), 'hour': 0},
              'actions': [{'type': 'email_me'}]}
        state = {}
        with mock.patch.object(automations, 'workflows', return_value=[wf]), mock.patch.object(automations, 'schedule_context', return_value={}), \
                mock.patch.object(automations, 'log_run'), mock.patch.object(automations, 'run_action', side_effect=['⚠️ offline', '✓ done']) as action:
            automations.run_schedule_workflows(state, [{'email': 'me@example.com'}])
            self.assertNotIn('wf', state['_wf_sched'])
            automations.run_schedule_workflows(state, [{'email': 'me@example.com'}])
            self.assertIn('wf', state['_wf_sched'])
            self.assertEqual(action.call_count, 2)

    def test_uncertain_delivery_is_terminal_for_workflow_retries(self):
        with mock.patch.object(smtp, 'send_mail', side_effect=smtp.DeliveryUncertain('check sent')):
            result = automations.run_action({'type': 'email_me', 'param': 'hello'}, {'name': 'test'},
                                            {'email': 'me@example.com'}, {})
        self.assertTrue(result.startswith('⛔'))

    def test_search_failure_keeps_followup_waiting_without_sending(self):
        now = dt.datetime.now().astimezone()
        row = {'id': 'f', 'account': 'me@example.com', 'to': ['client@example.com'], 'subject': 's',
               'message_id': '<m@example.com>', 'due': (now - dt.timedelta(days=1)).isoformat(), 'text': 'reminder', 'status': 'waiting'}
        storage.save_json(config.AUTOFOLLOW_FILE, [row])
        conn = mock.Mock(); conn.uid.return_value = ('NO', [b'try later'])
        with mock.patch('mailbrief.mail.imap.connect', return_value=conn), mock.patch('mailbrief.mail.imap.special_folder', return_value='INBOX'), \
                mock.patch('mailbrief.net.online', return_value=True), mock.patch.object(outbox, 'schedule') as schedule:
            self.assertEqual(autofollow.check_due(now, [{'email': 'me@example.com'}]), 0)
            schedule.assert_not_called()
        self.assertEqual(autofollow.items()[0]['status'], 'waiting')


class ReminderControl(Isolated):
    def test_automatic_reminders_require_opt_in(self):
        self.assertIsNone(reminders.add_reminder(1, 'automatic', 'A', '', 'me@example.com', source='promise'))
        self.assertIsNotNone(reminders.add_reminder(1, 'explicit', 'A', '', 'me@example.com'))
        storage.save_json(config.SETTINGS_FILE, {'auto_reminders': True})
        self.assertIsNotNone(reminders.add_reminder(1, 'automatic', 'A', '', 'me@example.com', source='promise'))

    def test_dismissed_reminder_is_not_recreated_automatically(self):
        storage.save_json(config.SETTINGS_FILE, {'auto_reminders': True})
        reminders.add_reminder(1, 's', 'A', '', 'me@example.com', source='meeting')
        item = storage.load_json(config.REMINDERS_FILE, [])[0]
        reminders.remove(item['id'])
        self.assertIsNone(reminders.add_reminder(1, 's', 'A', '', 'me@example.com', source='meeting'))
        self.assertEqual(storage.load_json(config.REMINDERS_FILE, []), [])
        self.assertIsNotNone(reminders.add_reminder(1, 's', 'A', '', 'me@example.com'))

    def test_disabled_notifications_do_no_network_or_process_work(self):
        storage.save_json(config.SETTINGS_FILE, {'notifications_enabled': False})
        with mock.patch.object(notify, 'is_holy_time') as holy, mock.patch.object(notify.subprocess, 'Popen') as launch:
            self.assertFalse(notify.toast('x', ['y'], vip=True))
            holy.assert_not_called(); launch.assert_not_called()

    def test_disabled_reminders_stay_available_without_notifications(self):
        reminders.add_reminder(0, 's', 'A', '', 'me@example.com')
        storage.save_json(config.SETTINGS_FILE, {'reminders_enabled': False})
        with mock.patch.object(notify, 'toast') as toast:
            self.assertEqual(reminders.fire_reminders(), 0)
            toast.assert_not_called()
        self.assertEqual(len(storage.load_json(config.REMINDERS_FILE, [])), 1)

    def test_due_reminders_are_grouped_and_not_repeated(self):
        for subject in ('first', 'second', 'third'):
            reminders.add_reminder(0, subject, 'A', '', 'me@example.com')
        with mock.patch.object(notify, 'toast', return_value=True) as toast:
            self.assertEqual(reminders.fire_reminders(), 3)
            self.assertEqual(reminders.fire_reminders(), 0)
            self.assertEqual(toast.call_count, 1)
        self.assertEqual(len(storage.load_json(config.REMINDERS_FILE, [])), 3)  # can still be dismissed in My day
        reminders.clear()
        self.assertEqual(storage.load_json(config.REMINDERS_FILE, []), [])

    def test_legacy_automatic_reminder_is_silent_without_opt_in(self):
        storage.save_json(config.REMINDERS_FILE, [{'id': 'legacy', 'subject': '🤝 הבטחת לדנה: אשלח מחר',
                          'from': 'דנה', 'account': 'me@example.com', 'due': dt.datetime.now().astimezone().isoformat()}])
        with mock.patch.object(notify, 'toast') as toast:
            self.assertEqual(reminders.fire_reminders(), 0)
            toast.assert_not_called()

    def test_every_reminder_is_accessible_with_pagination(self):
        from mailbrief.web.reminders import reminders_page
        now = dt.datetime.now().astimezone().isoformat()
        storage.save_json(config.REMINDERS_FILE, [{'id': str(i), 'subject': 'item ' + str(i), 'from': 'A',
                          'account': 'me@gmail.com', 'due': now} for i in range(55)])
        html = reminders_page()
        self.assertEqual(html.count('action="/reminder_delete"'), 50)
        self.assertIn('/reminders?p=1', html)
        self.assertEqual(reminders_page(1).count('action="/reminder_delete"'), 5)

    def test_signed_notification_has_a_dismiss_action(self):
        buttons = toast_actions.buttons({'subject': 's', 'account': 'me@example.com'})
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(buttons[-1][1]).query)
        result = toast_actions.act(query['id'][0], 'dismiss', query['sig'][0])
        self.assertIsInstance(result, str)
        self.assertTrue(reminders.unwanted('s', 'me@example.com'))


class FastPages(Isolated):
    def test_background_request_returns_immediately_and_deduplicates(self):
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            release.wait(5)
            completed.set()
        with mock.patch.object(background, 'submit', _SUBMIT), mock.patch.object(net, 'cached_json', side_effect=slow) as fetch:
            started = time.monotonic()
            try:
                self.assertIsNone(net.background_json('slow-test', 'https://example.com/data', 5))
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertTrue(entered.wait(2))
                for _ in range(10):
                    net.background_json('slow-test', 'https://example.com/data', 5)
                self.assertEqual(fetch.call_count, 1)
            finally:
                release.set()
                self.assertTrue(completed.wait(2))

    def test_today_renders_without_network_git_or_google_requests(self):
        from mailbrief.web import today
        with mock.patch.object(background, 'submit'), mock.patch.object(net.urllib.request, 'urlopen') as request, \
                mock.patch.object(google_apps, 'events_on') as events, mock.patch('mailbrief.features.today.subprocess.run') as git:
            started = time.monotonic()
            html = today.today_page()
            self.assertLess(time.monotonic() - started, 1)
            request.assert_not_called(); events.assert_not_called(); git.assert_not_called()
        self.assertIn('today_widgets.json', html)
        self.assertIn('הגדרות וכיבוי תזכורות', html)
