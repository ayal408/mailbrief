"""Paths and limits. Everything else reads these as config.NAME, so tests can redirect them in one place."""
import os
import sys

# Where the program is: next to MailBrief.exe, or the project folder (one level above this package) when run from source.
APP_DIR = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
           else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _documents():
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:     # CSIDL_PERSONAL (follows OneDrive)
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser('~'), 'Documents')


# Installed by winget (or into Program Files) the program folder is replaced on every upgrade, so the data lives in
# Documents\MailBrief. A copy that already keeps its data next to the EXE (or runs from source) keeps doing that.
INSTALLED = getattr(sys, 'frozen', False) and os.path.isfile(os.path.join(APP_DIR, 'unins000.exe'))   # MailBrief-Setup.exe
MANAGED = (getattr(sys, 'frozen', False) and not os.path.isdir(os.path.join(APP_DIR, 'data'))
           and (INSTALLED or '\\winget\\packages\\' in APP_DIR.lower()
                or APP_DIR.lower().startswith(os.environ.get('ProgramFiles', 'C:\\Program Files').lower())))
HERE = os.path.join(_documents(), 'MailBrief') if MANAGED else APP_DIR
# Files that travel inside MailBrief.exe (PyInstaller unpacks them to _MEIPASS), or the project folder from source.
RESOURCES = getattr(sys, '_MEIPASS', APP_DIR)
# The program's own Google sign-in key, added at build time (never in git): users just click "Connect with Google".
BUNDLED_GOOGLE = os.path.join(RESOURCES, 'google_client.json')
NOTICES_FILE = os.path.join(RESOURCES, 'THIRD-PARTY-NOTICES.txt')
DATA = os.path.join(HERE, 'data')
REPORTS = os.path.join(DATA, 'reports')
ACCOUNTS_FILE = os.path.join(DATA, 'accounts.json')
STATE_FILE = os.path.join(DATA, 'state.json')
SETTINGS_FILE = os.path.join(DATA, 'settings.json')
RULES_FILE = os.path.join(DATA, 'rules.json')
UNSUBS_FILE = os.path.join(DATA, 'unsubscribe.json')
ALERTS_TASK = 'MailBrief Alerts'
LEDGER_FILE = os.path.join(DATA, 'receipts.json')
HISTORY_FILE = os.path.join(DATA, 'history.json')
RECEIPTS_DIR = os.path.join(HERE, 'קבלות')
FORWARD_LOG = os.path.join(DATA, 'forward-log.json')
MAX_FORWARDS_PER_RUN = 20
WAIT_DAYS = 3
FOLLOWUP_DAYS = 4                # my own sent mail with no answer after this many days
PORT = 8765                     # always open: Google / Microsoft sign-in returns here
NICE_HOST = 'mailbrief.localhost'
NICE_PORT = 80                  # http://mailbrief.localhost without a port, when free
DAYS = 7
MAX_MESSAGES = 400
TASK_NAME = 'MailBrief'
SNAPSHOT_FILE = os.path.join(DATA, 'today.json')
CACHE_FILE = os.path.join(DATA, 'cache.json')
URL_FILE = os.path.join(DATA, 'url.txt')
NOTES_FILE = os.path.join(DATA, 'notes.json')
INSIGHTS_FILE = os.path.join(DATA, 'insights.json')
OUTBOX_FILE = os.path.join(DATA, 'outbox.json')
TRIAGE_FILE = os.path.join(DATA, 'triage.json')
SNOOZE_FILE = os.path.join(DATA, 'snoozed.json')
MAX_UPLOAD = 20_000_000       # attachments in one form (Gmail's limit is 25MB after encoding)
REMINDERS_FILE = os.path.join(DATA, 'reminders.json')
DOWNLOADS_DIR = os.path.join(HERE, 'הורדות')
MAX_VACATION_REPLIES = 30
BACKUP_DIR = os.path.join(HERE, 'גיבויים')
KEEP_BACKUPS = 10
ARCHIVE_DIR = os.path.join(HERE, 'ארכיון')
ARCHIVE_MANIFEST = os.path.join(DATA, 'archive.json')
WF_FILE = os.path.join(DATA, 'automations.json')
WF_LOG = os.path.join(DATA, 'automation-log.json')
WF_ROWS = os.path.join(DATA, 'automation-rows.json')
WF_DIR = os.path.join(HERE, 'יומני אוטומציה')
MAX_WORKFLOW_RUNS = 40
MAX_AUTO_REPLIES = 10
