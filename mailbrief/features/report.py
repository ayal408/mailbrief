"""The weekly HTML report."""
import datetime as dt
import os

from mailbrief import config
from mailbrief.features.unsubscribe import unsub_id
from mailbrief.mail.classify import CATS
from mailbrief.util import e
from mailbrief.web.layout import FONT, STYLE


def render_item(it, cls=''):
    title = e(it['subject'])
    if it.get('link'):
        title = f'<a href="{e(it["link"])}" target="_blank">{title}</a>'
    flag = '<span class="pill bad">חריג — לבדוק</span>' if it.get('unusual') else ''
    return (f'<div class="item {cls}"><div class="t">{title}{flag}</div>'
            f'<div class="m" dir="auto">{e(it["sender_name"])} · {e(it["date"])}</div>'
            f'<div class="s" dir="auto">{e(it["snippet"])}</div></div>')


def render_account(res):
    out = [f'<h2>{e(res["email"])}</h2>']
    if res['error']:
        return ''.join(out) + f'<div class="err">⚠️ {e(res["error"])}</div>'
    items = res['items']
    by = {c: [i for i in items if c in i['cats']] for c in CATS}
    out.append(f'<p class="muted">{len(items)} הודעות ב-{config.DAYS} הימים האחרונים · {res["tagged"]} תיוגים</p>')
    if by['phishing']:
        out.append('<h3>🎣 חשד לפישינג — לא ללחוץ על קישורים ולא לענות</h3>' + ''.join(
            render_item(i, 'bad').replace('</div></div>', '<div class="s" style="color:var(--bad)">⚠️ '
                                          + e(' · '.join(i.get('phish_why', []))) + '</div></div></div>', 1)
            for i in by['phishing']))
    if by['urgent']:
        out.append('<h3>🔥 דחוף</h3>' + ''.join(render_item(i, 'urgent') for i in by['urgent']))
    if by['people']:
        waiting = [i for i in by['people'] if i.get('answered') is False]
        out.append(f'<h3>👤 מאנשים{f" — {len(waiting)} ממתינים לתשובה" if waiting else ""}</h3>' + ''.join(
            render_item(i, 'urgent' if i.get('waiting_days', 0) >= config.WAIT_DAYS else '')
            .replace('</div></div>', ('<span class="pill">✓ נענה</span>' if i.get('answered') else
                                      f'<span class="pill">⏳ ממתין {i.get("waiting_days", 0)} ימים</span>'
                                      if i.get('answered') is False else '') + '</div></div>', 1)
            for i in sorted(by['people'], key=lambda i: -i.get('waiting_days', 0))))
    if by['receipts']:
        rows = ''.join(
            f'<tr><td dir="auto">{e(i["sender_name"])}</td><td dir="auto">'
            + (f'<a href="{e(i["link"])}" target="_blank">{e(i["subject"])}</a>' if i.get('link') else e(i['subject']))
            + f'</td><td dir="ltr">{e(i.get("amount", "—"))}</td><td>{e(i["book"])}</td><td>{e(i["date"])}</td>'
            + f'<td>{"📎" if i.get("files") else ""}'
            + (f' <span class="pill bad">⚠️ כפול? גם ב-{e(i["duplicate"])}</span>' if i.get('duplicate') else '') + '</td></tr>'
            for i in by['receipts'])
        out.append('<h3>🧾 קבלות וחיובים</h3><p class="muted" style="font-size:13px">📎 = נשמר בתיקיית „קבלות” ונכנס לאקסל החודשי.</p>'
                   '<div class="scroll"><table><thead><tr><th>ספק</th><th>נושא</th>'
                   f'<th>סכום</th><th>סיווג מוצע</th><th>תאריך</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>')
    if by['security']:
        out.append('<h3>🔐 אבטחה</h3>' + ''.join(render_item(i, 'bad' if i['unusual'] else '') for i in by['security']))
    if by['signins']:
        out.append('<h3>🔑 התחברויות לאפליקציות</h3><p class="muted">ניהול הגישות: '
                   '<a href="https://myaccount.google.com/connections" target="_blank">myaccount.google.com/connections</a></p>'
                   + ''.join(render_item(i) for i in by['signins']))
    labels = sorted({label for i in items for label in i.get('rules', [])})
    for label in labels:
        out.append(f'<h3>🏷️ {e(label)}</h3>' + ''.join(
            render_item(i, 'urgent' if i.get('notify') else '') for i in items if label in i.get('rules', [])))
    if by['newsletters']:
        senders = {}
        for i in by['newsletters']:
            s = senders.setdefault(i['sender'], {'name': i['sender_name'], 'count': 0, 'unsub': False})
            s['count'] += 1
            s['unsub'] = s['unsub'] or bool(i.get('unsub'))
        rows = ''.join(
            f'<tr><td dir="auto">{e(s["name"])}</td><td>{s["count"]}</td><td>'
            + (f'<a href="http://127.0.0.1:{config.PORT}/unsub?id={unsub_id(res["email"], addr)}" target="_blank">ביטול מנוי</a>'
               if s['unsub'] else '<span class="muted">—</span>') + '</td></tr>'
            for addr, s in sorted(senders.items(), key=lambda kv: -kv[1]['count']))
        out.append('<h3>📰 ניוזלטרים</h3><p class="muted" style="font-size:13px">„ביטול מנוי” עובד כש-MailBrief פתוח.</p>'
                   '<div class="scroll"><table><thead><tr><th>שולח</th><th>כמה</th><th></th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></div>')
    if not any(by.values()) and not labels:
        out.append('<p>שבוע שקט ✨</p>')
    return ''.join(out)


def write_report(results, subs=()):
    now = dt.datetime.now()
    all_items = [i for r in results for i in r['items']]
    n = lambda c: sum(1 for i in all_items if c in i['cats'])
    kpis = ''.join(f'<div class="kpi"><b>{v}</b><span>{k}</span></div>' for k, v in [
        ('תיבות', len(results)), ('הודעות', len(all_items)), ('🔥 דחוף', n('urgent')),
        ('⏳ ממתינים לתשובה', sum(1 for i in all_items if i.get('answered') is False)),
        ('🧾 קבלות', n('receipts')), ('🔐 אבטחה', n('security'))])
    new_subs = [s for s in subs if s['new']]
    if subs:
        kpis += (f'</div><h3>💳 מנויים וחיובים קבועים ({len(subs)})</h3>'
                 + (f'<div class="item urgent">חדש החודש: {e(", ".join(s["vendor"] for s in new_subs))}</div>' if new_subs else '')
                 + '<div class="scroll"><table><thead><tr><th>ספק</th><th>חיוב אחרון</th><th>תאריך</th><th>חודשים</th></tr></thead><tbody>'
                 + ''.join(f'<tr><td dir="auto">{e(s["vendor"])}</td><td dir="ltr">{e(s["currency"])}{s["amount"] if s["amount"] is not None else "—"}</td>'
                           f'<td>{e(s["last"])}</td><td>{s["months"]}</td></tr>' for s in subs)
                 + '</tbody></table></div><div>')
    page = (f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>תדריך מייל</title>{FONT}'
            f'<style>{STYLE}</style></head><body><main><h1>📬 תדריך מייל</h1>'
            f'<p class="muted">{now:%d/%m/%Y %H:%M} · {config.DAYS} ימים אחרונים · נוצר מקומית על ידי MailBrief</p>'
            f'<div class="kpis">{kpis}</div>{"".join(render_account(r) for r in results)}</main></body></html>')
    os.makedirs(config.REPORTS, exist_ok=True)
    path = os.path.join(config.REPORTS, f'brief-{now:%Y-%m-%d-%H%M}.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page)
    return path
