"""Who is using MailBrief: a first name and how to address them (feminine / masculine / neutral) — asked once, on the first run."""
from mailbrief import config
from mailbrief.storage import load_json, save_json


FORMS = {'f': ('👩', 'בלשון נקבה'), 'm': ('👨', 'בלשון זכר'), 'n': ('🙂', 'בלשון ניטרלית')}


GOALS = {    # what matters to the user — "My day" shows these cards and keeps the rest one click away
    'replies': ('⏳', 'לא לפספס תשובות', 'מי מחכה לתשובה ממני, ולמי אני מחכה'),
    'money': ('🧾', 'קבלות וכסף', 'תשלומים קרובים, חיובים קבועים, אקסל חודשי'),
    'calendar': ('📅', 'יומן ומשימות', 'פגישות, הזמנות ומשימות של היום'),
    'news': ('📰', 'תיבה שקטה', 'פחות ניוזלטרים ופרסומות'),
    'focus': ('⏱️', 'ריכוז וסדר', 'טיימר ריכוז, פתקים ותזכורות'),
}
DEFAULT_GOALS = ['replies', 'money', 'calendar']


def profile():
    return load_json(config.SETTINGS_FILE, {}).get('profile') or {}


def has_profile():
    return bool(profile().get('form'))


def goals():
    chosen = profile().get('goals')
    return list(GOALS) if chosen is None else [x for x in chosen if x in GOALS]


def save_profile(name, form, chosen_goals=None):
    settings = load_json(config.SETTINGS_FILE, {})
    old = settings.get('profile') or {}
    settings['profile'] = {'name': ' '.join(name.split())[:30], 'form': form if form in FORMS else 'n',
                           'goals': [x for x in chosen_goals if x in GOALS] if chosen_goals is not None else old.get('goals', DEFAULT_GOALS)}
    save_json(config.SETTINGS_FILE, settings)
    return settings['profile']


def g(fem, masc, neutral=None, form=None):
    """The wording that fits the user: g('שימי לב', 'שים לב', 'לתשומת לב')."""
    form = form or profile().get('form', 'n')
    return fem if form == 'f' else masc if form == 'm' else (neutral if neutral is not None else masc)


def welcome_back(form=None):
    return g('ברוכה השבה', 'ברוך השב', 'טוב לראות אותך שוב', form)
