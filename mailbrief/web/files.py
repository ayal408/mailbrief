"""📎 All attachments of the last month — filter by type and sender, download with one click."""
import datetime as dt

from mailbrief.features.files import KINDS, cached_files
from mailbrief.util import e
from mailbrief.view import current_account, mine
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


def files_page(msg=''):
    data = cached_files()
    box = current_account()
    rows = [r for r in data.get('rows', []) if mine(r, current=box)]
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    counts = {k: sum(1 for r in rows if r['kind'] == k) for k in list(KINDS) + ['other']}
    chips = ''.join(f'<button type="button" class="ghost fchip" data-kind="{k}" style="margin:0">{KINDS[k][0]} {KINDS[k][1]} ({counts[k]})</button>'
                    for k in KINDS if counts[k]) + (f'<button type="button" class="ghost fchip" data-kind="other" style="margin:0">📎 אחר ({counts["other"]})</button>'
                                                      if counts['other'] else '')
    table = ''
    for r in rows[:600]:
        when = f'{dt.datetime.fromisoformat(r["date"]):%d/%m}' if r['date'] else ''
        table += (f'<tr data-kind="{r["kind"]}" data-text="{e((r["name"] + " " + r["from"] + " " + r["sender"] + " " + r["subject"]).lower())}">'
                  f'<td>{KINDS.get(r["kind"], ("📎",))[0]} <b dir="auto">{e(r["name"])}</b>'
                  f'<div class="muted" dir="auto" style="font-size:12px">{e(r["subject"][:80])}</div></td>'
                  f'<td dir="auto">{e(r["from"])}</td><td style="white-space:nowrap">{when}</td><td style="white-space:nowrap">'
                  f'<form method="post" action="/file_get" style="display:inline;margin:0"><input type="hidden" name="t" value="{TOKEN}">'
                  f'<input type="hidden" name="account" value="{e(r["account"])}"><input type="hidden" name="message_id" value="{e(r["message_id"])}">'
                  f'<button class="ghost" style="margin:0;padding:4px 10px" title="הורדת כל הקבצים של המייל הזה">⬇️</button></form>'
                  + (f' <a href="{e(r["link"])}" target="_blank" title="פתיחה ב-Gmail">↗</a>' if r.get('link') else '') + '</td></tr>')
    return page('קבצים מצורפים', f'''{heading('📎', 'כל הקבצים המצורפים')}{note}
<p class="muted">כל הקבצים שהגיעו ב-{data.get("days", 30)} הימים האחרונים, בכל התיבות. רק שמות הקבצים נקראים — שום דבר לא יורד עד שלוחצים ⬇️.
{f'עודכן: {e(data.get("at", ""))}' if data else ''}</p>
<form method="post" action="/files_scan" style="margin-bottom:10px"><input type="hidden" name="t" value="{TOKEN}">
<button>{'🔄 רענון' if data else '📎 איסוף הרשימה (כדקה)'}</button></form>
{f"""<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
<input type="search" id="f-q" placeholder="🔍 סינון לפי שם קובץ, שולח או נושא…" style="flex:1;min-width:220px;font:inherit;padding:8px 12px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">
<button type="button" class="ghost fchip" data-kind="" style="margin:0">הכול ({len(rows)})</button>{chips}</div>
<div class="scroll"><table id="f-table"><thead><tr><th>קובץ</th><th>מאת</th><th>תאריך</th><th></th></tr></thead><tbody>{table}</tbody></table></div>
<script>(function(){{var kind='',q=document.getElementById('f-q');
function apply(){{var t=q.value.trim().toLowerCase();document.querySelectorAll('#f-table tbody tr').forEach(function(tr){{
tr.style.display=(!kind||tr.dataset.kind===kind)&&(!t||tr.dataset.text.indexOf(t)>=0)?'':'none';}});}}
document.querySelectorAll('.fchip').forEach(function(b){{b.onclick=function(){{kind=b.dataset.kind;
document.querySelectorAll('.fchip').forEach(function(x){{x.style.background=x===b?'var(--accent)':'';x.style.color=x===b?'#fff':'';}});apply();}};}});
q.oninput=apply;}})();</script>""" if rows else ('<p class="muted">לא נמצאו קבצים.</p>' if data else '')}''', '/search')
