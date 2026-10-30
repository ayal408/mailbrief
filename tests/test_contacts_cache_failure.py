import sqlite3
from unittest import mock
from tests.test_mailbrief import Isolated
from mailbrief.web import contacts

class ContactCacheFailure(Isolated):
    def test_unavailable_cache_keeps_manual_contacts(self):
        from mailbrief import config, storage
        storage.save_json(config.CONTACTS_FILE, {'friend@example.com': {'phone': '0501234567'}})
        with mock.patch.object(contacts.os.path, 'isfile', return_value=True), mock.patch.object(contacts.sqlite3, 'connect', side_effect=sqlite3.OperationalError('locked')):
            rows = contacts.people()
        self.assertEqual(rows[0]['email'], 'friend@example.com')
        self.assertEqual(rows[0]['phone'], '0501234567')
