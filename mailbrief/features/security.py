"""Extra protection: someone who never wrote to you before asking for money or bank details (the most common fraud —
"our bank account changed"), dangerous attachments (Office macros, programs hidden in a ZIP, password-locked archives),
and a weekly check of your addresses in known data leaks (Have I Been Pwned, with the user's own API key)."""
import datetime as dt
import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from urllib.parse import quote

from mailbrief import config
from mailbrief.mail.message import decode
from mailbrief.net import _PUBLIC_TLS
from mailbrief.storage import decrypt, load_json, save_json


MONEY_ASK = re.compile(
    r'העבר(?:ה|ת|ו)? (?:בנקאית|כספים|את התשלום)|פרטי (?:ה)?(?:חשבון|בנק)|מספר חשבון|חשבון (?:ה)?בנק (?:ה)?חדש|שינוי (?:פרטי )?(?:חשבון|בנק)|'
    r'עדכון פרטי (?:חשבון|בנק|תשלום)|תשלום דחוף|העברה דחופה|כרטיס(?:י)? מתנה|קוד(?:י)? (?:ה)?(?:כרטיס|מתנה)|IBAN|SWIFT|'
    r'wire transfer|bank (?:account|details)|new (?:bank|account) details|change of bank|urgent payment|gift ?cards?|'
    r'payment to (?:a|our) new account|ביטקוין|bitcoin|crypto wallet', re.I)


def known_people():
    """Everyone you already have mail history with, plus everyone you wrote to."""
    known = {(h.get('sender') or '').lower() for h in load_json(config.HISTORY_FILE, {}).values()}
    known |= {(r.get('to_email') or '').lower() for r in load_json(config.SNAPSHOT_FILE, {}).get('awaiting', [])}
    from mailbrief.features.clientcare import debts
    known |= {(d.get('email') or '').lower() for d in debts()}
    return {k for k in known if k}


def stranger_asks_money(it, known):
    """True for a first-time sender whose mail asks for money / bank details. Newsletters and shops don't count."""
    sender = (it.get('sender') or '').lower()
    if not sender or sender in known or 'newsletters' in it['cats'] or 'receipts' in it['cats']:
        return False
    domain = sender.rsplit('@', 1)[-1]
    if any(k.endswith('@' + domain) for k in known) and domain not in ('gmail.com', 'outlook.com', 'hotmail.com', 'walla.co.il', 'yahoo.com'):
        return False                              # a colleague of someone you know
    return bool(MONEY_ASK.search(f"{it.get('subject', '')} {it.get('snippet', '')} {it.get('body', '')[:3000]}"))


# ---- attachments ------------------------------------------------------------------------------------------------------

MACROS = re.compile(r'\.(docm|dotm|xlsm|xltm|xlam|pptm|potm|ppam|sldm)$', re.I)
RISKY_INSIDE = re.compile(r'\.(exe|scr|js|jse|vbs|vbe|bat|cmd|ps1|msi|hta|lnk|jar|com|pif|wsf|iso|img|docm|xlsm)$', re.I)


def attachment_risks(msg):
    """[reason] for attachments that need care, beyond the plain dangerous file types."""
    why = []
    for part in msg.iter_attachments():
        name = decode(part.get_filename()) or ''
        if MACROS.search(name):
            why.append(f'קובץ Office עם מאקרו ({name}) — לא לפתוח ולא „לאפשר תוכן”')
        elif re.search(r'\.[a-z0-9]{2,4}\.[a-z0-9]{2,4}$', name, re.I) and RISKY_INSIDE.search(name):
            why.append(f'סיומת כפולה מטעה ({name})')
        if name.lower().endswith('.zip'):
            data = part.get_payload(decode=True) or b''
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    inside = z.infolist()
                    bad = [i.filename for i in inside if RISKY_INSIDE.search(i.filename)]
                    if bad:
                        why.append(f'בתוך {name} יש קובץ מסוכן ({bad[0]})')
                    elif any(i.flag_bits & 0x1 for i in inside):
                        why.append(f'{name} נעול בסיסמה — דרך נפוצה להחביא נוזקה מסריקה')
            except (zipfile.BadZipFile, OSError, RuntimeError):
                pass
    return why[:2]


# ---- data leaks (Have I Been Pwned) -----------------------------------------------------------------------------------

def hibp_key():
    enc = (load_json(config.SETTINGS_FILE, {}).get('hibp') or {}).get('key', '')
    return decrypt(enc) if enc else ''


def breaches_for(address, key):
    """[{'name', 'date', 'data'}] — the leaks the address appears in (names only; nothing about you is sent but the address)."""
    req = urllib.request.Request(f'https://haveibeenpwned.com/api/v3/breachedaccount/{quote(address)}?truncateResponse=false',
                                 headers={'hibp-api-key': key, 'User-Agent': 'MailBrief'})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_PUBLIC_TLS) as resp:
            rows = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        if exc.code == 401:
            raise RuntimeError('מפתח Have I Been Pwned לא תקין') from None
        raise RuntimeError(f'Have I Been Pwned: שגיאה {exc.code}') from None
    return [{'name': r.get('Title') or r.get('Name'), 'date': r.get('BreachDate', ''),
             'data': ', '.join(r.get('DataClasses', [])[:5])} for r in rows]


def check_leaks(force=False):
    """Weekly (or now): every mailbox address. Returns (new leaks [(address, breach)], error)."""
    key = hibp_key()
    if not key:
        return [], ''
    cache = load_json(config.CACHE_FILE, {})
    last = cache.get('leaks') or {}
    week = dt.date.today().strftime('%G-%V')
    if not force and last.get('week') == week:
        return [], ''
    results, fresh, error = {}, [], ''
    for n, acc in enumerate(load_json(config.ACCOUNTS_FILE, [])):
        if n:
            time.sleep(7)                         # the service allows about one lookup every 6 seconds
        try:
            found = breaches_for(acc['email'], key)
        except RuntimeError as exc:
            error = str(exc)
            break
        results[acc['email']] = found
        before = {b['name'] for b in (last.get('results') or {}).get(acc['email'], [])}
        fresh += [(acc['email'], b) for b in found if b['name'] not in before and last.get('results') is not None]
    if not error:
        cache['leaks'] = {'week': week, 'at': dt.datetime.now().strftime('%d/%m/%Y'), 'results': results}
        save_json(config.CACHE_FILE, cache)
    return fresh, error
