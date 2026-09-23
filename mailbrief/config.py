"""Paths and limits. Everything else reads these as config.NAME, so tests can redirect them in one place."""
import os
import sys

# The program folder: next to MailBrief.exe, or the project folder (one level above this package) when run from source.
HERE = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
PORT = 8765
DAYS = 7
MAX_MESSAGES = 400
TASK_NAME = 'MailBrief'
SNAPSHOT_FILE = os.path.join(DATA, 'today.json')
CACHE_FILE = os.path.join(DATA, 'cache.json')
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
