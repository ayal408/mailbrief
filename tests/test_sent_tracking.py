"""Sent history uses recorded evidence, never absence as a read/reply receipt."""
from unittest.mock import patch

from mailbrief import config, storage
from mailbrief.web import sent_tracking
from tests.test_mailbrief import Isolated


class SentTracking(Isolated):
    def setUp(self):
        super().setUp()
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'one@example.com'}, {'email': 'two@example.com'}])
        storage.save_json(config.OUTBOX_FILE, [
            {'id': 'a', 'message_id': '<same>', 'account': 'one@example.com', 'to': ['client@example.com'],
             'subject': 'הצעה', 'status': 'sent', 'sent': '2026-10-30T10:00:00+02:00'},
            {'id': 'b', 'message_id': '<same>', 'account': 'two@example.com', 'to': ['other@example.com'],
             'subject': 'אחר', 'status': 'partial', 'error': '<b>error</b>'}])

    def test_no_reply_is_inferred_from_missing_history(self):
        rows = sent_tracking.tracking_rows('one@example.com')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['reply'], 'unknown')
        storage.save_json(config.AUTOFOLLOW_FILE, [{'account': 'one@example.com', 'message_id': '<same>', 'status': 'waiting'}])
        self.assertEqual(sent_tracking.tracking_rows('one@example.com')[0]['reply'], 'unknown')

    def test_confirmed_reply_wins_over_older_waiting_snapshot(self):
        storage.save_json(config.AUTOFOLLOW_FILE, [{'account': 'one@example.com', 'message_id': '<same>', 'status': 'answered'}])
        storage.save_json(config.SNAPSHOT_FILE, {'awaiting': [{'account': 'one@example.com', 'message_id': '<same>', 'days': 4}]})
        rows = sent_tracking.tracking_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(next(r for r in rows if r['account'] == 'one@example.com')['reply'], 'answered')
        self.assertEqual(next(r for r in rows if r['account'] == 'two@example.com')['reply'], 'unknown')

    def test_removed_account_is_excluded_and_partial_is_never_sent(self):
        storage.save_json(config.AUTOFOLLOW_FILE, [{'account': 'removed@example.com', 'message_id': '<gone>', 'status': 'answered'}])
        rows = sent_tracking.tracking_rows('two@example.com')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['delivery'], 'partial')

    def test_filters_escape_errors_and_render_without_writing(self):
        before = storage.load_json(config.OUTBOX_FILE, [])
        with patch.object(sent_tracking, 'page', side_effect=lambda title, body, active: body):
            html = sent_tracking.tracking_page('two@example.com', 'issues')
            self.assertIn('שליחה חלקית', html)
            self.assertIn('&lt;b&gt;error&lt;/b&gt;', html)
            self.assertNotIn('client@example.com', html)
            self.assertNotIn('name="days"', html)
            html = sent_tracking.tracking_page('one@example.com', 'answered')
            self.assertIn('אין הודעות במעקב', html)
        self.assertEqual(storage.load_json(config.OUTBOX_FILE, []), before)
