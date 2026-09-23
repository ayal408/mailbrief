"""Data for "My day": weather codes, fortunes, project status."""
import datetime as dt
import os
import subprocess

from mailbrief import config
from mailbrief.storage import load_json, save_json


SKIP_DIRS = {'node_modules', '.venv', 'venv', '__pycache__', '.git', 'dist', 'build'}


def projects_root():
    """The folder whose git projects appear on "My day" — a setting (settings.json: projects_root), empty = hidden."""
    return load_json(config.SETTINGS_FILE, {}).get('projects_root', '')


def find_projects(root, depth=2):
    """Git repositories directly under the root folder (or one level deeper)."""
    found = []
    try:
        entries = sorted(os.scandir(root), key=lambda d: d.name.lower())
    except OSError:
        return found
    for entry in entries:
        if not entry.is_dir() or entry.name in SKIP_DIRS or entry.name.startswith('.'):
            continue
        if os.path.isdir(os.path.join(entry.path, '.git')):
            found.append(entry.path)
        elif depth > 1:
            found += find_projects(entry.path, depth - 1)
    return found


WEATHER = [(0, '☀️', 'בהיר'), (3, '🌤️', 'מעונן חלקית'), (48, '🌫️', 'ערפל'), (57, '🌦️', 'טפטוף'), (67, '🌧️', 'גשם'),
           (77, '❄️', 'שלג'), (82, '🌧️', 'ממטרים'), (99, '⛈️', 'סופת רעמים')]


FORTUNES = [
    'ההתאמה הבנקאית תיסגר היום בניסיון הראשון.', 'הבאג שמחפשים נמצא בשורה 42. תמיד בשורה 42.',
    'Docker יעלה בפעם הראשונה, בלי port is already allocated.', 'ה-div יתמרכז. גם אנכית. גם ב-RTL.',
    'המאזן יתאזן, הטסטים יעברו, וה-migration ירוץ בלי שגיאות.', 'הלקוח ישלח את כל הקבלות בזמן. ממוינות.',
    'הפיצ׳ר הכי טוב של היום: הפסקת קפה.', 'ה-.env לא ייכנס בטעות ל-git. אף פעם.', 'dbt run יעבור ירוק מההתחלה ועד הסוף.',
    ('מי שמנהלת 20 פרויקטים במקביל יכולה להכול.', 'מי שמנהל 20 פרויקטים במקביל יכול להכול.', 'מי שמנהלים 20 פרויקטים במקביל יכולים להכול.'), 'חובה מימין, זכות משמאל — ובקוד הכול הפוך. RTL זו דרך חיים.',
]


def project_pulse():
    cache = load_json(config.CACHE_FILE, {}).get('projects')
    if cache and dt.datetime.now().timestamp() - cache['at'] < 600:
        return cache['data']
    rows = []
    root = projects_root()
    for path in (find_projects(root) if root else []):
        rel = os.path.relpath(path, root).replace('\\', '/')
        def git(*args):
            try:
                return subprocess.run(['git', '-C', path, *args], capture_output=True, text=True, encoding='utf-8',
                                      errors='replace', timeout=15, creationflags=0x08000000).stdout.strip()
            except Exception:
                return ''
        dirty = len([l for l in git('status', '--porcelain').splitlines() if l.strip()])
        last = git('log', '-1', '--format=%cI')
        rows.append({'name': rel, 'branch': git('rev-parse', '--abbrev-ref', 'HEAD'), 'dirty': dirty, 'last': last[:10]})
    cache_all = load_json(config.CACHE_FILE, {})
    cache_all['projects'] = {'at': dt.datetime.now().timestamp(), 'data': rows}
    save_json(config.CACHE_FILE, cache_all)
    return rows
