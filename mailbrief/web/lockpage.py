"""🔒 The screen shown instead of any page while MailBrief is locked."""
from mailbrief.util import e
from mailbrief.web.layout import FONT, STYLE
from mailbrief.web.token import TOKEN


def lock_page(target='/today', error=''):
    return f'''<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>נעול · MailBrief</title>{FONT}<style>{STYLE}
.lock{{max-width:360px;margin:12vh auto 0;text-align:center}}
.lock input{{font:inherit;font-size:28px;letter-spacing:10px;text-align:center;width:100%;padding:12px;border-radius:14px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}}
.lock button{{font:inherit;border:0;background:var(--accent);color:#fff;padding:12px 26px;border-radius:12px;cursor:pointer;margin-top:12px;width:100%}}</style></head>
<body><main class="lock"><div style="font-size:56px">🔒</div><h1>MailBrief נעול</h1>
<p class="muted">מקלידים את הקוד כדי להמשיך</p>
{f'<p style="color:var(--bad);font-weight:600" role="alert">{e(error)}</p>' if error else ''}
<form method="post" action="/unlock"><input type="hidden" name="t" value="{TOKEN}"><input type="hidden" name="next" value="{e(target)}">
<input type="password" name="pin" inputmode="numeric" autocomplete="off" maxlength="8" autofocus aria-label="קוד" required>
<button>פתיחה</button></form>
<p class="muted" style="font-size:12px;margin-top:24px">שכחת? <code dir="ltr">MailBrief.exe --reset-pin</code></p></main></body></html>'''
