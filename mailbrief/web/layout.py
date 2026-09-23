"""Shared page layout and CSS."""

from mailbrief.web.icon import FAVICON
from mailbrief.util import e


STYLE = """
:root{--bg:#fbf7f2;--surface:#fff;--ink:#1d1a24;--muted:#6b6475;--line:#ebe4dc;--accent:#7c3aed;--warn:#ea580c;--bad:#dc2626;--good:#16a34a}
@media (prefers-color-scheme:dark){:root{--bg:#14121a;--surface:#1e1b26;--ink:#f3eff8;--muted:#a39cb0;--line:#2e2a38;--accent:#a78bfa;--warn:#fb923c;--bad:#f87171;--good:#4ade80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Rubik,system-ui,sans-serif;line-height:1.55}
main{max-width:980px;margin:0 auto;padding:32px 16px 64px}a{color:var(--accent)}
h1{font-size:38px;font-weight:900;margin:0}h2{font-size:24px;margin:40px 0 8px;direction:ltr;text-align:right}h3{font-size:19px;margin:24px 0 10px}
.muted{color:var(--muted)}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:14px}.kpi b{font-size:30px;display:block}.kpi span{color:var(--muted)}
.item{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin-bottom:8px}
.item.bad{border-color:var(--bad);box-shadow:inset 4px 0 0 var(--bad)}.item.urgent{border-color:var(--warn);box-shadow:inset 4px 0 0 var(--warn)}
.item .t{font-weight:500}.item .m{color:var(--muted);font-size:13px}.item .s{font-size:14px;color:var(--muted);margin-top:4px;overflow-wrap:anywhere}
.pill{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:1px 9px;margin-inline-start:6px;white-space:nowrap}
.pill.bad{color:var(--bad);border-color:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden}
th,td{text-align:start;padding:9px 12px;border-bottom:1px solid var(--line);font-size:14px}th{color:var(--muted);font-weight:500;background:var(--bg)}
.scroll{overflow-x:auto}.err{background:var(--surface);border:1px solid var(--bad);color:var(--bad);border-radius:14px;padding:12px 16px}
"""


FONT = '<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;700;900&display=swap" rel="stylesheet">' + FAVICON


def page(title, body):
    return (f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(title)}</title>{FONT}'
            f'<style>{STYLE}.bar{{height:20px;background:var(--accent);border-radius:6px;min-width:3px}}'
            'input[type=search]{width:100%;font:inherit;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--ink)}'
            'button{font:inherit;border:0;background:var(--accent);color:#fff;padding:10px 18px;border-radius:10px;cursor:pointer}</style>'
            f'</head><body><main><p><a href="/">→ חזרה ל-MailBrief</a></p>{body}</main></body></html>')
