"""📁 A folder per client: files that clients send (mail matching one of your rules) are saved by themselves in
Documents\\MailBrief\\לקוחות\\<label>\\<YYYY-MM>\\ — turned on in Settings → Clients."""
import datetime as dt
import os

from mailbrief import config
from mailbrief.mail.message import decode
from mailbrief.storage import load_json
from mailbrief.util import safe_name, write_once


def enabled():
    return bool(load_json(config.SETTINGS_FILE, {}).get('client_folders'))


def save_client_files(pairs, state):
    """pairs: [(item, message)] from the hourly check. Each email once. Returns how many files were saved."""
    if not enabled():
        return 0
    done, saved = set(state.get('_client_files', [])), 0
    for it, msg in pairs:
        mid = it.get('message_id') or (msg.get('Message-ID') or '').strip()
        if not it.get('rules') or not mid or mid in done:
            continue
        done.add(mid)
        month = (it.get('iso') or dt.date.today().isoformat())[:7]
        for part in msg.iter_attachments():
            data = part.get_payload(decode=True) or b''
            name = decode(part.get_filename()) or ''
            if not data or not name or len(data) > 25_000_000:
                continue
            folder = os.path.join(config.CLIENTS_DIR, safe_name(it['rules'][0])[:60], month)
            write_once(folder, f"{(it.get('iso') or '')[:10]} {safe_name(name)}", data)
            saved += 1
    state['_client_files'] = sorted(done)[-3000:]
    return saved
