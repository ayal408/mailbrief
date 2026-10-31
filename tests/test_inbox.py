"""📥 The inbox: a fake IMAP server in memory, the real MailBrief web server on a free port — nothing touches real mail."""
import email
import http.client
import json
import re
import socket
import threading
import unittest
from email.message import EmailMessage
from email.policy import default as default_policy
from unittest import mock
from urllib.parse import urlencode

from mailbrief import config, storage
from tests.test_mailbrief import Isolated


def make(uid, frm, subject, body, html=None, flags=(), msgid=None, refs='', attach=None, cid_png=False, date='Thu, 08 Oct 2026 09:15:00 +0300'):
    m = EmailMessage()
    m['From'], m['To'], m['Subject'], m['Date'] = frm, 'me@gmail.com', subject, date
    m['Message-ID'] = msgid or f'<m{uid}@example.com>'
    if refs:
        m['In-Reply-To'] = refs.split()[-1]
        m['References'] = refs
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype='html')
        if cid_png:
            m.get_payload()[-1].add_related(b'\x89PNG fake', maintype='image', subtype='png', cid='<logo1>')
    if attach:
        m.add_attachment(attach[1], maintype='application', subtype='pdf', filename=attach[0])
    return {'uid': uid, 'raw': m.as_bytes(), 'flags': set(flags)}


class FakeIMAP:
    """Just enough of a Gmail IMAP server for the inbox."""
    capabilities = ('IMAP4REV1', 'MOVE', 'UIDPLUS')

    def __init__(self, boxes):
        self.boxes, self.current, self.literal = boxes, None, None

    def _q(self, name):
        return name[1:-1].replace('\\"', '"').replace('\\\\', '\\') if name.startswith('"') else name

    def noop(self):
        return 'OK', [b'']

    def logout(self):
        return 'BYE', [b'']

    def select(self, name, readonly=False):
        name = self._q(name)
        if name not in self.boxes:
            return 'NO', [b'no such folder']
        self.current = name
        return 'OK', [str(len(self.boxes[name])).encode()]

    def response(self, code):
        if code == 'COPYUID':                                # UIDPLUS: told once, after a MOVE
            said, self.copyuid = getattr(self, 'copyuid', None), None
            return code, [said]
        return code, [b'7']

    def expunge(self):
        self.boxes[self.current] = [m for m in self.boxes[self.current] if '\\Deleted' not in m['flags']]
        return 'OK', [b'']

    def list(self, *args):
        rows = {'INBOX': '\\HasNoChildren', '[Gmail]/All Mail': '\\All', '[Gmail]/Sent Mail': '\\Sent', '[Gmail]/Trash': '\\Trash',
                '[Gmail]/Drafts': '\\Drafts', '[Gmail]/Spam': '\\Junk', '&BdcF6QXRBdUF3w-': '\\HasNoChildren'}
        rows.update({n: '\\HasNoChildren' for n in self.boxes if n not in rows})
        return 'OK', [b'(\\HasChildren \\Noselect) "/" "[Gmail]"'] + [f'({f}) "/" "{n}"'.encode() for n, f in rows.items() if n in self.boxes]

    def create(self, name):
        name = self._q(name)
        if name in self.boxes:
            return 'NO', [b'exists']
        self.boxes[name] = []
        return 'OK', [b'']

    def rename(self, old, new):
        self.boxes[self._q(new)] = self.boxes.pop(self._q(old))
        return 'OK', [b'']

    def delete(self, name):
        self.boxes.pop(self._q(name))
        return 'OK', [b'']

    def status(self, name, what):
        unseen = sum(1 for m in self.boxes[self._q(name)] if '\\Seen' not in m['flags'])
        return 'OK', [f'{name} (UNSEEN {unseen})'.encode()]

    def append(self, name, flags, when, raw):
        box = self.boxes[self._q(name)]
        uid = max([m['uid'] for m in box] + [0]) + 1
        box.append({'uid': uid, 'raw': raw, 'flags': set(re.findall(r'\\\w+', flags))})
        return 'OK', [f'[APPENDUID 7 {uid}] done'.encode()]

    def _pick(self, ids):
        wanted = {int(x) for x in ids.decode().split(',')}
        return [m for m in self.boxes[self.current] if m['uid'] in wanted]

    def uid(self, cmd, *args):
        box = self.boxes[self.current]
        if cmd == 'SEARCH':
            hits = box
            if 'UNSEEN' in args:
                hits = [m for m in hits if '\\Seen' not in m['flags']]
            if 'HEADER' in args:
                header, value = args[args.index('HEADER') + 1], self._q(args[args.index('HEADER') + 2])
                assert ' ' not in value or args[args.index('HEADER') + 2].startswith('"'), 'unquoted search value'
                hits = [m for m in hits if value in str(email.message_from_bytes(m['raw']).get(header) or '')]
            if args and args[-1] in ('X-GM-RAW', 'TEXT'):
                word = self.literal.decode()
                text = lambda m: email.message_from_bytes(m['raw'], policy=default_policy).get_body(('plain',)).get_content()
                hits = [m for m in hits if word.lower() in text(m).lower()]
            return 'OK', [' '.join(str(m['uid']) for m in hits).encode()]
        if cmd == 'FETCH':
            out = []
            for m in self._pick(args[0]):
                raw, what = m['raw'], args[1]
                head, _, text = raw.partition(b'\n\n')
                if 'BODY' not in what:
                    out.append(f'{m["uid"]} (UID {m["uid"]} INTERNALDATE "08-Oct-2026 09:15:00 +0300")'.encode())
                    continue
                if 'HEADER.FIELDS' in what:
                    lit = head + b'\r\n\r\n'
                    meta = f'{m["uid"]} (UID {m["uid"]} FLAGS ({" ".join(sorted(m["flags"]))}) INTERNALDATE "08-Oct-2026 09:15:00 +0300" RFC822.SIZE {len(raw)} X-GM-THRID 5{m["uid"]} X-GM-MSGID 9{m["uid"]} BODY[HEADER.FIELDS (FROM)] {{{len(lit)}}}'
                elif 'TEXT' in what:
                    lit = text[:3072]
                    meta = f'{m["uid"]} (UID {m["uid"]} BODY[TEXT]<0> {{{len(lit)}}}'
                else:
                    lit = raw
                    if 'PEEK' not in what:
                        m['flags'].add('\\Seen')
                    meta = f'{m["uid"]} (UID {m["uid"]} BODY[] {{{len(lit)}}}'
                out += [(meta.encode(), lit), b')']
            return 'OK', out
        if cmd == 'STORE':
            for m in self._pick(args[0]):
                flags = set(re.findall(r'\\\w+', args[2]))
                m['flags'] = m['flags'] | flags if args[1].startswith('+') else m['flags'] - flags
            return 'OK', [b'']
        if cmd == 'MOVE':
            moving = self._pick(args[0])
            self.boxes[self.current] = [m for m in box if m not in moving]
            target = self.boxes[self._q(args[1])]
            old, new = [], []
            for m in moving:                                 # a new UID there when the old one is taken, like a real server
                taken = {x['uid'] for x in target}
                old.append(m['uid'])
                m = dict(m, uid=m['uid'] if m['uid'] not in taken else max(taken) + 1)
                new.append(m['uid'])
                target.append(m)
            self.copyuid = f'7 {",".join(map(str, old))} {",".join(map(str, new))}'.encode()
            return 'OK', [b'']
        if cmd == 'EXPUNGE':
            self.boxes[self.current] = [m for m in box if '\\Deleted' not in m['flags']]
            return 'OK', [b'']
        raise AssertionError(cmd)


class InboxBase(Isolated):
    def setUp(self):
        super().setUp()
        from mailbrief.mail import mailbox
        mailbox._POOL.clear()
        thread_root = '<m1@example.com>'
        self.boxes = {
            'INBOX': [make(1, 'Dana Levi <dana@client.co.il>', 'הצעת מחיר', 'שלום, מצורפת ההצעה',
                           html='<p onclick="evil()">שלום <b>רב</b></p><script>alert(1)</script><img src="https://track.example/p.gif">'
                                '<img src="cid:logo1"><a href="javascript:alert(2)">x</a><a href="https://site.example">אתר</a>',
                           cid_png=True, attach=('quote.pdf', b'%PDF-1.4 fake')),
                      make(2, 'News <news@shop.example>', 'מבצע השבוע', 'הנחות ' * 50, flags={'\\Seen'}),
                      make(3, 'Dana Levi <dana@client.co.il>', 'Re: הצעת מחיר', 'עוד שאלה קטנה', refs=thread_root)],
            '[Gmail]/All Mail': [], '[Gmail]/Sent Mail': [], '[Gmail]/Trash': [], '[Gmail]/Drafts': [], '[Gmail]/Spam': [],
            '&BdcF6QXRBdUF3w-': []}
        self.fake = FakeIMAP(self.boxes)
        self.patches.append(mock.patch('mailbrief.mail.imap.connect', return_value=self.fake))
        self.patches[-1].start()
        self.patches.append(mock.patch('mailbrief.mail.mailbox.prefetch'))      # no background reading in the tests
        self.patches[-1].start()


class MailboxLayer(InboxBase):
    def test_folders_list_read_and_act(self):
        from mailbrief.mail import mailbox
        folders = mailbox.folders('me@gmail.com')
        self.assertEqual([f['role'] for f in folders if f['role'] != 'category'][:3], ['inbox', 'sent', 'drafts'])
        cats = [f['id'] for f in folders if f['role'] == 'category']                 # Gmail's categories, under the inbox
        self.assertEqual(cats[0], 'INBOX#category:primary')
        self.assertEqual(len(cats), 5)
        self.assertEqual(mailbox.real_folder(cats[1]), ('INBOX', 'category:promotions'))
        self.assertIn('חשבון', [f['name'] for f in folders])                       # Hebrew label, IMAP UTF-7
        self.assertEqual(next(f for f in folders if f['role'] == 'inbox')['unread'], 2)
        page = mailbox.list_messages('me@gmail.com')
        self.assertEqual([r['uid'] for r in page['items']], [3, 2, 1])
        first = page['items'][2]
        self.assertEqual(first['from']['name'], 'Dana Levi')
        self.assertTrue(first['attach'])
        self.assertIn('מצורפת ההצעה', first['snippet'])
        self.assertEqual(first['gid'], f'{91:x}')
        self.assertEqual(mailbox.cached_list('me@gmail.com', 'INBOX')[0]['uid'], 3)      # kept for offline
        raw = mailbox.fetch_raw('me@gmail.com', 'INBOX', 1)
        self.assertIn('\\Seen', self.boxes['INBOX'][0]['flags'])                      # opening = read
        self.assertEqual(mailbox.fetch_raw('me@gmail.com', 'INBOX', 1), raw)            # second time from the cache
        mailbox.set_flag('me@gmail.com', 'INBOX', [2], '\\Flagged', True)
        self.assertIn('\\Flagged', self.boxes['INBOX'][1]['flags'])
        mailbox.archive('me@gmail.com', 'INBOX', [2])
        self.assertEqual([m['uid'] for m in self.boxes['[Gmail]/All Mail']], [2])
        mailbox.delete('me@gmail.com', 'INBOX', [3])
        self.assertEqual([m['uid'] for m in self.boxes['[Gmail]/Trash']], [3])
        mailbox.delete('me@gmail.com', '[Gmail]/Trash', [3])                         # from the trash: gone for good
        self.assertEqual(self.boxes['[Gmail]/Trash'], [])

    def test_search_and_unread(self):
        from mailbrief.mail import mailbox
        self.assertEqual([r['uid'] for r in mailbox.list_messages('me@gmail.com', query='הנחות')['items']], [2])
        self.assertEqual([r['uid'] for r in mailbox.list_messages('me@gmail.com', unread=True)['items']], [3, 1])

    def test_offline_shows_the_last_list(self):
        from mailbrief.mail import mailbox
        mailbox.list_messages('me@gmail.com')
        mailbox._POOL.clear()
        with mock.patch('mailbrief.mail.imap.connect', side_effect=OSError('no network')):
            page = mailbox.list_messages('me@gmail.com')
        self.assertTrue(page['offline'])
        self.assertEqual(len(page['items']), 3)


class MailiceLike(InboxBase):
    def test_folders_create_rename_hide_delete(self):
        from mailbrief.mail import mailbox
        from mailbrief.web import inbox
        made = mailbox.create_folder('me@gmail.com', 'לקוחות')
        self.assertIn(made, self.boxes)
        self.assertIn('לקוחות', [f['name'] for f in mailbox.folders('me@gmail.com')])
        renamed = mailbox.rename_folder('me@gmail.com', made, 'לקוחות 2026')
        self.assertIn(renamed, self.boxes)
        with self.assertRaises(ValueError):
            mailbox.rename_folder('me@gmail.com', 'INBOX', 'x')                       # the fixed folders stay
        inbox.set_folder_pref('me@gmail.com', renamed, 'pinned', True)
        inbox.set_folder_pref('me@gmail.com', renamed, 'color', '#16a34a')
        listed = inbox.with_prefs('me@gmail.com', mailbox.folders('me@gmail.com'))
        pinned = next(f for f in listed if f['id'] == renamed)
        self.assertTrue(pinned['pinned'])
        self.assertEqual(pinned['color'], '#16a34a')
        self.assertLess(listed.index(pinned), next(i for i, f in enumerate(listed) if not f['role'] and not f['pinned']))
        mailbox.delete_folder('me@gmail.com', renamed)
        self.assertNotIn(renamed, self.boxes)
        self.assertEqual(mailbox.can('me@gmail.com'), {'archive': True, 'spam': True, 'drafts': True})

    def test_search_operators_for_other_servers(self):
        from mailbrief.mail.mailbox import imap_criteria
        crit, literal = imap_criteria('from:dana subject:"הצעת מחיר" has:attachment newer_than:7d -is:read שלום')
        self.assertEqual(crit[:2], ['FROM', '"dana"'])
        self.assertIn('SINCE', crit)
        self.assertIn('NOT', crit)
        self.assertEqual(literal, [('SUBJECT', 'הצעת מחיר'), ('TEXT', 'שלום')])          # Hebrew goes as literals
        storage.save_json(config.ACCOUNTS_FILE, [{'id': 'test0001', 'email': 'me@biz.co.il', 'host': 'imap.biz.co.il'}])
        from mailbrief.mail import mailbox
        mailbox._POOL.clear()
        hits = mailbox.list_messages('me@biz.co.il', query='שאלה')['items']
        self.assertEqual([r['uid'] for r in hits], [3])

    def test_overview_and_quote_folding_and_rich_text(self):
        from mailbrief.features import outbox
        from mailbrief.mail import mailbox
        from mailbrief.mail.sanitize import clean_html
        from mailbrief.web import inbox
        home = mailbox.overview(['me@gmail.com'])
        self.assertEqual(home['accounts'][0]['unread'], 2)
        import datetime as dt
        fresh = (dt.date.today() - dt.date(2026, 10, 8)).days < 7                  # the fake mail is dated 2026-10-08
        self.assertEqual(sum(home['accounts'][0]['days']), 3 if fresh else 0)
        self.assertEqual({r['uid'] for r in home['latest']}, {1, 3})
        folded, _ = clean_html('<p>תודה</p><div class="gmail_quote"><blockquote>ישן</blockquote></div>', collapse=True)
        self.assertIn('<details class="mb-q">', folded)
        self.assertTrue(folded.endswith('</details>'))
        self.assertNotIn('details', clean_html('<blockquote>ישן</blockquote>')[0])        # the quote under a reply stays plain
        item = outbox.schedule('me@gmail.com', 'x@y.co', 'שלום', 'מודגש', outbox._now(),
                               html='<b>מודגש</b><img src=x onerror=alert(1)><script>bad()</script>')
        part = outbox.build(item, {'email': 'me@gmail.com'}).get_body(('html',)).get_content()
        self.assertIn('<b>מודגש</b>', part)
        self.assertNotIn('onerror', part)
        self.assertNotIn('<script', part)
        self.assertTrue(inbox.viewable('text/plain') and inbox.viewable('application/octet-stream', 'data.csv'))
        self.assertFalse(inbox.viewable('application/x-msdownload', 'setup.exe'))
        self.assertTrue(inbox.translate_link('Hello, your order has shipped and will arrive on Monday morning at the latest.'))
        self.assertEqual(inbox.translate_link('שלום, ההזמנה שלך יצאה ותגיע ביום שני בבוקר לכל המאוחר. תודה רבה!'), '')

    def test_prefetch_reads_ahead_without_marking_read(self):
        import time
        from mailbrief.mail import mailbox
        self.patches.pop().stop()                                                   # the real prefetch this time
        mailbox.prefetch('me@gmail.com', 'INBOX', [{'uid': 1, 'size': 100}, {'uid': 3, 'size': 100}])
        for _ in range(50):
            if not mailbox._PREFETCHING:
                break
            time.sleep(0.05)
        self.assertEqual(mailbox._cached_body('me@gmail.com', 'INBOX', 3), self.boxes['INBOX'][2]['raw'])
        self.assertNotIn('\\Seen', self.boxes['INBOX'][2]['flags'])


class Review(InboxBase):
    def test_thread_search_quotes_odd_message_ids(self):
        from mailbrief.mail import mailbox
        odd = '<a "b"%] c@example.com>'
        self.boxes['INBOX'].append(make(9, 'X <x@example.com>', 'Re: odd', 'reply', refs=odd))
        found = mailbox.thread_messages('me@gmail.com', 'INBOX', odd, 1)
        self.assertEqual([r['uid'] for r in found], [9])

    def test_drop_leaves_a_busy_connection_alone(self):
        import threading
        from mailbrief.mail import mailbox
        acc = mailbox.account('me@gmail.com')
        with mailbox.session(acc, 'INBOX'):
            pass                                                                        # now kept in the pool
        inside, release = threading.Event(), threading.Event()

        def busy():
            with mailbox.session(acc, 'INBOX'):
                inside.set()
                release.wait(5)
        worker = threading.Thread(target=busy)
        worker.start()
        inside.wait(5)
        mailbox.drop(acc['id'])                                                         # must not close it mid-use
        self.assertIn(acc['id'], mailbox._POOL)
        release.set()
        worker.join(5)
        mailbox.drop(acc['id'])
        self.assertNotIn(acc['id'], mailbox._POOL)


class LikeAMailbox(InboxBase):
    def test_undo_mark_all_read_and_empty(self):
        from mailbrief.mail import mailbox
        self.boxes['[Gmail]/Trash'].append(dict(self.boxes['INBOX'][0], uid=1))      # uid 1 is taken in the trash
        target, new = mailbox.delete('me@gmail.com', 'INBOX', [1])
        self.assertEqual((target, new), ('[Gmail]/Trash', [2]))                     # the server's new UID, for ↩️
        mailbox.move('me@gmail.com', target, new, 'INBOX')                          # ↩️ undo: back where it was
        self.assertIn(b'm1@example.com', b''.join(m['raw'] for m in self.boxes['INBOX']))
        self.assertEqual(mailbox.mark_all_read('me@gmail.com', 'INBOX'), 2)
        self.assertTrue(all('\\Seen' in m['flags'] for m in self.boxes['INBOX']))
        self.assertEqual(mailbox.empty('me@gmail.com', '[Gmail]/Trash'), 1)
        self.assertEqual(self.boxes['[Gmail]/Trash'], [])
        with self.assertRaises(ValueError):
            mailbox.empty('me@gmail.com', 'INBOX')                                   # only the trash and spam
        self.assertEqual(mailbox.uid_list('3,5:7'), [3, 5, 6, 7])

    def test_print_page_templates_and_block(self):
        from mailbrief.web import inbox
        doc = inbox.print_document('me@gmail.com', 'INBOX', 1, 'n0nce')
        self.assertIn('<script nonce="n0nce">', doc)
        self.assertEqual(doc.count('<script'), 1)                                   # the email's own script is gone
        self.assertIn('quote.pdf', doc)
        self.assertNotIn('track.example', doc)


class SafeBody(InboxBase):
    def test_email_html_is_cleaned(self):
        from mailbrief.mail import mailbox, sanitize
        msg = mailbox.parse(self.boxes['INBOX'][0]['raw'])
        body, blocked = sanitize.message_html(msg)
        self.assertNotIn('<script', body)
        self.assertNotIn('onclick', body)
        self.assertNotIn('javascript:', body)
        self.assertNotIn('track.example', body)                                     # tracking picture blocked...
        self.assertEqual(blocked, 1)
        self.assertIn('src="data:image/png;base64,', body)                          # ...the email's own logo shown
        self.assertIn('target="_blank"', body)
        shown, _ = sanitize.message_html(msg, images=True)
        self.assertIn('https://track.example/p.gif', shown)
        self.assertIn('sandbox', sanitize.csp(False))
        self.assertNotIn('https:', sanitize.csp(False))

    def test_tricky_markup(self):
        from mailbrief.mail.sanitize import clean_html
        for bad in ['<svg onload=alert(1)>', '<iframe src="https://x"></iframe>', '<a href=" JaVaScRiPt:alert(1)">x</a>',
                    '<div style="background:url(javascript:alert(1))">', '<style>@import "https://x/a.css"; b{color:red}</style>',
                    '<form action="https://x"><input name=p></form>', '<img src=x onerror=alert(1)>', '<scr<script>ipt>alert(1)</script>',
                    '<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>', '<!--><img src=x onerror=alert(1)>-->']:
            out, _ = clean_html(bad)
            self.assertNotRegex(out.lower(), r'onload|onerror|javascript:|<iframe|<form|<input|@import|<svg|<script', bad)

    def test_css_escapes_cannot_load_from_the_internet(self):
        from mailbrief.mail.sanitize import clean_css, clean_html
        for css in ['background:u\\72l(https://t.example/a.png)', 'background:url\\28https://t.example/a.png\\29',
                    "background-image:image-set('https://t.example/a.png' 1x)", 'width:exp/**/ression(alert(1))',
                    '@im\\port "https://t.example/a.css"', 'background:url(//t.example/a.png)']:
            out = clean_css(css, False)
            self.assertNotIn('t.example', out, css)
            self.assertNotIn('expression', out, css)
            self.assertNotIn('@import', out, css)
        self.assertIn('AB//CD==', clean_css('background:url(data:image/png;base64,AB//CD==)', False))    # pictures in the mail stay
        self.assertIn('https://t.example/a.png', clean_css('background:url(https://t.example/a.png)', True))
        for bad in ['<a href="&#106;avascript:alert(1)">x</a>', '<a href="java&#09;script:alert(1)">x</a>', '<img srcset="https://t.example/a 1x">',
                    '<base href="https://t.example/">', '<meta http-equiv="refresh" content="0;url=https://t.example">',
                    '<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=">', '<td background="https://t.example/bg.png">x</td>']:
            out, _ = clean_html(bad)
            self.assertNotRegex(out.lower(), r'javascript|t\.example|svg|<base|<meta', bad)


class Writing(InboxBase):
    def test_reply_all_forward_and_draft(self):
        from mailbrief.features import outbox
        from mailbrief.mail import mailbox
        from mailbrief.web import inbox
        storage.save_json(config.ACCOUNTS_FILE, [{'id': 'test0001', 'email': 'me@gmail.com', 'host': 'imap.gmail.com', 'display_name': 'Me'}])
        reply = inbox.compose_data('all', 'me@gmail.com', 'INBOX', 1)
        self.assertEqual(reply['to'], 'dana@client.co.il')
        self.assertEqual(reply['subject'], 'Re: הצעת מחיר')
        fwd = inbox.compose_data('fwd', 'me@gmail.com', 'INBOX', 1)
        self.assertEqual(fwd['files'], ['quote.pdf'])
        original = mailbox.parse(self.boxes['INBOX'][0]['raw'])
        item = outbox.schedule('me@gmail.com', 'dana@client.co.il', reply['subject'], 'תודה!', outbox._now(), cc='a@b.co',
                               bcc='hidden@b.co', thread=inbox.thread_headers(original), quote=inbox.quote_of(original))
        msg = outbox.build(item, {'email': 'me@gmail.com', 'display_name': 'Me'})
        self.assertEqual(msg['In-Reply-To'], '<m1@example.com>')
        self.assertEqual(msg['Cc'], 'a@b.co')
        self.assertIn('> שלום, מצורפת ההצעה', msg.get_body(('plain',)).get_content())
        self.assertNotIn('<script', msg.get_body(('html',)).get_content())
        item = outbox.schedule('me@gmail.com', 'x@y.co', fwd['subject'], 'ראו למטה', outbox._now(),
                               forward={'account': 'me@gmail.com', 'folder': 'INBOX', 'uid': 1})
        names = [p.get_filename() for p in outbox.build(item, {'email': 'me@gmail.com'}).iter_attachments()]
        self.assertEqual(names, ['quote.pdf'])
        draft = EmailMessage()
        draft['To'], draft['Subject'] = 'x@y.co', 'טיוטה'
        draft.set_content('עוד לא גמרתי')
        folder, uid = mailbox.save_draft('me@gmail.com', draft)
        self.assertEqual((folder, uid), ('[Gmail]/Drafts', 1))
        folder, uid2 = mailbox.save_draft('me@gmail.com', draft, replace_uid=uid)     # saving again replaces it
        self.assertEqual([m['uid'] for m in self.boxes['[Gmail]/Drafts']], [uid2])
        with self.assertRaises(ValueError):
            outbox.schedule('me@gmail.com', 'not-an-address', 's', 'b', outbox._now())


class InboxServer(InboxBase):
    def test_sender_note_endpoint_persists_and_rejects_stale_edits(self):
        fields = {'a': 'me@gmail.com', 'email': 'sender@example.com', 'text': 'לבדוק ביום ראשון', 'revision': '0'}
        resp, note = self.post('/inbox_sender_note', fields)
        self.assertEqual(resp.status, 200)
        self.assertEqual(note['revision'], 1)
        resp, body = self.get('/inbox_sender.json?a=me%40gmail.com&email=sender%40example.com')
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(body)['note']['text'], fields['text'])
        resp, _ = self.post('/inbox_sender_note', dict(fields, text='ישן'))
        self.assertEqual(resp.status, 400)

    def setUp(self):
        super().setUp()
        from mailbrief.web import server
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            self.port = s.getsockname()[1]
        self.server = server.LocalServer(('127.0.0.1', self.port), server.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.token = server.TOKEN

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def get(self, path):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request('GET', path, headers={'Host': 'mailbrief.localhost:8765'})
        resp = conn.getresponse()
        return resp, resp.read()

    def post(self, path, fields):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request('POST', path, body=urlencode(dict(fields, t=self.token)),
                     headers={'Host': 'mailbrief.localhost:8765', 'Content-Type': 'application/x-www-form-urlencoded'})
        resp = conn.getresponse()
        return resp, json.loads(resp.read() or b'{}')

    def test_overview_only_reads_the_selected_mailbox(self):
        with mock.patch('mailbrief.web.server.view.emails', return_value=['me@gmail.com', 'work@example.com']), \
                mock.patch('mailbrief.web.server.mailbox.overview', return_value={'accounts': [], 'latest': [], 'week': []}) as overview:
            resp, _ = self.get('/inbox_overview.json?a=work%40example.com')
            self.assertEqual(resp.status, 200)
            overview.assert_called_once_with(['work@example.com'])
            overview.reset_mock()
            resp, _ = self.get('/inbox_overview.json?a=removed%40example.com')
            self.assertEqual(resp.status, 400)
            overview.assert_not_called()
            resp, _ = self.get('/inbox_overview.json?a=*')
            self.assertEqual(resp.status, 200)
            overview.assert_called_once_with(['me@gmail.com', 'work@example.com'])

    def test_other_websites_cannot_use_the_inbox(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request('GET', '/inbox_msg.json?a=me@gmail.com&f=INBOX&u=1',
                     headers={'Host': 'mailbrief.localhost:8765', 'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(conn.getresponse().status, 403)
        self.assertNotIn('\\Seen', self.boxes['INBOX'][0]['flags'])                  # nothing was marked as read
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        conn.request('GET', '/inbox_poll.json', headers={'Host': 'mailbrief.localhost:8765', 'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(conn.getresponse().status, 200)
        resp, data = self.post('/inbox_tool', {'a': 'me@gmail.com', 'f': 'INBOX', 'u': 'x1', 'tool': 'remind1'})
        self.assertEqual(resp.status, 400)                                            # a bad number: an error, not a crash

    def test_dates_from_the_hebrew_picker(self):
        import datetime as dt
        resp, body = self.get('/inbox')
        self.assertIn('id="hp"', body.decode())                                    # the Hebrew date picker is on every page
        later = (dt.datetime.now() + dt.timedelta(days=3)).replace(hour=10, minute=30, second=0, microsecond=0)
        resp, data = self.post('/inbox_send', {'a': 'me@gmail.com', 'to': 'x@y.co', 'subject': 'מתוזמן', 'body': 'שלום',
                                               'mode': 'new', 'when': 'custom', 'at': later.strftime('%Y-%m-%dT%H:%M')})
        self.assertIn('🕒', data['msg'])
        from mailbrief.features import outbox
        sent_at = dt.datetime.fromisoformat(outbox.outbox()[-1]['send_at'])
        self.assertGreaterEqual(sent_at.replace(tzinfo=None), later)               # (moved to after Shabbat if it fell inside)
        resp, data = self.post('/inbox_tool', {'a': 'me@gmail.com', 'f': 'INBOX', 'u': '1', 'tool': 'remind_at', 'at': later.strftime('%Y-%m-%dT%H:%M')})
        self.assertIn('⏰', data['msg'])
        self.assertEqual(storage.load_json(config.REMINDERS_FILE, [])[-1]['subject'], 'הצעת מחיר')
        resp, data = self.post('/inbox_tool', {'a': 'me@gmail.com', 'f': 'INBOX', 'u': '1', 'tool': 'remind_at', 'at': '2020-01-01T09:00'})
        self.assertEqual(resp.status, 400)                                          # the past is refused

    def test_undo_print_templates_block(self):
        resp, data = self.post('/inbox_act', {'a': 'me@gmail.com', 'f': 'INBOX', 'uids': '2', 'act': 'archive'})
        self.assertEqual(data['undo'], {'folder': '[Gmail]/All Mail', 'uids': [2], 'back': 'INBOX'})
        resp, data = self.post('/inbox_act', {'a': 'me@gmail.com', 'f': data['undo']['folder'], 'uids': '2', 'act': 'move', 'to': 'INBOX'})
        self.assertTrue(data['ok'])
        self.assertIn(2, [m['uid'] for m in self.boxes['INBOX']])
        resp, body = self.get('/inbox_print?a=me@gmail.com&f=INBOX&u=1')
        policy = resp.getheader('Content-Security-Policy')
        self.assertIn("script-src 'nonce-", policy)
        self.assertNotIn('unsafe-inline\'; img-src https', policy)
        resp, body = self.get('/inbox_templates.json')
        self.assertTrue(json.loads(body)['templates'][0]['text'])
        resp, data = self.post('/inbox_tool', {'a': 'me@gmail.com', 'f': 'INBOX', 'u': '2', 'tool': 'block'})
        self.assertIn('news@shop.example', data['msg'])
        self.assertIn('news@shop.example', [b['who'] for b in storage.load_json(config.SETTINGS_FILE, {})['blocked']])
        resp, data = self.post('/inbox_act', {'a': 'me@gmail.com', 'f': 'INBOX', 'uids': '', 'act': 'readall'})
        self.assertEqual(data['count'], 2)

    def test_the_whole_page(self):
        resp, body = self.get('/inbox')
        self.assertEqual(resp.status, 200)
        self.assertIn('id="ibx"', body.decode())
        resp, body = self.get('/inbox_folders.json?a=me@gmail.com')
        self.assertEqual(json.loads(body)['folders'][0]['role'], 'inbox')
        resp, body = self.get('/inbox_list.json?a=me@gmail.com&f=INBOX')
        rows = json.loads(body)['items']
        self.assertEqual(len(rows), 3)
        resp, body = self.get('/inbox_msg.json?a=me@gmail.com&f=INBOX&u=1')
        info = json.loads(body)
        self.assertEqual(info['files'][0]['name'], 'quote.pdf')
        self.assertEqual(info['blocked'], 1)
        resp, body = self.get('/inbox_body?a=me@gmail.com&f=INBOX&u=1')
        self.assertIn('sandbox', resp.getheader('Content-Security-Policy'))
        self.assertEqual(resp.getheader('X-Frame-Options'), 'SAMEORIGIN')
        policy = resp.getheader('Content-Security-Policy')            # only the height-reporting script, by its nonce
        nonce = re.search(r"script-src 'nonce-([\w-]+)'", policy).group(1)
        self.assertNotIn('allow-same-origin', policy)
        self.assertEqual(re.findall(rb'<script[^>]*>', body), [f'<script nonce="{nonce}">'.encode()])
        resp, body = self.get(f'/inbox_file?a=me@gmail.com&f=INBOX&u=1&n={info["files"][0]["n"]}')
        self.assertEqual(body, b'%PDF-1.4 fake')
        self.assertIn('attachment', resp.getheader('Content-Disposition'))
        resp, data = self.post('/inbox_act', {'a': 'me@gmail.com', 'f': 'INBOX', 'uids': '2', 'act': 'archive'})
        self.assertTrue(data['ok'])
        self.assertEqual([m['uid'] for m in self.boxes['INBOX']], [1, 3])
        resp, data = self.post('/inbox_act', {'a': 'me@gmail.com', 'f': 'INBOX', 'uids': '1', 'act': 'bogus'})
        self.assertEqual(resp.status, 400)
        self.assertIn('error', data)
        resp, data = self.post('/inbox_draft', {'a': 'me@gmail.com', 'to': 'x@y.co', 'subject': 'טיוטה', 'body': 'שלום', 'mode': 'new'})
        self.assertEqual(data['folder'], '[Gmail]/Drafts')
        with mock.patch('mailbrief.web.server.send_soon'):
            resp, data = self.post('/inbox_send', {'a': 'me@gmail.com', 'to': 'dana@client.co.il', 'subject': 'Re: הצעת מחיר', 'body': 'תודה',
                                                   'mode': 'reply', 'ref_a': 'me@gmail.com', 'ref_f': 'INBOX', 'ref_u': '1', 'quote': '1', 'when': 'now'})
        self.assertTrue(data['id'])
        from mailbrief.features import outbox
        waiting = outbox.outbox()[-1]
        self.assertEqual(waiting['thread']['in_reply_to'], '<m1@example.com>')
        resp, data = self.post('/inbox_cancel', {'id': data['id']})
        self.assertTrue(data['ok'])
        self.assertEqual(outbox.outbox()[-1]['status'], 'cancelled')
        resp, body = self.get('/inbox_list.json?a=*')                                  # all inboxes as one
        self.assertEqual(json.loads(body)['items'][0]['account'], 'me@gmail.com')


if __name__ == '__main__':
    unittest.main()
