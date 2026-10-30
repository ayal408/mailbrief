"""Mailbox landing choices without Windows dependencies or network access."""
import json
import re
import unittest
from unittest.mock import patch

from mailbrief.web import inbox


class MailboxWorkspace(unittest.TestCase):
    def boot(self, start=None, current=''):
        with patch.object(inbox.view, 'emails', return_value=['one@example.com', 'two@example.com']), \
                patch.object(inbox.view, 'current_account', return_value=current), \
                patch.object(inbox.view, 'color', return_value='#123456'), \
                patch.object(inbox.view, 'account', return_value={}), \
                patch.object(inbox, 'page', side_effect=lambda title, body, active: body), \
                patch('mailbrief.web.layout.update_banner', return_value=''):
            html = inbox.inbox_page(start)
        return json.loads(re.search(r'window.IBX=(.*?);</script>', html)[1])

    def test_default_is_a_separate_mailbox(self):
        self.assertEqual(self.boot()['account'], 'one@example.com')

    def test_explicit_account_and_unified_view_are_supported(self):
        self.assertEqual(self.boot({'a': 'TWO@example.com'})['account'], 'two@example.com')
        self.assertEqual(self.boot({'a': '*'})['account'], '*')

    def test_removed_account_cannot_be_selected(self):
        self.assertEqual(self.boot({'a': 'removed@example.com'})['account'], 'one@example.com')

    def test_deep_links_take_precedence_over_last_mailbox(self):
        self.assertTrue(self.boot({'a': 'two@example.com', 'u': '42'})['explicit_account'])
        self.assertTrue(self.boot({'f': 'Sent'})['explicit_account'])
