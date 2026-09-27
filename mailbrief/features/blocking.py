"""🚫 Blocked senders: one click, and their future emails are archived by themselves (out of the inbox, still in the
mailbox) and never show in My day or in notifications. An address or a whole domain (@shop.com); unblocking is one click."""
import datetime as dt

from mailbrief import config
from mailbrief.storage import load_json, save_json


def blocked():
    return load_json(config.SETTINGS_FILE, {}).get('blocked') or []


def is_blocked(sender, rows=None):
    s = (sender or '').lower().strip()
    domain = '@' + s.rsplit('@', 1)[-1] if '@' in s else ''
    return any(b['who'] in (s, domain) for b in (blocked() if rows is None else rows))


def block(who):
    who = (who or '').lower().strip()
    if not who or ('@' not in who):
        raise ValueError('צריך כתובת מייל או @דומיין')
    settings = load_json(config.SETTINGS_FILE, {})
    rows = [b for b in settings.get('blocked') or [] if b['who'] != who]
    settings['blocked'] = rows + [{'who': who, 'since': dt.date.today().isoformat()}]
    save_json(config.SETTINGS_FILE, settings)
    return who


def unblock(who):
    settings = load_json(config.SETTINGS_FILE, {})
    settings['blocked'] = [b for b in settings.get('blocked') or [] if b['who'] != (who or '').lower().strip()]
    save_json(config.SETTINGS_FILE, settings)


def archive_blocked(m, acc, items):
    """In the check: blocked senders' emails leave the inbox (Gmail: the Inbox label goes; others: the Archive folder).
    Returns the items that stay."""
    from mailbrief.features.cleanup import _archive_folder
    from mailbrief.mail.imap import is_gmail
    rows = blocked()
    if not rows:
        return items
    out = [it for it in items if not is_blocked(it.get('sender'), rows)]
    uids = [it['uid'] for it in items if is_blocked(it.get('sender'), rows) and it.get('uid')]
    if uids:
        try:
            gmail = is_gmail(acc)
            target = None if gmail else _archive_folder(m)
            m.select('INBOX')
            for uid in uids:
                uid = uid.encode() if isinstance(uid, str) else uid
                if gmail:
                    m.uid('STORE', uid, '-X-GM-LABELS', r'(\Inbox)')
                else:
                    m.uid('MOVE', uid, f'"{target}"')
        except Exception:
            pass                                             # the next check tries again
    return out
