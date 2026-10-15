"""Backups, restore and the health check."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import PurePosixPath

from mailbrief import config
from mailbrief.features import google_apps
from mailbrief.mail import imap
from mailbrief.features.calendar import holy_status, holy_windows
from mailbrief.mail.accounts import friendly_error
from mailbrief.storage import file_lock, locked, load_json, save_json


@locked(lambda: config.OUTBOX_FILE)
def make_backup(tag='auto'):
    """Back up JSON and the local files needed by queued mail and signatures. Secrets stay DPAPI-encrypted."""
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    path = os.path.join(config.BACKUP_DIR, f'mailbrief-{dt.datetime.now():%Y-%m-%d-%H%M%S-%f}-{tag}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(os.listdir(config.DATA)):
            if (name.endswith('.json') and name != 'cache.json') or name == 'token':
                with file_lock(os.path.join(config.DATA, name)):
                    z.write(os.path.join(config.DATA, name), name)
        for folder in ('outbox-files', 'signatures'):
            root = os.path.join(config.DATA, folder)
            for parent, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(parent, d))]
                for name in names:
                    source = os.path.join(parent, name)
                    if not os.path.islink(source):
                        z.write(source, os.path.relpath(source, config.DATA).replace(os.sep, '/'))
    for old in list_backups()[config.KEEP_BACKUPS:]:
        try:
            os.remove(os.path.join(config.BACKUP_DIR, old))
        except OSError:
            pass
    return path


def list_backups():
    return sorted((f for f in os.listdir(config.BACKUP_DIR) if f.startswith('mailbrief-') and f.endswith('.zip')), reverse=True) \
        if os.path.isdir(config.BACKUP_DIR) else []


def _backup_member(name):
    parts = name.split('/')
    if not all(parts) or '\\' in name or ':' in name or any(p in ('.', '..') for p in parts) or name.startswith('/'):
        raise RuntimeError('נתיב לא תקין בגיבוי')
    if len(parts) == 1 and (name.endswith('.json') or name == 'token'):
        return True
    if parts[0] == 'outbox-files' and len(parts) == 3:
        return True
    if parts[0] == 'signatures' and len(parts) == 2:
        return True
    raise RuntimeError('קובץ לא צפוי בגיבוי: ' + name)


@locked(lambda: config.OUTBOX_FILE + '.sender')
@locked(lambda: config.OUTBOX_FILE)
def restore_backup(name):
    if name not in list_backups():
        raise RuntimeError('הגיבוי לא נמצא')
    # Stage and validate the whole archive before touching live data. Keep old JSON-only backups compatible.
    with tempfile.TemporaryDirectory(dir=config.DATA) as stage:
        with zipfile.ZipFile(os.path.join(config.BACKUP_DIR, name)) as z:
            members = [m for m in z.infolist() if not m.is_dir()]
            if len({m.filename for m in members}) != len(members):
                raise RuntimeError('קובץ כפול בגיבוי')
            for member in members:
                _backup_member(member.filename)
                target = os.path.join(config.DATA, *PurePosixPath(member.filename).parts)
                if os.path.commonpath([os.path.realpath(config.DATA), os.path.realpath(target)]) != os.path.realpath(config.DATA):
                    raise RuntimeError('נתיב לא תקין בגיבוי')
                content = z.read(member)
                if member.filename.endswith('.json') and '/' not in member.filename:
                    json.loads(content.decode('utf-8'))
                dest = os.path.join(stage, *PurePosixPath(member.filename).parts)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'wb') as f:
                    f.write(content)
        make_backup('before-restore')
        for member in members:
            parts = PurePosixPath(member.filename).parts
            target = os.path.join(config.DATA, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with file_lock(target):
                os.replace(os.path.join(stage, *parts), target)
    return len(members)


def health_checks():
    """[(area, ok, detail)] — quick diagnostics of everything MailBrief depends on."""
    rows = []
    accounts = load_json(config.ACCOUNTS_FILE, [])
    if not accounts:
        rows.append(('תיבות מייל', False, 'אין תיבה מחוברת — ״חיבור עם Google״ בדף הראשי'))
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
    g = google_apps.gapps_account()
    if not g:
        rows.append(('יומן ומשימות Google', True, 'לא מחובר (לא חובה)'))
    else:
        for what, fetch in (('Google Calendar', google_apps.events_on), ('Google Tasks', google_apps.open_tasks)):
            try:
                found = len(fetch(g))
                rows.append((what, True, f'מחובר ({g["email"]}) · {found} {"אירועים היום" if what == "Google Calendar" else "משימות פתוחות"}'))
            except Exception as exc:
                rows.append((what, False, str(exc)))
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


def verify_backup(name=None):
    """🧪 Opens a backup the way a restore would (without restoring anything) and checks every file inside.
    Returns (ok, detail). The newest one when no name is given."""
    import json
    names = list_backups()
    name = name or (names[0] if names else '')
    if not name:
        return False, 'עוד אין גיבוי במחשב'
    try:
        with zipfile.ZipFile(os.path.join(config.BACKUP_DIR, name)) as z:
            bad = z.testzip()
            if bad:
                return False, f'הקובץ {bad} בגיבוי פגום'
            members = [m for m in z.namelist() if m.endswith('.json')]
            for m in members:
                json.loads(z.read(m).decode('utf-8'))
            needed = {n for n in ('accounts.json', 'settings.json') if os.path.exists(os.path.join(config.DATA, n))}
            missing = needed - set(members)
            if missing:
                return False, f'חסר בגיבוי: {", ".join(sorted(missing))}'
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        return False, f'לא הצלחתי לפתוח את הגיבוי: {exc}'
    return True, f'{name} — {len(members)} קבצים, כולם נפתחים ותקינים'


def verify_cloud():
    """The newest encrypted copy in Google Drive: downloaded, unlocked with the saved password and checked — in memory only.
    (None, reason) when there is nothing to check."""
    import io
    import json
    from mailbrief.features import cloud_backup
    from mailbrief.storage import decrypt
    c = cloud_backup.cloud_cfg()
    acc = cloud_backup.drive_account()
    if not (c.get('auto') and c.get('password') and acc):
        return None, 'גיבוי הענן לא פעיל עם סיסמה שמורה'
    files = cloud_backup.remote_backups(acc)
    if not files:
        return False, 'אין עדיין גיבוי ב-Drive'
    blob = cloud_backup._call(acc, 'GET', f'https://www.googleapis.com/drive/v3/files/{files[0]["id"]}?alt=media')
    try:
        data = cloud_backup.unseal(blob, decrypt(c['password']))
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.testzip():
                return False, 'הגיבוי ב-Drive פגום'
            count = sum(1 for m in z.namelist() if m.endswith('.json') and json.loads(z.read(m).decode('utf-8')) is not None)
    except Exception as exc:
        return False, f'הגיבוי ב-Drive לא נפתח: {exc}'
    return True, f'{files[0]["name"]} ב-Drive — {count} קבצים תקינים'


def check_backups(state=None, force=False):
    """Once a month (or on request): check the local and the cloud backup. A bad local one -> a fresh backup, checked again.
    Saves the result for the settings page; returns (ok, lines)."""
    month = dt.date.today().strftime('%Y-%m')
    if state is not None and not force and state.get('_backup_check') == month:
        return None, []
    ok, detail = verify_backup()
    lines = [('✓ ' if ok else '⚠️ ') + detail]
    if not ok:
        make_backup('checked')
        ok, detail = verify_backup()
        lines.append(('✓ גיבוי חדש נוצר ונבדק: ' if ok else '⚠️ גם גיבוי חדש נכשל: ') + detail)
    try:
        cloud_ok, cloud_detail = verify_cloud()
    except Exception as exc:
        cloud_ok, cloud_detail = False, f'בדיקת Drive נכשלה: {exc}'
    if cloud_ok is not None:
        lines.append(('✓ ' if cloud_ok else '⚠️ ') + cloud_detail)
        ok = ok and cloud_ok
    settings = load_json(config.SETTINGS_FILE, {})
    settings['backup_check'] = {'at': dt.datetime.now().strftime('%d/%m/%Y %H:%M'), 'ok': ok, 'lines': lines}
    save_json(config.SETTINGS_FILE, settings)
    if state is not None:
        state['_backup_check'] = month
    return ok, lines


_SCHEDULE_STATUS = {}


def cached_schedule_status(task=config.TASK_NAME):
    from mailbrief.background import submit
    def refresh():
        _SCHEDULE_STATUS[task] = schedule_status(task)
    submit('schedule-' + task, refresh, cooldown=60)
    return _SCHEDULE_STATUS.get(task, 'נבדק ברקע…')
