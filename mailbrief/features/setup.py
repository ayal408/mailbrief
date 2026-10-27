"""Register MailBrief's scheduled runs with Windows Task Scheduler, without script interpreters."""
import os
import subprocess
import sys
import winreg
import xml.etree.ElementTree as ET

from mailbrief import config


TASKS = {config.TASK_NAME: '--run', config.ALERTS_TASK: '--check', 'MailBrief Today': '--today'}
NO_WINDOW = 0x08000000


def _run(args):
    return subprocess.run(args, capture_output=True, timeout=60, creationflags=NO_WINDOW)


def _task_path(name):
    result = _run(['schtasks.exe', '/Query', '/TN', name, '/XML'])
    if result.returncode != 0:
        return '-'
    # schtasks labels redirected XML as UTF-16 even when it writes the active console encoding.
    for encoding in ('utf-8', 'utf-16', 'mbcs'):
        try:
            text = result.stdout.decode(encoding)
            start = text.find('<Task')
            if start < 0:
                continue
            root = ET.fromstring(text[start:])
            command = root.find('.//{*}Exec/{*}Command')
            return (command.text or '-').strip('"') if command is not None else '-'
        except (ET.ParseError, UnicodeError):
            continue
    return '-'


def installed_paths():
    return [_task_path(name) for name in TASKS]


def schedule_ok(exe=None):
    exe = exe or program_path()
    paths = installed_paths()
    return len(paths) == len(TASKS) and all(os.path.normcase(p) == os.path.normcase(exe) for p in paths)


def program_path():
    return sys.executable if getattr(sys, 'frozen', False) else ''


def _create(name, exe, flag, schedule):
    action = f'"{exe}" {flag}'
    result = _run(['schtasks.exe', '/Create', '/TN', name, '/TR', action, *schedule, '/F'])
    if result.returncode != 0:
        message = result.stderr.decode('mbcs', 'replace').strip() or result.stdout.decode('mbcs', 'replace').strip()
        raise RuntimeError('רישום התזמונים נכשל: ' + message[-200:])


def install(exe=None):
    exe = exe or program_path()
    if not exe:
        raise RuntimeError('התזמונים נרשמים רק מ-MailBrief.exe (לא מקוד המקור)')
    _create(config.TASK_NAME, exe, '--run', ['/SC', 'WEEKLY', '/D', 'SUN', '/ST', '08:00'])
    _create(config.ALERTS_TASK, exe, '--check', ['/SC', 'DAILY', '/ST', '07:00', '/RI', '60', '/DU', '16:00'])
    _create('MailBrief Today', exe, '--today', ['/SC', 'ONLOGON'])
    _register_protocol(exe)


def _register_protocol(exe):
    root = r'Software\Classes\mailbrief'
    values = ((root, '', 'URL:MailBrief'), (root, 'URL Protocol', ''),
              (root + r'\DefaultIcon', '', f'{exe},0'),
              (root + r'\shell\open\command', '', f'"{exe}" "%1"'))
    for key_name, value_name, value in values:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_name) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)


def _remove_protocol(exe=''):
    root = r'Software\Classes\mailbrief'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root + r'\shell\open\command') as key:
            command = winreg.QueryValueEx(key, '')[0]
    except OSError:
        return
    if exe and os.path.normcase(exe) not in os.path.normcase(command):
        return
    for child in (r'\shell\open\command', r'\shell\open', r'\shell', r'\DefaultIcon', ''):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, root + child)
        except OSError:
            pass


def remove(only_this_copy=True):
    exe = program_path() if only_this_copy else ''
    for name in TASKS:
        if not exe or os.path.normcase(_task_path(name)) == os.path.normcase(exe):
            _run(['schtasks.exe', '/Delete', '/TN', name, '/F'])
    _remove_protocol(exe)
    appdata = os.environ.get('APPDATA', '')
    shortcut = os.path.join(appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'MailBrief.lnk') if appdata else ''
    if shortcut and os.path.isfile(shortcut):
        try:
            os.remove(shortcut)                  # legacy shortcut; the installer manages current shortcuts itself
        except OSError:
            pass


def ensure():
    """On start: register the runs when missing or pointing at another copy (e.g. after an installer upgrade)."""
    exe = program_path()
    if exe and not schedule_ok(exe):
        from mailbrief.features.migrate import remember_previous
        for old in installed_paths():
            if old != '-' and os.path.normcase(old) != os.path.normcase(exe):
                remember_previous(old)             # its data can be brought over from the settings page
                break
        install(exe)
        return True
    return False
