"""Notes are local, scoped to mailbox/sender, and reject stale edits."""
from mailbrief import config, storage
from mailbrief.features.sender_notes import get_note, save_note
from mailbrief.web.inbox import sender_profile
from tests.test_mailbrief import Isolated


class SenderNotes(Isolated):
    def setUp(self):
        super().setUp()
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'one@example.com'}, {'email': 'two@example.com'}])

    def test_notes_round_trip_without_crossing_mailboxes_or_senders(self):
        note = save_note('one@example.com', 'SENDER@example.com', 'פרטים להמשך טיפול', 0)
        self.assertEqual(note['revision'], 1)
        self.assertEqual(get_note('ONE@example.com', 'sender@example.com')['text'], 'פרטים להמשך טיפול')
        self.assertEqual(get_note('two@example.com', 'sender@example.com')['text'], '')
        self.assertEqual(get_note('one@example.com', 'other@example.com')['text'], '')
        self.assertEqual(sender_profile('one@example.com', 'sender@example.com')['note'], note)

    def test_stale_window_cannot_overwrite_a_newer_note(self):
        save_note('one@example.com', 'sender@example.com', 'ראשון', 0)
        with self.assertRaisesRegex(ValueError, 'חלון אחר'):
            save_note('one@example.com', 'sender@example.com', 'שינוי ישן', 0)
        self.assertEqual(get_note('one@example.com', 'sender@example.com')['text'], 'ראשון')
        cleared = save_note('one@example.com', 'sender@example.com', '', 1)
        self.assertEqual(cleared['text'], '')
        self.assertEqual(cleared['revision'], 2)

    def test_invalid_account_and_long_note_do_not_change_data(self):
        with self.assertRaises(LookupError):
            save_note('missing@example.com', 'sender@example.com', 'x', 0)
        with self.assertRaises(ValueError):
            save_note('one@example.com', 'sender@example.com', 'x' * 3001, 0)
        with self.assertRaises(ValueError):
            save_note('one@example.com', 'sender@example.com\nextra', 'x', 0)
        self.assertEqual(storage.load_json(config.SENDER_NOTES_FILE, {}), {})
