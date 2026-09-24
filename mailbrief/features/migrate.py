"""Moving to the installed MailBrief: bring over the data of a previous copy (a MailBrief.exe folder with its data next to it).
Encrypted sign-ins move too — Windows DPAPI keys belong to this Windows user, not to the folder."""
import os
import shutil

from mailbrief import config
from mailbrief.storage import load_json, save_json


FOLDERS = ('data', 'קבלות', 'ארכיון', 'גיבויים', 'הורדות', 'יומני אוטומציה')
SKIP = {'window', 'url.txt', 'tray.log', 'setup.log'}      # belongs to the running program, not to the user's data


def has_data(folder):
    return bool(folder) and os.path.isfile(os.path.join(folder, 'data', 'accounts.json'))


def same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def remember_previous(exe_path):
    """Called before this copy takes over the scheduled runs: the copy they pointed at may hold the user's data."""
    folder = os.path.dirname(exe_path or '')
    if has_data(folder) and not same(folder, config.HERE):
        settings = load_json(config.SETTINGS_FILE, {})
        settings['previous_copy'] = folder
        save_json(config.SETTINGS_FILE, settings)


def previous_copy():
    folder = load_json(config.SETTINGS_FILE, {}).get('previous_copy', '')
    return folder if has_data(folder) and not same(folder, config.HERE) else ''


def summary(folder):
    accounts = load_json(os.path.join(folder, 'data', 'accounts.json'), [])
    receipts = load_json(os.path.join(folder, 'data', 'receipts.json'), {})
    return {'accounts': [a.get('email', '') for a in accounts], 'receipts': len(receipts)}


def import_from(folder):
    """Copies the previous copy's data here. What is here now is backed up first (גיבויים), so nothing is lost."""
    folder = folder.strip().strip('"')
    if folder.lower().endswith('.exe'):          # the path of the old MailBrief.exe — its folder holds the data
        folder = os.path.dirname(folder)
    if not has_data(folder):
        raise ValueError('בתיקייה הזו אין נתונים של MailBrief (צריכה להיות בה תיקיית data עם accounts.json)')
    if same(folder, config.HERE):
        raise ValueError('זו התיקייה של העותק הנוכחי')
    if os.path.isfile(config.ACCOUNTS_FILE):
        from mailbrief.features.maintenance import make_backup
        try:
            make_backup('before-import')
        except OSError:
            pass
    copied = 0
    for name in FOLDERS:
        src = os.path.join(folder, name)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(config.HERE, name)
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            if name == 'data' and rel.split(os.sep)[0] in SKIP:
                continue
            os.makedirs(os.path.join(dst, rel), exist_ok=True)
            for f in files:
                if name == 'data' and rel == '.' and f in SKIP:
                    continue
                shutil.copy2(os.path.join(root, f), os.path.join(dst, rel, f))
                copied += 1
    settings = load_json(config.SETTINGS_FILE, {})
    settings.pop('previous_copy', None)
    settings['imported_from'] = folder
    save_json(config.SETTINGS_FILE, settings)
    return copied
