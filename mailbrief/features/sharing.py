"""A weekly report to a partner or an employee: every Sunday morning, what happened last week with the chosen
labels (clients) — who wrote, about what, and what is still waiting. Sent from your mailbox; never on Shabbat / Yom Tov
(it runs from the hourly check, which doesn't run then). Only the chosen labels are shared — nothing else."""
import datetime as dt
from email.message import EmailMessage

from mailbrief import config
from mailbrief.mail import smtp
from mailbrief.profile import profile
from mailbrief.storage import load_json
from mailbrief.util import e


def share_cfg():
    cfg = load_json(config.SETTINGS_FILE, {}).get('share') or {}
    return {'on': bool(cfg.get('on')), 'email': cfg.get('email', ''), 'name': cfg.get('name', ''),
            'labels': cfg.get('labels') or [], 'account': cfg.get('account', '')}


def build_share(cfg=None, today=None):
    """(subject, text, html, count)"""
    cfg, today = cfg or share_cfg(), today or dt.date.today()
    since = (today - dt.timedelta(days=7)).isoformat()
    labels = set(cfg['labels'])
    rows = sorted((h for h in load_json(config.HISTORY_FILE, {}).values()
                   if h['date'] >= since and set(h.get('rules', [])) & labels), key=lambda h: h['date'])
    waiting = [h for h in rows if h.get('answered') is False]
    me = profile().get('name', '') or 'MailBrief'
    subject = f'📋 סיכום שבועי — {", ".join(sorted(labels))} · {today:%d/%m}'
    hello = f'שלום {cfg["name"]},' if cfg['name'] else 'שלום,'
    text = [hello, '', f'השבוע: {len(rows)} מיילים, {len(waiting)} עדיין ממתינים לתשובה.', '']
    text += [f"• {h['date'][8:10]}/{h['date'][5:7]} {h.get('name') or h['sender']} — {h.get('subject', '')}"
             + (' ⏳' if h.get('answered') is False else '') for h in rows[-60:]]
    text += ['', f'נשלח מ-MailBrief של {me}']
    html = (f'<div dir="rtl" style="font-family:Arial,sans-serif;max-width:640px;color:#1d1a24"><p>{e(hello)}</p>'
            f'<p>השבוע: <b>{len(rows)}</b> מיילים, <b>{len(waiting)}</b> עדיין ממתינים לתשובה.</p>'
            '<table style="border-collapse:collapse;width:100%;font-size:14px">' + ''.join(
                f'<tr><td style="padding:4px 8px;border-bottom:1px solid #eee;white-space:nowrap">{h["date"][8:10]}/{h["date"][5:7]}</td>'
                f'<td style="padding:4px 8px;border-bottom:1px solid #eee">{e(h.get("name") or h["sender"])}</td>'
                f'<td style="padding:4px 8px;border-bottom:1px solid #eee">{e(h.get("subject", ""))}</td>'
                f'<td style="padding:4px 8px;border-bottom:1px solid #eee">{"⏳ ממתין" if h.get("answered") is False else ""}</td></tr>'
                for h in rows[-60:]) + f'</table><p style="color:#6b6475;font-size:12px">נשלח מ-MailBrief של {e(me)}</p></div>')
    return subject, '\n'.join(text), html, len(rows)


def send_share(accounts, cfg=None):
    cfg = cfg or share_cfg()
    acc = next((a for a in accounts if a['email'].lower() == cfg['account'].lower()), accounts[0] if accounts else None)
    if not acc or not cfg['email'] or not cfg['labels']:
        raise RuntimeError('צריך נמען ולפחות תווית אחת')
    subject, text, html, count = build_share(cfg)
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = acc['email'], cfg['email'], subject
    msg['X-MailBrief-Forwarded'] = '1'
    msg.set_content(text)
    msg.add_alternative(html, subtype='html')
    smtp.send_mail(acc, msg)
    return count


def maybe_share(state, accounts, now=None):
    """Sunday from 08:00, once a week."""
    cfg, now = share_cfg(), now or dt.datetime.now()
    week = now.strftime('%G-%V')
    if not cfg['on'] or now.weekday() != 6 or now.hour < 8 or state.get('_share') == week:
        return None
    count = send_share(accounts, cfg)
    state['_share'] = week
    return count
