"""Backups, restore and the health check."""
import datetime as dt
import os
import re
import shutil
import subprocess
import zipfile

from mailbrief import config
from mailbrief.mail import imap
from mailbrief.features.calendar import holy_status, holy_windows
from mailbrief.features.notify import telegram_cfg
from mailbrief.mail.accounts import friendly_error
from mailbrief.storage import load_json, save_json


def make_backup(tag='auto'):
    """Zip every settings / data JSON (not the report HTML or the web cache). Secrets stay DPAPI-encrypted."""
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    path = os.path.join(config.BACKUP_DIR, f'mailbrief-{dt.datetime.now():%Y-%m-%d-%H%M%S}-{tag}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(os.listdir(config.DATA)):
            if (name.endswith('.json') and name != 'cache.json') or name == 'token':
                z.write(os.path.join(config.DATA, name), name)
    for old in list_backups()[config.KEEP_BACKUPS:]:
        try:
            os.remove(os.path.join(config.BACKUP_DIR, old))
        except OSError:
            pass
    return path


def list_backups():
    return sorted((f for f in os.listdir(config.BACKUP_DIR) if f.startswith('mailbrief-') and f.endswith('.zip')), reverse=True) \
        if os.path.isdir(config.BACKUP_DIR) else []


def restore_backup(name):
    if name not in list_backups():
        raise RuntimeError('הגיבוי לא נמצא')
    make_backup('before-restore')                 # so a restore can always be undone
    with zipfile.ZipFile(os.path.join(config.BACKUP_DIR, name)) as z:
        members = [m for m in z.namelist() if '/' not in m and '\\' not in m and (m.endswith('.json') or m == 'token')]
        for member in members:
            z.extract(member, config.DATA)
    return len(members)


def health_checks():
    """[(area, ok, detail)] — quick diagnostics of everything MailBrief depends on."""
    rows = []
    accounts = load_json(config.ACCOUNTS_FILE, [])
    if not accounts:
        rows.append(('תיבות מייל', False, 'אין תיבה מחוברת — „חיבור עם Google” בדף הראשי'))
    for acc in accounts:
        started = dt.datetime.now()
        try:
            imap.connect(acc).logout()
            rows.append((f'תיבה {acc["email"]}', True, f'מחובר ({(dt.datetime.now() - started).total_seconds():.1f} שנ׳)'))
        except Exception as exc:
            rows.append((f'תיבה {acc["email"]}', False, f'{friendly_error(exc, acc)} — אפשר להתחבר מחדש עם אותו כפתור'))
    save_json(config.ACCOUNTS_FILE, accounts)
    for task, what in ((config.TASK_NAME, 'תדריך שבועי'), (config.ALERTS_TASK, 'בדיקה שעתית'), ('MailBrief Today', 'היום שלי בכניסה')):
        status = schedule_status(task)
        ok = not status.startswith('לא')
        rows.append((f'תזמון: {what}', ok or task == 'MailBrief Today', status if ok else f'{status} — אפשר לבקש ממני להתקין מחדש'))
    windows = holy_windows(saved_only=True)
    rows.append(('לוח שבתות וחגים', bool(windows), holy_status() if windows else 'אין לוח שמור — ייטען בבדיקה הבאה עם אינטרנט'))
    for log, what in (('last-check.log', 'הבדיקה השעתית'), ('tray.log', 'הסמל ליד השעון')):
        path = os.path.join(config.DATA, log)
        rows.append((what, not os.path.exists(path), 'תקין' if not os.path.exists(path) else
                     f'שגיאה אחרונה ({dt.datetime.fromtimestamp(os.path.getmtime(path)):%d/%m %H:%M}) — מופיעה בקובץ data\\{log}'))
    last = os.path.join(config.DATA, 'last-run.log')
    if os.path.exists(last):
        with open(last, encoding='utf-8') as f:
            first = f.readline().strip()
        rows.append(('ריצה שבועית אחרונה', 'FAILED' not in first, first[:60]))
    free = shutil.disk_usage(config.HERE).free / 1e9
    rows.append(('מקום פנוי בדיסק', free > 2, f'{free:.1f} GB'))
    token, chat, _ = telegram_cfg()
    rows.append(('טלגרם', True, 'מחובר' if token and chat else 'לא מחובר (לא חובה)'))
    rows.append(('גיבויים', bool(list_backups()), f'{len(list_backups())} גיבויים, האחרון: {list_backups()[0][10:26]}' if list_backups() else 'עוד אין — נוצר בריצה השבועית'))
    return rows


def schedule_status(task=config.TASK_NAME):
    try:
        out = subprocess.run(['schtasks', '/Query', '/TN', task, '/FO', 'LIST'], capture_output=True, text=True,
                             encoding='mbcs', errors='replace', timeout=10, creationflags=0x08000000).stdout
        nxt = re.search(r'Next Run Time:\s*(.+)', out)
        return f'מופעל — הריצה הבאה: {nxt.group(1).strip()}' if nxt else 'לא מתוזמן'
    except Exception:
        return 'לא ידוע'
