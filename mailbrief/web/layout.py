"""Shared page layout, CSS and the tab bar (same look as the "surprise box" page)."""

from mailbrief.web.icon import FAVICON
from mailbrief.util import e
from mailbrief import __version__
from mailbrief.profile import profile, welcome_back
from mailbrief.web import extras
from mailbrief import view


STYLE = """
:root{--bg:#fbf7f2;--surface:#ffffff;--ink:#1d1a24;--muted:#6b6475;--line:#ebe4dc;--accent:#7c3aed;--accent-2:#f97316;--warn:#ea580c;--bad:#dc2626;--good:#16a34a;--shadow:0 10px 30px rgba(40,20,60,.08);--glass:rgba(251,247,242,.86);--oval:rgba(124,58,237,.10);color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14121a;--surface:#1e1b26;--ink:#f3eff8;--muted:#a39cb0;--line:#2e2a38;--accent:#a78bfa;--accent-2:#fb923c;--warn:#fb923c;--bad:#f87171;--good:#4ade80;--shadow:0 10px 30px rgba(0,0,0,.35);--glass:rgba(20,18,26,.86);--oval:rgba(167,139,250,.13);color-scheme:dark}}
:root[data-theme=dark]{--bg:#14121a;--surface:#1e1b26;--ink:#f3eff8;--muted:#a39cb0;--line:#2e2a38;--accent:#a78bfa;--accent-2:#fb923c;--warn:#fb923c;--bad:#f87171;--good:#4ade80;--shadow:0 10px 30px rgba(0,0,0,.35);--glass:rgba(20,18,26,.86);--oval:rgba(167,139,250,.13);color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);font-family:Rubik,system-ui,sans-serif;line-height:1.5;min-height:100vh;background-color:var(--bg);
background-image:radial-gradient(ellipse 46% 330px at 50% 0,var(--oval),transparent 100%);background-repeat:no-repeat}
body,main,.box,.item,.kpi,table,nav.tabs{transition:background-color .3s,border-color .3s,color .3s}
main{max-width:1040px;margin:0 auto 64px;padding:24px;background:var(--surface);border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow);animation:rise .35s ease}a{color:var(--accent)}
@media(max-width:760px){main{margin:0 8px 40px;padding:20px 14px 28px;border-radius:20px}}
main.swap{animation:rise .35s ease}main.fading{opacity:.5;filter:saturate(.7);transition:opacity .2s,filter .2s}
@keyframes rise{from{opacity:0;transform:translateY(8px)}}
h1{font-size:24px;font-weight:700;margin:0 0 4px}main h1 .g{background:none;color:inherit}
.g{background:linear-gradient(90deg,var(--accent),var(--accent-2));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{font-size:24px;margin:40px 0 8px;direction:ltr;text-align:right}h3{font-size:19px;margin:24px 0 10px}
.muted{color:var(--muted)}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:14px;box-shadow:var(--shadow)}.kpi b{font-size:30px;display:block}.kpi span{color:var(--muted)}
.item{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin-bottom:8px;transition:border-color .15s}
.item:hover{border-color:color-mix(in srgb,var(--accent) 40%,var(--line))}
.item.bad{border-color:var(--bad);box-shadow:inset 4px 0 0 var(--bad)}.item.urgent{border-color:var(--warn);box-shadow:inset 4px 0 0 var(--warn)}
.item .t{font-weight:500}.item .m{color:var(--muted);font-size:13px}.item .s{font-size:14px;color:var(--muted);margin-top:4px;overflow-wrap:anywhere}
.box{box-shadow:var(--shadow);border-radius:20px!important;transition:transform .15s,box-shadow .15s}
.pill{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:1px 9px;margin-inline-start:6px;white-space:nowrap}
.pill.bad{color:var(--bad);border-color:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:var(--shadow)}
th,td{text-align:start;padding:9px 12px;border-bottom:1px solid var(--line);font-size:14px}th{color:var(--muted);font-weight:500;background:var(--bg)}
.scroll{overflow-x:auto}.err{background:var(--surface);border:1px solid var(--bad);color:var(--bad);border-radius:14px;padding:12px 16px}
.hero{position:relative;text-align:center;padding:48px 16px 24px;max-width:1040px;margin:0 auto}
.hero .gift{font-size:72px;cursor:pointer;display:inline-block;text-decoration:none;animation:wobble 2.4s ease-in-out infinite;user-select:none}
@keyframes wobble{0%,100%{transform:rotate(0)}20%{transform:rotate(-12deg) scale(1.05)}40%{transform:rotate(10deg)}60%{transform:rotate(-6deg)}}
.hero h1.name{background:linear-gradient(90deg,var(--accent),var(--accent-2));-webkit-background-clip:text;background-clip:text;color:transparent;}
.hero .name{font-size:clamp(32px,6vw,56px);font-weight:900;margin:8px 0 4px;letter-spacing:-.5px;line-height:1.2}
.hero .tag{color:var(--muted);font-size:18px;margin:0;min-height:28px}
.caret{display:inline-block;width:2px;height:1em;background:var(--accent);vertical-align:-2px;margin-inline-start:2px;animation:blink 1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.hero .corner{position:absolute;top:14px;inset-inline-end:16px;display:flex;gap:6px;align-items:center}
nav.tabs{position:sticky;top:0;z-index:5;display:flex;gap:8px;justify-content:center;flex-wrap:wrap;padding:10px 16px;margin:0 0 14px;transition:background-color .2s}
nav.tabs.stuck{background:var(--glass);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:0 1px 0 var(--line)}
nav.tabs a{font-size:16px;border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:10px 18px;border-radius:999px;text-decoration:none;
transition:.15s;white-space:nowrap}
nav.tabs a:hover{border-color:var(--accent);transform:translateY(-1px)}
nav.tabs a.on{background:var(--accent);color:#fff;border-color:var(--accent);box-shadow:0 6px 18px color-mix(in srgb,var(--accent) 35%,transparent)}
.mbxs{display:flex;gap:6px;justify-content:center;flex-wrap:wrap;margin:-4px 16px 16px}
.mbx{font:inherit;font-size:13px;border:1px dashed var(--line);background:transparent;color:var(--muted);padding:4px 12px;border-radius:999px;cursor:pointer;margin:0}
.mbx:hover{border-color:var(--accent);color:var(--ink);filter:none}.mbx.on{border-style:solid;border-color:var(--accent);color:var(--ink);background:var(--surface);font-weight:500}
@media(max-width:760px){nav.tabs{flex-wrap:nowrap;overflow-x:auto;justify-content:flex-start;scrollbar-width:none}nav.tabs::-webkit-scrollbar{display:none}
.hero{padding-top:56px}.hero .gift{font-size:48px}.hero .tag{font-size:16px}}
button{transition:filter .15s,transform .1s}button:hover:not(:disabled){filter:brightness(1.08)}button:active:not(:disabled){transform:scale(.97)}
button:disabled{opacity:.5;cursor:default}
button.ghost{background:transparent!important;color:var(--ink)!important;border:1px solid var(--line)!important}button.ghost:hover:not(:disabled){border-color:var(--accent)!important;filter:none}
main .kpi,main .item,main .box{background:var(--bg)!important;box-shadow:none}main .item.urgent{box-shadow:inset 4px 0 0 var(--warn)}main .item.bad{box-shadow:inset 4px 0 0 var(--bad)}main .kpi{border-radius:12px}
main .box:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--accent) 45%,var(--line))!important}
footer.foot{text-align:center;color:var(--muted);margin-top:40px;font-size:13px}
"""


FONT = ('<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;700;900&display=swap" rel="stylesheet">'
        + FAVICON + extras.BOOT)


TABS = [('/today', '☀️', 'היום שלי'), ('/', '⚙️', 'הגדרות'), ('/dashboard', '📊', 'לוח בקרה'), ('/stats', '📈', 'במספרים'),
        ('/automations', '⚡', 'אוטומציות'), ('/clients', '👥', 'לקוחות'), ('/reading', '📰', 'ניוזלטרים'),
        ('/search', '🔍', 'חיפוש'), ('/help', '❓', 'מדריך')]


TITLE_TAB = {'היום שלי': '/today', 'לוח בקרה': '/dashboard', 'המייל שלי במספרים': '/stats', 'אוטומציות': '/automations',
             'לקוחות': '/clients', 'לקוח': '/clients', 'רשימת קריאה': '/reading', 'ניוזלטרים': '/reading', 'חיפוש': '/search', 'מדריך': '/help',
             'בדיקת תקינות': '/help', '30 הימים שלך': '/today', 'מיון מהיר': '/today', 'מייל מתוזמן': '/today', 'ברכות חג': '/today'}


def top_bar(active=''):
    """Like the surprise box: a hero (wobbling envelope, gradient name, typed line), then centered pill tabs."""
    tabs = ''.join(f'<a href="{path}"{" class=on" if path == active else ""}>{icon} {label}</a>' for path, icon, label in TABS)
    me = profile()
    return (f'<style>{extras.STYLE}</style><header class="hero"><div class="corner">'
            '<button class="tbtn" id="mb-theme" type="button" onclick="MB.theme()">🌗</button>'
            '<button class="kbtn" type="button" onclick="MB.open()" title="מעבר מהיר לכל דף ופעולה">⌨️ Ctrl+K</button>'
            '<button class="fchip" id="mb-focus" type="button" title="טיימר ריכוז — לחיצה לפתיחה"></button></div>'
            f'<span class="gift" id="mb-gift" title="🎉">📬</span><h1 class="name g" id="mb-hello" data-name="{e(me.get("name", ""))}" '
            f'data-back="{e(welcome_back() if me.get("form") else "")}">שלום!</h1>'
            '<p class="tag"><span id="mb-type"></span><span class="caret"></span></p></header>'
            f'<nav class="tabs" id="mb-tabs">{tabs}</nav>{view.switcher()}')


def update_banner():
    """A friendly "new version" strip; quiet when offline or when running from source."""
    from mailbrief.features.update import can_self_update, update_available
    from mailbrief.web.token import TOKEN
    try:
        rel = update_available()
    except Exception:
        rel = None
    if not rel:
        return ''
    action = (f'<form method="post" action="/update" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
              '<button style="margin:0 8px;padding:7px 16px">✨ עדכון עכשיו</button></form>' if can_self_update() else
              '<code dir="ltr" style="margin:0 8px">winget upgrade mailbrief</code>')
    return (f'<div class="item" style="border-color:var(--accent);display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
            f'🎁 <b>גרסה חדשה {e(rel["version"])} זמינה</b> <span class="muted">(עכשיו {__version__})</span>{action}'
            f'<a href="{e(rel["page"])}" target="_blank" class="muted" style="font-size:13px">מה חדש?</a></div>')


def heading(icon, text):
    """Page title: the emoji stays in color, the words get the purple→orange gradient."""
    return f'<h1>{icon} <span class="g">{e(text)}</span></h1>'


def page(title, body, active=''):
    return (f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(title)} · MailBrief</title>{FONT}'
            f'<style>{STYLE}.bar{{height:20px;background:linear-gradient(90deg,var(--accent),var(--accent-2));border-radius:6px;min-width:3px}}'
            'input[type=search]{width:100%;font:inherit;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--ink)}'
            'button{font:inherit;border:0;background:var(--accent);color:#fff;padding:12px 22px;border-radius:12px;cursor:pointer;font-weight:500}</style>'
            f'</head><body>{top_bar(active or TITLE_TAB.get(title, ""))}<main>{body}</main>{extras.HTML}</body></html>')
