"""📞 Phone numbers from email signatures: when a person writes, the number at the bottom of their email is kept
(on this computer only), so the client page can show it with a call and a WhatsApp button."""
import datetime as dt
import re

from mailbrief import config
from mailbrief.mail.message import body_text
from mailbrief.storage import load_json, save_json


PHONE = re.compile(r'(?<![\d+])(?:\+972[-\s.]?|0)(?:5\d|[23489]|7[2-9])[-\s.]?\d{3}[-\s.]?\d{4}(?!\d)')
QUOTED = re.compile(r'^\s*(>|On .+wrote:|.*כתב\(ה\):|.*כתב:|From:|מאת:|-----Original Message|________________)', re.M)


def own_part(text):
    """The sender's own words — the quoted conversation below them is someone else's signature."""
    cut = QUOTED.search(text)
    return text[:cut.start()] if cut else text


def find_phone(text):
    """The last Israeli phone number in the signature area (the bottom lines of the sender's own part)."""
    lines = [ln for ln in own_part(text).splitlines() if ln.strip()][-12:]
    found = PHONE.findall('\n'.join(lines))
    return normalize(found[-1]) if found else ''


def normalize(number):
    digits = re.sub(r'\D', '', number)
    if digits.startswith('972'):
        digits = '0' + digits[3:]
    return digits if 9 <= len(digits) <= 10 else ''


def pretty(phone):
    return f'{phone[:3]}-{phone[3:]}' if phone.startswith('05') else f'{phone[:2]}-{phone[2:]}'


def whatsapp(phone):
    """wa.me link for a mobile number (05x); landlines have no WhatsApp."""
    return f'https://wa.me/972{phone[1:]}' if phone.startswith('05') else ''


def learn(pairs):
    """pairs: (classified item, message) of the latest check. Only people — not newsletters or systems."""
    book, changed = load_json(config.CONTACTS_FILE, {}), False
    for it, msg in pairs:
        if 'people' not in it.get('cats', []) or not it.get('sender'):
            continue
        phone = find_phone(body_text(msg) or '')
        key = it['sender'].lower()
        if phone and not (book.get(key) or {}).get('manual') and (book.get(key) or {}).get('phone') != phone:
            book[key] = {'phone': phone, 'at': dt.date.today().isoformat()}
            changed = True
    if changed:
        save_json(config.CONTACTS_FILE, book)


def phone_of(*addresses):
    book = load_json(config.CONTACTS_FILE, {})
    return next((book[a.lower()]['phone'] for a in addresses if a and a.lower() in book), '')


def set_phone(address, phone):
    book = load_json(config.CONTACTS_FILE, {})
    phone = normalize(phone)
    if phone:
        book[address.lower()] = {'phone': phone, 'at': dt.date.today().isoformat(), 'manual': True}
    else:
        book.pop(address.lower(), None)
    save_json(config.CONTACTS_FILE, book)
    return phone
