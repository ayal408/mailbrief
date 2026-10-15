"""Draft identity and MIME content shared by saving and sending from the inbox."""
from mailbrief.features import outbox
from mailbrief.mail import mailbox
from mailbrief.web import inbox


def message_fields(form):
    mode = form.get('mode', 'new')
    extra = {'cc': form.get('cc', ''), 'bcc': form.get('bcc', '')}
    draft = None
    if str(form.get('draft_u', '')).isdigit():
        draft = {'account': form.get('draft_a') or form.get('ref_a') or form.get('a', ''),
                 'folder': form.get('draft_f', ''), 'uid': int(form['draft_u'])}
        extra['draft'] = draft
    original = None
    if str(form.get('ref_u', '')).isdigit() and mode in ('reply', 'all', 'fwd'):
        original = mailbox.parse(mailbox.fetch_raw(form.get('ref_a', ''), form.get('ref_f', ''), int(form['ref_u']), mark_seen=False))
        if mode != 'fwd':
            extra['thread'] = inbox.thread_headers(original)
        if form.get('quote'):
            extra['quote'] = inbox.quote_of(original, forward=mode == 'fwd')
    if mode == 'edit' and draft:
        original = mailbox.parse(mailbox.fetch_raw(draft['account'], draft['folder'], draft['uid'], mark_seen=False))
        extra['thread'] = {'in_reply_to': str(original.get('In-Reply-To') or ''),
                           'references': str(original.get('References') or '')}
    # A saved draft already contains forwarded/uploaded attachments. Otherwise use the original forward.
    if draft:
        extra['forward'] = dict(draft)
    elif mode == 'fwd' and original is not None:
        extra['forward'] = {'account': form.get('ref_a', ''), 'folder': form.get('ref_f', ''), 'uid': int(form['ref_u'])}
    return extra


def save(form):
    acc = mailbox.account(form.get('a', ''))
    extra = message_fields(form)
    draft = extra.pop('draft', None)
    item = {'id': 'draft', 'to': outbox.addresses(form.get('to', '')),
            'cc': outbox.addresses(extra.get('cc')), 'bcc': outbox.addresses(extra.get('bcc')),
            'subject': form.get('subject', '')[:300], 'body': form.get('body', '')[:50000],
            'thread': extra.get('thread'), 'quote': extra.get('quote'), 'forward': extra.get('forward')}
    if form.get('html', '').strip():
        item['html'] = outbox.rich_html(form['html'])
    message = outbox.build(item, acc, files_data=form.get('_files', ()), include_signature=False)
    del message['X-MailBrief-Scheduled']
    folder, uid = mailbox.save_draft(acc['email'], message, None)
    result = {'account': acc['email'], 'folder': folder, 'uid': uid}
    if draft and uid is not None:
        # Append first, then delete using the source account AND folder, even if the sender changed.
        try:
            mailbox.delete_for_good(draft['account'], draft['folder'], [draft['uid']])
        except Exception:
            result['warning'] = 'הטיוטה נשמרה; העותק הקודם נשאר בתיבה כי לא ניתן למחוק אותו בבטחה'
    return result
