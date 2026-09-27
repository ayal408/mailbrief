"""Which mailbox the pages show: all of them, or one — chosen from the switcher under the tabs. Each mailbox has a colour."""
from mailbrief import config
from mailbrief.storage import load_json, save_json
from mailbrief.util import e


COLORS = ['#7c3aed', '#f97316', '#0ea5e9', '#16a34a', '#ec4899', '#ca8a04', '#14b8a6', '#6366f1']


def emails():
    return [a['email'] for a in load_json(config.ACCOUNTS_FILE, [])]


def current_account():
    """'' = all mailboxes."""
    chosen = (load_json(config.SETTINGS_FILE, {}).get('view_account') or '').lower()
    return next((m for m in emails() if m.lower() == chosen), '')


def set_account(address):
    settings = load_json(config.SETTINGS_FILE, {})
    settings['view_account'] = address if address.lower() in {m.lower() for m in emails()} else ''
    save_json(config.SETTINGS_FILE, settings)
    return settings['view_account']


def mine(row, key='account', current=None):
    """True when the row belongs to the chosen mailbox (always true when showing all)."""
    current = current_account() if current is None else current
    return not current or (row.get(key) or '').lower() == current.lower()


def color(address):
    known = [m.lower() for m in emails()]
    index = known.index(address.lower()) if address and address.lower() in known else len(known)
    return COLORS[index % len(COLORS)]


def dot(address):
    """A small coloured dot marking which mailbox an email belongs to (only when there is more than one)."""
    if not address or len(emails()) < 2:
        return ''
    return (f'<span title="{e(address)}" style="display:inline-block;width:9px;height:9px;border-radius:50%;'
            f'background:{color(address)};margin-inline-end:6px;vertical-align:1px"></span>')


def account(address):
    return next((a for a in load_json(config.ACCOUNTS_FILE, []) if a['email'].lower() == (address or '').lower()), {})


def avatar(address, size=22):
    """The mailbox's Google profile picture, or a coloured circle with its first letter."""
    acc = account(address)
    style = f'width:{size}px;height:{size}px;border-radius:50%;flex:none;vertical-align:middle'
    if acc.get('avatar'):
        return f'<img src="/avatar/{e(acc["avatar"])}" alt="" title="{e(acc.get("display_name") or address)}" style="{style};object-fit:cover">'
    letter = (acc.get('display_name') or address or '?')[:1].upper()
    return (f'<span title="{e(address)}" style="{style};display:inline-grid;place-items:center;background:{color(address)};'
            f'color:#fff;font-weight:700;font-size:{int(size * .5)}px">{e(letter)}</span>')


def label(address):
    """The Google account's name next to the picture, and the address (before the @) beside it."""
    name, short = account(address).get('display_name', '').strip(), e(address.split('@')[0])
    if not name:
        return short
    return (f'<span dir="auto" style="font-weight:500;color:var(--ink)">{e(name)}</span>'
            f'<span style="font-size:11.5px;opacity:.75;margin-inline-start:6px">{short}</span>')


def switcher():
    """The chips under the tabs; hidden with a single mailbox."""
    from mailbrief.web.token import TOKEN
    boxes = emails()
    if len(boxes) < 2:
        return ''
    current = current_account()
    chip = ('<button name="account" value="{value}" class="mbx{on}" type="submit">{mark}{label}</button>')
    chips = chip.format(value='', on=' on' if not current else '', mark='📬 ', label='כל התיבות') + ''.join(
        chip.format(value=e(m), on=' on' if m == current else '',
                    mark=f'<span style="margin-inline-end:6px">{avatar(m, 18)}</span>',
                    label=label(m)) for m in boxes)
    return (f'<form method="post" action="/view_account" class="mbxs"><input type="hidden" name="t" value="{TOKEN}">{chips}</form>')
