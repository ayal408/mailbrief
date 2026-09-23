"""Forwarding by rules, once per email, only after the rule was created."""
import datetime as dt

from mailbrief import config
from mailbrief.mail import smtp
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.smtp import build_forward
from mailbrief.money.ledger import item_key
from mailbrief.storage import load_json, save_json


def process_forwards(acc, pending, state):
    """pending: [(item, message)]. Each message goes to each rule target once, only if it arrived after the rule."""
    done = set(state.get('_forwarded', []))
    log = load_json(config.FORWARD_LOG, [])
    sent = 0
    for it, msg in pending:
        if msg.get('X-MailBrief-Forwarded'):
            continue
        arrived = dt.datetime.fromisoformat(it['iso'])
        for to, created in it['forward']:
            key = f"{item_key(acc['email'], it)}|{to.lower()}"
            if key in done or it['sender'].lower() == to.lower() or sent >= config.MAX_FORWARDS_PER_RUN:
                continue
            if created and arrived < dt.datetime.fromisoformat(created):
                continue
            entry = {'at': dt.datetime.now().strftime('%d/%m %H:%M'), 'account': acc['email'], 'to': to,
                     'subject': it['subject'], 'from': it['sender']}
            try:
                smtp.send_mail(acc, build_forward(msg, acc, to))
                done.add(key)
                sent += 1
                entry['ok'] = True
            except Exception as exc:
                entry['error'] = friendly_error(exc, acc)
            log.append(entry)
    state['_forwarded'] = sorted(done)[-5000:]
    save_json(config.FORWARD_LOG, log[-200:])
    return sent
