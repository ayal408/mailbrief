"""📝 A price quote as a PDF: items, quantity, price and VAT, with your business details and logo — made on this computer
(Edge, which comes with Windows, turns the page into a PDF), sent from your mailbox and added to quote tracking.
A quote, not a tax invoice: invoices must come from software registered with the Tax Authority."""
import base64
import datetime as dt
import os
import subprocess
import tempfile

from mailbrief import config
from mailbrief.money.books import VAT_RATE
from mailbrief.profile import profile
from mailbrief.storage import load_json, save_json
from mailbrief.util import e, safe_name


EDGE = [r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', r'C:\Program Files\Microsoft\Edge\Application\msedge.exe']


def folder():
    return os.path.join(config.HERE, 'הצעות מחיר')


def next_number(peek=False):
    settings = load_json(config.SETTINGS_FILE, {})
    number = int(settings.get('quote_no', 1000)) + 1
    if not peek:
        settings['quote_no'] = number
        save_json(config.SETTINGS_FILE, settings)
    return number


def totals(items, vat=True):
    """items: [(description, quantity, price)] -> (lines [(desc, qty, price, sum)], before VAT, VAT, total)."""
    lines = [(d.strip(), q, p, round(q * p, 2)) for d, q, p in items if d.strip() and q > 0]
    net = round(sum(s for *_, s in lines), 2)
    tax = round(net * VAT_RATE / 100, 2) if vat else 0.0
    return lines, net, tax, round(net + tax, 2)


def quote_html(number, client, items, vat=True, notes='', valid_days=30, account=''):
    lines, net, tax, total = totals(items, vat)
    me = profile()
    acc = next((a for a in load_json(config.ACCOUNTS_FILE, []) if a['email'] == account), {})
    logo = ''
    if acc.get('signature_logo'):
        from mailbrief.features.outbox import logo_path
        if os.path.isfile(logo_path(acc)):
            with open(logo_path(acc), 'rb') as f:
                logo = f'<img src="data:image/{acc["signature_logo"]};base64,{base64.b64encode(f.read()).decode()}" alt="" class="logo">'
    today = dt.date.today()
    rows = ''.join(f'<tr><td>{n}</td><td>{e(d)}</td><td>{q:g}</td><td>₪{p:,.2f}</td><td>₪{s:,.2f}</td></tr>'
                   for n, (d, q, p, s) in enumerate(lines, 1))
    who = me.get('business') or me.get('name') or ''
    contact = ' · '.join(x for x in (account, (acc.get('signature_links') or {}).get('site', '')) if x)
    return f'''<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><title>הצעת מחיר {number}</title><style>
@page{{size:A4;margin:16mm}} body{{font-family:Arial,sans-serif;color:#1d1a24;font-size:13px}}
.top{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #7c3aed;padding-bottom:12px}}
.logo{{max-height:70px;max-width:200px}} h1{{color:#7c3aed;margin:0;font-size:26px}} .muted{{color:#6b6475}}
table{{width:100%;border-collapse:collapse;margin-top:18px}} th{{background:#f3effa;text-align:right;padding:8px}} td{{padding:8px;border-bottom:1px solid #ebe4dc}}
.sum{{width:280px;margin-inline-start:auto;margin-top:12px}} .sum div{{display:flex;justify-content:space-between;padding:4px 0}}
.total{{font-size:18px;font-weight:700;border-top:2px solid #1d1a24;margin-top:4px;padding-top:6px}}
.notes{{margin-top:22px;white-space:pre-wrap}} .foot{{margin-top:30px;font-size:11px}}</style></head><body>
<div class="top"><div><h1>הצעת מחיר</h1><div class="muted">מס׳ {number} · {today:%d/%m/%Y}</div>
<div style="margin-top:10px"><b>לכבוד:</b> {e(client.get("name") or "")}<br><span dir="ltr">{e(client.get("email") or "")}</span></div></div>
<div style="text-align:left">{logo}<div><b>{e(who)}</b></div><div class="muted" dir="ltr">{e(contact)}</div></div></div>
<table><thead><tr><th>#</th><th>תיאור</th><th>כמות</th><th>מחיר ליחידה</th><th>סה״כ</th></tr></thead><tbody>{rows}</tbody></table>
<div class="sum"><div><span>לפני מע״מ</span><span>₪{net:,.2f}</span></div>
{f'<div><span>מע״מ {VAT_RATE:g}%</span><span>₪{tax:,.2f}</span></div>' if vat else '<div class="muted"><span>לא כולל מע״מ (עוסק פטור)</span><span></span></div>'}
<div class="total"><span>סה״כ לתשלום</span><span>₪{total:,.2f}</span></div></div>
{f'<div class="notes"><b>הערות:</b>\n{e(notes)}</div>' if notes.strip() else ''}
<div class="foot muted">ההצעה בתוקף {valid_days} ימים, עד {today + dt.timedelta(days=valid_days):%d/%m/%Y}. זו הצעת מחיר ואינה חשבונית מס.</div>
</body></html>''', total


def edge_path():
    return next((p for p in EDGE if os.path.isfile(p)), '')


def html_to_pdf(html):
    """The page as PDF bytes, printed by Edge in the background."""
    edge = edge_path()
    if not edge:
        raise RuntimeError('לא נמצא Microsoft Edge במחשב — הוא נדרש ליצירת ה-PDF')
    with tempfile.TemporaryDirectory() as tmp:
        page, pdf = os.path.join(tmp, 'quote.html'), os.path.join(tmp, 'quote.pdf')
        with open(page, 'w', encoding='utf-8') as f:
            f.write(html)
        subprocess.run([edge, '--headless=new', '--disable-gpu', '--no-pdf-header-footer', f'--user-data-dir={os.path.join(tmp, "edge")}',
                        f'--print-to-pdf={pdf}', 'file:///' + page.replace('\\', '/')], capture_output=True, timeout=60, creationflags=0x08000000)
        if not os.path.isfile(pdf):
            raise RuntimeError('יצירת ה-PDF נכשלה')
        with open(pdf, 'rb') as f:
            return f.read()


def make_quote(account, client, items, vat=True, notes='', valid_days=30):
    """Creates the PDF in „הצעות מחיר”. Returns (path, number, total)."""
    if not any(d.strip() and q > 0 for d, q, p in items):
        raise ValueError('צריך לפחות פריט אחד')
    number = next_number()
    html, total = quote_html(number, client, items, vat, notes, valid_days, account)
    data = html_to_pdf(html)
    os.makedirs(folder(), exist_ok=True)
    path = os.path.join(folder(), safe_name(f'הצעת מחיר {number} - {client.get("name") or client.get("email", "")}')[:90] + '.pdf')
    with open(path, 'wb') as f:
        f.write(data)
    return path, number, total
