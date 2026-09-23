"""Gmail labels / IMAP folders under "אוטומטי"."""

from mailbrief.mail.classify import CATS, TAG_PREFIX, TAGGED
from mailbrief.mail.imap import delimiter, is_gmail, utf7


def apply_tags(m, acc, items, state):
    gmail = is_gmail(acc)
    sep = '/' if gmail else delimiter(m)
    done = set(state.setdefault(acc['id'], []))
    created, count = set(), 0
    for it in items:
        if not it.get('uid'):
            continue
        for label in [CATS[c][1] for c in it['cats'] if c in TAGGED] + it.get('rules', []):
            name = utf7(f'{TAG_PREFIX}{sep}{label}')
            if name not in created:
                m.create(f'"{utf7(TAG_PREFIX)}"')
                m.create(f'"{name}"')      # "already exists" is fine
                created.add(name)
            key = f"{it.get('message_id') or it['uid']}|{label}"
            if gmail:
                typ, _ = m.uid('STORE', it['uid'], '+X-GM-LABELS', f'("{name}")')
            elif key in done:
                continue
            else:
                typ, _ = m.uid('COPY', it['uid'], f'"{name}"')
            if typ == 'OK':
                count += 1
                done.add(key)
    state[acc['id']] = sorted(done)[-5000:]
    return count


def tag_message(m, acc, uid, label):
    gmail = is_gmail(acc)
    sep = '/' if gmail else delimiter(m)
    name = utf7(f'{TAG_PREFIX}{sep}{label}')
    m.create(f'"{utf7(TAG_PREFIX)}"')
    m.create(f'"{name}"')
    typ, _ = (m.uid('STORE', uid, '+X-GM-LABELS', f'("{name}")') if gmail else m.uid('COPY', uid, f'"{name}"'))
    if typ != 'OK':
        raise RuntimeError('השרת לא אישר את התווית')
