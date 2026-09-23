"""Local .eml archive with an offline index, and optional newsletter archiving."""
import datetime as dt
import os
from urllib.parse import quote

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.mail.accounts import friendly_error
from mailbrief.mail.classify import classify, demote_automated
from mailbrief.mail.imap import fetch_recent, fetch_uids, is_gmail, special_folder
from mailbrief.money.ledger import item_key
from mailbrief.storage import load_json, save_json
from mailbrief.util import e, safe_name, write_once
from mailbrief.web.layout import STYLE


def archive_messages(account, pairs):
    """Save receipts and personal mail as .eml under ארכיון\\<mailbox>\\YYYY-MM\\ and refresh the offline index."""
    manifest, added = load_json(config.ARCHIVE_MANIFEST, {}), 0
    for it, msg in pairs:
        if not {'receipts', 'people'} & set(it['cats']):
            continue
        key = item_key(account, it)
        if key in manifest:
            continue
        folder = os.path.join(config.ARCHIVE_DIR, safe_name(account), it['iso'][:7])
        path = write_once(folder, f"{it['iso'][:10]} {safe_name(it['sender_name'])[:30]} - {safe_name(it['subject'])[:60]}.eml",
                          msg.as_bytes())
        manifest[key] = {'date': it['iso'][:10], 'account': account, 'from': it['sender_name'], 'email': it['sender'],
                         'subject': it['subject'][:150], 'kind': 'קבלה' if 'receipts' in it['cats'] else 'אישי',
                         'file': os.path.relpath(path, config.ARCHIVE_DIR).replace('\\', '/'), 'attachments': it.get('attachments', [])}
        added += 1
    if added:
        save_json(config.ARCHIVE_MANIFEST, manifest)
        write_archive_index(manifest)
    return added


def write_archive_index(manifest):
    rows = ''.join(
        f'<tr><td>{e(r["date"])}</td><td>{e(r["kind"])}</td><td dir="auto">{e(r["from"])}</td>'
        f'<td dir="auto"><a href="{quote(r["file"])}">{e(r["subject"])}</a></td>'
        f'<td>{"📎 " + e(", ".join(a for a in r["attachments"] if a)[:60]) if any(r["attachments"]) else ""}</td>'
        f'<td dir="ltr" style="font-size:12px">{e(r["account"])}</td></tr>'
        for r in sorted(manifest.values(), key=lambda r: r['date'], reverse=True))
    os.makedirs(config.ARCHIVE_DIR, exist_ok=True)
    with open(os.path.join(config.ARCHIVE_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(f'''<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>ארכיון מייל</title>
<style>{STYLE} input{{width:100%;font:inherit;padding:12px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--ink);margin:12px 0}}</style>
</head><body><main><h1>🗄️ ארכיון מייל</h1><p class="muted">{len(manifest)} הודעות — קבלות ומיילים אישיים, שמורים במחשב כקובצי .eml (נפתחים בכל תוכנת מייל). עובד גם בלי אינטרנט.</p>
<input id="q" placeholder="🔍 סינון לפי שם, נושא, תאריך..." oninput="for (const r of document.querySelectorAll('tbody tr')) r.style.display = r.textContent.toLowerCase().includes(this.value.toLowerCase()) ? '' : 'none'">
<div class="scroll"><table><thead><tr><th>תאריך</th><th>סוג</th><th>מאת</th><th>נושא</th><th>קבצים</th><th>תיבה</th></tr></thead><tbody>{rows}</tbody></table></div>
</main></body></html>''')


def archive_backfill(days=90):
    """Headers first to find receipts / personal mail, then download only those bodies."""
    accounts, rules, total, errors = load_json(config.ACCOUNTS_FILE, []), load_json(config.RULES_FILE, []), 0, []
    own = [a['email'] for a in accounts]
    for acc in accounts:
        try:
            m = imap.connect(acc)
            try:
                gmail = is_gmail(acc)
                folder = special_folder(m, r'\All') or 'INBOX'
                heads = []
                for uid, gid, msg in fetch_recent(m, gmail, days=days, readonly=True, folder=folder, limit=5000, headers_only=True):
                    it = classify(msg, acc['email'], rules)
                    it['uid'] = uid
                    heads.append(it)
                demote_automated(heads, own)
                wanted = [it['uid'].encode() for it in heads if {'receipts', 'people'} & set(it['cats']) and it.get('uid')]
                pairs = []
                for uid, gid, msg in fetch_uids(m, wanted, gmail):
                    it = classify(msg, acc['email'], rules)
                    it['message_id'] = (msg.get('Message-ID') or '').strip()
                    pairs.append((it, msg))
                demote_automated([it for it, _ in pairs], own)
                total += archive_messages(acc['email'], pairs)
            finally:
                m.logout()
        except Exception as exc:
            errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
    save_json(config.ACCOUNTS_FILE, accounts)
    return total, errors


def archive_old_newsletters(days_old=3):
    """Gmail only: take newsletters older than N days out of the inbox (label removal — nothing is deleted)."""
    accounts, rules, moved, errors = load_json(config.ACCOUNTS_FILE, []), load_json(config.RULES_FILE, []), 0, []
    own = [a['email'] for a in accounts]
    cutoff = dt.datetime.now().astimezone() - dt.timedelta(days=days_old)
    for acc in accounts:
        if not is_gmail(acc):
            continue
        try:
            m = imap.connect(acc)
            try:
                items = []
                for uid, _, msg in fetch_recent(m, True, days=45, readonly=False, limit=3000, headers_only=True):
                    it = classify(msg, acc['email'], rules)
                    it['uid'] = uid
                    items.append(it)
                demote_automated(items, own)
                old = [it['uid'] for it in items if 'newsletters' in it['cats'] and it.get('uid') and not it.get('rules')
                       and dt.datetime.fromisoformat(it['iso']) < cutoff]
                for i in range(0, len(old), 100):
                    typ, _ = m.uid('STORE', ','.join(old[i:i + 100]), '-X-GM-LABELS', r'(\Inbox)')
                    if typ == 'OK':
                        moved += len(old[i:i + 100])
            finally:
                m.logout()
        except Exception as exc:
            errors.append(f"{acc['email']}: {friendly_error(exc, acc)}")
    save_json(config.ACCOUNTS_FILE, accounts)
    return moved, errors
