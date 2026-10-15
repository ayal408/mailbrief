"""Delivery, concurrent persistence, cache identity and complete-backup regressions (offline)."""
import concurrent.futures
import datetime as dt
import multiprocessing
import os
import shutil
import smtplib
import threading
import zipfile
from unittest import mock

from mailbrief import config, storage
from mailbrief.features import maintenance, outbox
from mailbrief.mail import mailbox, smtp
from tests.test_mailbrief import Isolated
from tests.test_inbox import InboxBase, make


def increment_file(path, count):
    for _ in range(count):
        with storage.file_lock(path):
            value = storage.load_json(path, 0)
            storage.save_json(path, value + 1)


def send_in_process(data, now, log):
    def record_send(*args):
        increment_file(log, 1)
    with mock.patch.object(config, 'DATA', data), mock.patch.object(config, 'OUTBOX_FILE', os.path.join(data, 'outbox.json')), \
            mock.patch.object(outbox, 'is_holy_time', return_value=False), mock.patch.object(outbox.net, 'online', return_value=True), \
            mock.patch.object(outbox, 'after_send'), mock.patch.object(smtp, 'send_mail', side_effect=record_send):
        outbox.send_due([{'email': 'me@gmail.com', 'host': 'imap.gmail.com'}], dt.datetime.fromisoformat(now))


class Persistence(Isolated):
    def test_threads_do_not_collide_on_temporary_files(self):
        path = os.path.join(config.DATA, 'concurrent.json')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: increment_file(path, 15), range(8)))
        self.assertEqual(storage.load_json(path, 0), 120)
        self.assertFalse(any(n.endswith('.tmp') for n in os.listdir(config.DATA)))

    def test_processes_share_the_transaction_lock(self):
        path = os.path.join(config.DATA, 'processes.json')
        ctx = multiprocessing.get_context('spawn')
        workers = [ctx.Process(target=increment_file, args=(path, 10)) for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(20)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(storage.load_json(path, 0), 30)


class Delivery(Isolated):
    def setUp(self):
        super().setUp()
        self.now = dt.datetime(2026, 10, 15, 14, 25, 35, 654321, tzinfo=dt.timezone.utc)
        self.acc = {'email': 'me@gmail.com', 'host': 'imap.gmail.com'}
        self.enterContext(mock.patch.object(outbox, 'is_holy_time', return_value=False))
        self.enterContext(mock.patch.object(outbox, 'holy_windows', return_value=[]))
        self.enterContext(mock.patch.object(outbox.net, 'online', return_value=True))
        self.enterContext(mock.patch.object(outbox, 'after_send'))

    def queue(self, **kwargs):
        return outbox.schedule(self.acc['email'], 'one@example.com', 'subject', 'body', self.now, **kwargs)

    def test_undo_deadline_keeps_seconds_in_schedule_and_update(self):
        deadline = self.now + dt.timedelta(seconds=10)
        item = outbox.schedule(self.acc['email'], 'one@example.com', 's', 'b', deadline)
        with mock.patch.object(smtp, 'send_mail') as send:
            self.assertEqual(outbox.send_due([self.acc], self.now), 0)
            send.assert_not_called()
            outbox.update(item['id'], send_at=deadline + dt.timedelta(seconds=10))
            self.assertEqual(outbox.send_due([self.acc], deadline), 0)
            self.assertEqual(outbox.send_due([self.acc], deadline + dt.timedelta(seconds=10)), 1)

    def test_two_senders_send_once_and_preserve_concurrent_queue_changes(self):
        original = self.queue()
        cancel_me = self.queue()
        inside, release = threading.Event(), threading.Event()

        def send(*args):
            self.assertEqual(outbox.outbox()[0]['status'], 'sending')
            inside.set()
            self.assertTrue(release.wait(5))

        with mock.patch.object(smtp, 'send_mail', side_effect=send) as sent:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(outbox.send_due, [self.acc], self.now)
                self.assertTrue(inside.wait(5))
                try:
                    second = pool.submit(outbox.send_due, [self.acc], self.now)
                    future = self.now + dt.timedelta(days=1)
                    added = outbox.schedule(self.acc['email'], 'new@example.com', 'new', 'new', future)
                    outbox.cancel(cancel_me['id'])
                    with self.assertRaises(ValueError):
                        outbox.cancel(original['id'])
                finally:
                    release.set()
                self.assertEqual(first.result(10) + second.result(10), 1)
            self.assertEqual(sent.call_count, 1)
        states = {m['id']: m['status'] for m in outbox.outbox()}
        self.assertEqual(states, {original['id']: 'sent', cancel_me['id']: 'cancelled', added['id']: 'waiting'})

    def test_desktop_and_scheduled_process_send_once(self):
        self.queue()
        log = os.path.join(config.DATA, 'smtp-count.json')
        ctx = multiprocessing.get_context('spawn')
        workers = [ctx.Process(target=send_in_process, args=(config.DATA, self.now.isoformat(), log)) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(20)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(storage.load_json(log, 0), 1)
        self.assertEqual(outbox.outbox()[0]['status'], 'sent')

    def test_interrupted_claim_is_not_resent(self):
        item = self.queue()
        item['status'] = 'sending'
        storage.save_json(config.OUTBOX_FILE, [item])
        with mock.patch.object(smtp, 'send_mail') as send:
            self.assertEqual(outbox.send_due([self.acc], self.now), 0)
            send.assert_not_called()
        self.assertEqual(outbox.outbox()[0]['status'], 'uncertain')

    def test_partial_delivery_is_reported_per_recipient_and_not_retried(self):
        item = self.queue(cc='two@example.com', bcc='three@example.com')
        exc = smtp.PartialDelivery({'two@example.com': (550, b'no such user')},
                                   ['one@example.com', 'two@example.com', 'three@example.com'])
        with mock.patch.object(smtp, 'send_mail', side_effect=exc) as send:
            self.assertEqual(outbox.send_due([self.acc], self.now), 0)
            outbox.send_due([self.acc], self.now)
            self.assertEqual(send.call_count, 1)
        saved = next(m for m in outbox.outbox() if m['id'] == item['id'])
        self.assertEqual(saved['status'], 'partial')
        self.assertEqual(saved['accepted'], ['one@example.com', 'three@example.com'])
        self.assertEqual(saved['refused']['two@example.com']['code'], 550)

    def test_uncertain_delivery_is_not_retried(self):
        self.queue()
        with mock.patch.object(smtp, 'send_mail', side_effect=smtp.DeliveryUncertain('check sent')) as send:
            outbox.send_due([self.acc], self.now)
            outbox.send_due([self.acc], self.now)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(outbox.outbox()[0]['status'], 'uncertain')

    def test_refused_recipients_are_failed_not_retried_as_network_errors(self):
        self.queue()
        with mock.patch.object(smtp, 'send_mail', side_effect=smtplib.SMTPRecipientsRefused({'one@example.com': (550, b'no')})):
            outbox.send_due([self.acc], self.now)
        self.assertEqual(outbox.outbox()[0]['status'], 'failed')

    def test_bookkeeping_failure_does_not_change_delivery_result(self):
        self.queue(follow={'days': 3})
        with mock.patch.object(smtp, 'send_mail') as send, mock.patch('mailbrief.features.autofollow.register', side_effect=OSError('disk full')), \
                mock.patch('mailbrief.features.diag.log_error'):
            self.assertEqual(outbox.send_due([self.acc], self.now), 1)
            self.assertEqual(outbox.send_due([self.acc], self.now), 0)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(outbox.outbox()[0]['status'], 'sent')

    def test_plain_text_edit_updates_html_alternative(self):
        item = self.queue(html='<b>old body</b>')
        updated = outbox.update(item['id'], body='correct body')
        msg = outbox.build(updated, self.acc)
        self.assertIn('correct body', msg.get_body(('html',)).get_content())
        self.assertNotIn('old body', msg.as_string())

    def test_smtp_detects_partial_acceptance_and_ambiguous_disconnect(self):
        msg = outbox.build(self.queue(cc='two@example.com'), self.acc)
        acc = dict(self.acc, user=self.acc['email'], password='encrypted')
        server = mock.Mock()
        with mock.patch.object(smtp.smtplib, 'SMTP_SSL', return_value=server), mock.patch.object(smtp, 'decrypt', return_value='password'):
            server.send_message.return_value = {'two@example.com': (550, b'unknown')}
            with self.assertRaises(smtp.PartialDelivery) as raised:
                smtp.send_mail(acc, msg)
            self.assertEqual(raised.exception.accepted, ['one@example.com'])
            server.send_message.side_effect = smtplib.SMTPServerDisconnected('lost')
            with self.assertRaises(smtp.DeliveryUncertain):
                smtp.send_mail(acc, msg)
            server.quit.assert_called()


class CacheAndDeletion(InboxBase):
    def test_reused_uid_reads_new_body_after_validity_change(self):
        old = mailbox.fetch_raw('me@gmail.com', 'INBOX', 1, mark_seen=False)
        replacement = make(1, 'New <new@example.com>', 'replacement', 'new content')
        self.boxes['INBOX'][0] = replacement
        response = self.fake.response
        with mock.patch.object(self.fake, 'response', side_effect=lambda code: (code, [b'8']) if code == 'UIDVALIDITY' else response(code)):
            self.assertNotEqual(mailbox.fetch_raw('me@gmail.com', 'INBOX', 1, mark_seen=False), old)
        self.assertEqual(mailbox._cached_body('me@gmail.com', 'INBOX', 1), replacement['raw'])

    def test_offline_body_remains_available(self):
        raw = mailbox.fetch_raw('me@gmail.com', 'INBOX', 1, mark_seen=False)
        mailbox.drop('test0001')
        with mock.patch('mailbrief.mail.imap.connect', side_effect=OSError('offline')):
            self.assertEqual(mailbox.fetch_raw('me@gmail.com', 'INBOX', 1, mark_seen=False), raw)

    def test_no_global_expunge_without_uidplus(self):
        self.fake.capabilities = ('IMAP4REV1',)
        self.boxes['INBOX'][1]['flags'].add('\\Deleted')
        with mock.patch.object(self.fake, 'expunge') as expunge:
            for operation in (lambda: mailbox.delete_for_good('me@gmail.com', 'INBOX', [1]),
                              lambda: mailbox.move('me@gmail.com', 'INBOX', [1], '[Gmail]/Trash')):
                with self.assertRaisesRegex(RuntimeError, 'UIDPLUS'):
                    operation()
            expunge.assert_not_called()
        self.assertEqual([m['uid'] for m in self.boxes['INBOX']], [1, 2, 3])
        self.assertNotIn('\\Deleted', self.boxes['INBOX'][0]['flags'])


class CompleteBackups(Isolated):
    def test_backup_restores_attachments_and_signature_and_can_build_mail(self):
        item = outbox.schedule('me@gmail.com', 'one@example.com', 's', 'b', dt.datetime.now().astimezone(),
                               files=[('receipt.pdf', b'%PDF receipt')])
        acc = {'id': 'abcdef12', 'email': 'me@gmail.com', 'signature_logo': 'png'}
        logo = outbox.logo_path(acc)
        os.makedirs(os.path.dirname(logo), exist_ok=True)
        with open(logo, 'wb') as f:
            f.write(b'logo')
        backup = maintenance.make_backup('test')
        with zipfile.ZipFile(backup) as z:
            self.assertIn(f'outbox-files/{item["id"]}/receipt.pdf', z.namelist())
            self.assertIn('signatures/abcdef12.img', z.namelist())
        shutil.rmtree(os.path.join(config.DATA, 'outbox-files'))
        shutil.rmtree(os.path.dirname(logo))
        maintenance.restore_backup(os.path.basename(backup))
        msg = outbox.build(outbox.outbox()[0], acc)
        self.assertEqual(next(msg.iter_attachments()).get_payload(decode=True), b'%PDF receipt')
        with open(logo, 'rb') as f:
            self.assertEqual(f.read(), b'logo')

    def test_invalid_archive_changes_nothing(self):
        backup = maintenance.make_backup('test')
        before = storage.load_json(config.ACCOUNTS_FILE, [])
        with zipfile.ZipFile(backup, 'w') as z:
            z.writestr('accounts.json', '[]')
            z.writestr('outbox-files/../../outside', b'bad')
        with self.assertRaises(RuntimeError):
            maintenance.restore_backup(os.path.basename(backup))
        self.assertEqual(storage.load_json(config.ACCOUNTS_FILE, []), before)

    def test_corrupt_json_is_validated_before_restore(self):
        backup = maintenance.make_backup('test')
        before = storage.load_json(config.ACCOUNTS_FILE, [])
        with zipfile.ZipFile(backup, 'w') as z:
            z.writestr('accounts.json', '[]')
            z.writestr('settings.json', '{broken')
        with self.assertRaises(ValueError):
            maintenance.restore_backup(os.path.basename(backup))
        self.assertEqual(storage.load_json(config.ACCOUNTS_FILE, []), before)
