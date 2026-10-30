"""Profiles use saved correspondence and keep mailbox histories separate."""
from mailbrief import config, storage
from mailbrief.web.inbox import sender_profile
from tests.test_mailbrief import Isolated


class SenderProfiles(Isolated):
    def setUp(self):
        super().setUp()
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'one@example.com'}, {'email': 'two@example.com'}])
        storage.save_json(config.HISTORY_FILE, {
            'one': {'account': 'one@example.com', 'sender': 'sender@example.com', 'name': 'Dana', 'date': '2026-10-29', 'subject': 'One', 'answered': False, 'link': 'javascript:bad'},
            'two': {'account': 'two@example.com', 'sender': 'sender@example.com', 'name': 'Different', 'date': '2026-10-30', 'subject': 'Private'},
            'legacy': {'sender': 'sender@example.com', 'date': '2026-10-28', 'subject': 'Unknown account'}})

    def test_history_is_scoped_and_untrusted_links_are_removed(self):
        p = sender_profile('one@example.com', 'SENDER@example.com')
        self.assertEqual((p['count'], p['name'], p['waiting']), (1, 'Dana', 1))
        self.assertEqual(p['recent'], [{'subject': 'One', 'date': '2026-10-29', 'link': ''}])
        self.assertEqual(p['photo'], '')

    def test_new_sender_has_no_invented_history(self):
        p = sender_profile('two@example.com', 'new@example.com')
        self.assertEqual((p['count'], p['waiting'], p['recent']), (0, 0, []))
        self.assertEqual(p['last'], '')

    def test_contact_details_and_local_photo_only(self):
        storage.save_json(config.CONTACTS_FILE, {'sender@example.com': {'name': 'Saved name', 'phone': '0501234567'}})
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'one@example.com'}, {'email': 'sender@example.com', 'avatar': 'photo.png'}])
        p = sender_profile('one@example.com', 'sender@example.com')
        self.assertEqual((p['name'], p['phone'], p['photo']), ('Saved name', '0501234567', '/avatar/photo.png'))
        storage.save_json(config.ACCOUNTS_FILE, [{'email': 'one@example.com'}, {'email': 'sender@example.com', 'avatar': 'https://tracker.example/pixel'}])
        self.assertEqual(sender_profile('one@example.com', 'sender@example.com')['photo'], '')

    def test_unknown_mailbox_and_invalid_sender_are_rejected(self):
        with self.assertRaises(LookupError):
            sender_profile('missing@example.com', 'sender@example.com')
        with self.assertRaises(ValueError):
            sender_profile('one@example.com', '')
