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


# The 🥠 line at the top of "My day": one a day, in turn (by the day of the year). A tuple = feminine, masculine, neutral.
FORTUNES = [
    'היום תיבת הדואר תתרוקן עוד לפני הצהריים 📭', 'כל לקוח יענה כבר על המייל הראשון.', 'הקבלות יגיעו בזמן — ומסודרות.',
    'מייל אחד טוב שווה עשר שיחות טלפון.', 'מה שנראה דחוף בבוקר — חצי ממנו יסתדר לבד עד הצהריים.',
    ('את לא חייבת לענות לכל מייל היום. רק לחשובים.', 'אתה לא חייב לענות לכל מייל היום. רק לחשובים.', 'לא חייבים לענות לכל מייל היום. רק לחשובים.'),
    'הפיצ׳ר הכי טוב של היום: הפסקת קפה ☕', 'חשבונית שנשלחת היום — משולמת מוקדם יותר.', 'התשובה הכי טובה היא לפעמים הקצרה ביותר.',
    ('מי שמסדרת את המייל בבוקר — מרוויחה את כל היום.', 'מי שמסדר את המייל בבוקר — מרוויח את כל היום.', 'מסדרים את המייל בבוקר — ומרוויחים את כל היום.'),
    'ניוזלטר שלא נפתח חודשיים — כנראה שאפשר לבטל אותו.', 'שבוע טוב מתחיל בתיבה נקייה.', 'כל „אחזור אליך” שמתקיים — בונה אמון.',
    'היום אף אחד לא ישלח „ראית את המייל שלי?”', 'מייל ששלחת עם כל הפרטים חוסך שלושה מיילים של שאלות.',
    'לפני השבת: תיבה מסודרת, ראש שקט 🕯️', 'הסבלנות של היום היא הלקוח המרוצה של מחר.', 'הדבר הכי קשה ברשימה — כדאי לעשות ראשון.',
    ('את עושה עבודה מצוינת — גם אם אף אחד לא אמר את זה היום.', 'אתה עושה עבודה מצוינת — גם אם אף אחד לא אמר את זה היום.', 'עבודה מצוינת — גם אם אף אחד לא אמר את זה היום.'),
    'הקובץ המצורף באמת יהיה מצורף. בפעם הראשונה.', 'מה שמתוזמן לאחרי שבת — יחכה בסבלנות.', 'מספיק לענות היום לשלושה מיילים שממתינים הכי הרבה.',
    'עשר דקות של מיון מהיר שוות שעה של חיפושים.', 'היום הסיסמה תתקבל בניסיון הראשון 🔑', 'תודה קטנה במייל עושה יום גדול למישהו אחר.',
    'מייל שלא עונים עליו בשישי — עדיין יחכה בראשון, וזה בסדר.', 'כל קבלה במקום — רואה החשבון מחייך.', 'גם „לא” מנומס הוא תשובה מצוינת.',
    ('היום תספיקי יותר ממה שתכננת.', 'היום תספיק יותר ממה שתכננת.', 'היום נספיק יותר ממה שתוכנן.'), 'טלפון כבוי לשעה = עבודה של שלוש.',
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
