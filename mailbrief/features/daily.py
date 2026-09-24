"""The daily summary by email — "My day" in the inbox, readable on any phone (Shabbat and Yom Tov: nothing is sent)."""
import datetime as dt
from email.message import EmailMessage

from mailbrief import config
from mailbrief.address import link
from mailbrief.features import google_apps
from mailbrief.features.alerts import upcoming_payments
from mailbrief.features.invites import upcoming, when_text
from mailbrief.mail import smtp
from mailbrief.profile import profile
from mailbrief.storage import load_json
from mailbrief.util import e


DAYS = ['שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת', 'ראשון']


def daily_cfg():
    cfg = load_json(config.SETTINGS_FILE, {}).get('daily') or {}
    return {'on': bool(cfg.get('on')), 'hour': int(cfg.get('hour', 7)), 'account': cfg.get('account', '')}


def daily_account(accounts, cfg=None):
    cfg = cfg or daily_cfg()
    return next((a for a in accounts if a['email'].lower() == cfg['account'].lower()), accounts[0] if accounts else None)


def build_daily(now=None):
    """(subject, plain text, html). Short: only what needs attention today."""
    now = now or dt.datetime.now()
    snap = load_json(config.SNAPSHOT_FILE, {})
    sections = []

    def section(title, rows):
        if rows:
            sections.append((title, rows))
    section('🔥 דחוף', [(u['subject'], f"{u['from']} · {u['why']}", u.get('link', '')) for u in snap.get('urgent', [])[:5]])
    gapps = None
    try:
        gapps = google_apps.today_overview()
    except Exception:
        pass
    if gapps:
        section('📅 היום ביומן', [(ev['title'], ev['time'] + (f"–{ev['end']}" if ev['end'] else '') + (f" · {ev['where']}" if ev['where'] else ''),
                                   ev.get('link', '')) for ev in gapps.get('events', [])])
        today = now.date().isoformat()
        section('✅ משימות להיום', [(t['title'], 'באיחור!' if t['due'] < today else 'היום', t.get('link', ''))
                                   for t in gapps.get('tasks', []) if t['due'] and t['due'] <= today])
    section('💸 לתשלום בקרוב', [(p['subject'], f"{p['from']} · {p.get('amount', '')} · עד {p['due'][8:10]}/{p['due'][5:7]}", p.get('link', ''))
                               for p in upcoming_payments(days=3)])
    section('📨 הזמנות לפגישות', [(i['title'], f"{when_text(i)} · מאת {i['from']}", i.get('link', ''))
                                 for i in snap.get('invites', []) if upcoming(i)][:4])
    section('⏳ מחכים לתשובה ממך', [(w['subject'], f"{w['from']} · {w['days']} ימים", w.get('link', '')) for w in snap.get('waiting', [])[:5]])
    section('📤 מחכה לתשובה מהם', [(w['subject'], f"אל {w['to']} · {w['days']} ימים", w.get('link', '')) for w in snap.get('awaiting', [])[:4]])
    reminders = [r for r in load_json(config.REMINDERS_FILE, []) if r['due'][:10] <= now.date().isoformat()]
    section('⏰ תזכורות', [(r['subject'], r['from'], r.get('link', '')) for r in reminders[:5]])
    from mailbrief.money.books import missing_invoices
    section('🧾 חשבונית שעוד לא הגיעה', [(f"{m['vendor']}", f"מגיעה בדרך כלל עד ה-{m['day']} לחודש · אחרונה {m['last'][8:10]}/{m['last'][5:7]}", '')
                                        for m in missing_invoices(today=now.date())[:5]])
    from mailbrief.features.clientcare import debts
    section('💰 לקוחות שעוד לא שילמו', [(f"{d['name']} — {d['amount']}".strip(' —'), f"חשבונית {d['invoice']} · לתשלום עד {d['due'][8:10]}/{d['due'][5:7]}", '')
                                       for d in debts() if d['status'] == 'open' and d['due'] <= now.date().isoformat()][:5])
    from mailbrief.features.meetings import holiday_lines, holiday_prep
    try:
        prep = holiday_prep(now.astimezone())
    except Exception:
        prep = None
    if prep:
        section(f"🕯️ לפני {prep['name'] or 'החג'} — מה כדאי לסגור", [(line, '', '') for line in holiday_lines(prep)])
    from mailbrief.money.budget import budget_status
    section('📊 תקציב החודש', [(f"{b['book']}: ₪{b['spent']:,.0f} מתוך ₪{b['budget']:,.0f}", f"{b['pct']}%" + (' — חריגה!' if b['over'] else ''), '')
                              for b in budget_status() if b['pct'] >= 80])
    if now.weekday() == 6:                           # Sunday: the week in numbers
        from mailbrief.features.digest import summary_lines, weekly_summary
        section('📊 השבוע שלך במספרים', [(line, '', '') for line in summary_lines(weekly_summary(now.date()))])

    name = profile().get('name', '')
    greet = 'בוקר טוב' if now.hour < 12 else 'צהריים טובים' if now.hour < 17 else 'ערב טוב'
    subject = f"☀️ היום שלך — יום {DAYS[now.weekday()]} {now:%d/%m}" + ('' if sections else ' · הכול רגוע ✨')
    text = [f'{greet}{", " + name if name else ""}!', '']
    html = [f'<div dir="rtl" style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#1d1a24;line-height:1.5">'
            f'<div style="background:linear-gradient(90deg,#7c3aed,#f97316);color:#fff;border-radius:16px;padding:18px 20px">'
            f'<div style="font-size:26px">📬</div><div style="font-size:22px;font-weight:bold">{e(greet)}{", " + e(name) if name else ""}!</div>'
            f'<div style="opacity:.9">יום {DAYS[now.weekday()]}, {now:%d/%m/%Y}</div></div>']
    if not sections:
        text.append('אין היום משהו שדורש תשומת לב ✨')
        html.append('<p style="font-size:17px;text-align:center;padding:20px">אין היום משהו שדורש תשומת לב ✨</p>')
    for title, rows in sections:
        text += [title] + [f'• {t} — {sub}' + (f'\n  {url}' if url.startswith('https://') else '') for t, sub, url in rows] + ['']
        html.append(f'<h3 style="margin:20px 0 6px;font-size:17px">{e(title)}</h3>' + ''.join(
            '<div style="background:#fbf7f2;border:1px solid #ebe4dc;border-radius:12px;padding:10px 12px;margin-bottom:6px">'
            + (f'<a href="{e(url)}" style="color:#7c3aed;font-weight:bold;text-decoration:none">{e(t[:90])}</a>' if url.startswith('https://') else f'<b>{e(t[:90])}</b>')
            + f'<div style="color:#6b6475;font-size:13px">{e(sub)}</div></div>' for t, sub, url in rows))
    html.append(f'<p style="color:#6b6475;font-size:12px;text-align:center;margin-top:24px">נשלח מ-MailBrief שבמחשב שלך · '
                f'<a href="{e(link("today"))}" style="color:#7c3aed">פתיחת „היום שלי”</a> (במחשב)</p></div>')
    return subject, '\n'.join(text), ''.join(html)


def send_daily(acc, now=None):
    subject, text, html = build_daily(now)
    msg = EmailMessage()
    msg['From'] = msg['To'] = acc['email']
    msg['Subject'] = subject
    msg['X-MailBrief-Forwarded'] = '1'               # our own message: automations and alerts ignore it
    msg.set_content(text)
    msg.add_alternative(html, subtype='html')
    smtp.send_mail(acc, msg)
    return subject


def maybe_send_daily(state, accounts, now=None):
    """Called from the hourly check (which never runs on Shabbat / Yom Tov): once a day, from the chosen hour."""
    cfg, now = daily_cfg(), now or dt.datetime.now()
    today = now.date().isoformat()
    if not cfg['on'] or not accounts or state.get('_daily') == today or now.hour < cfg['hour']:
        return None
    acc = daily_account(accounts, cfg)
    subject = send_daily(acc, now)
    state['_daily'] = today
    return subject
