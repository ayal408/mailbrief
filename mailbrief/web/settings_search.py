"""🔎 Search in settings: every heading of every settings sub-tab, with the words under it, so typing "חתימה" or "נטפרי"
jumps straight to the right place. Built from the pages themselves, so a new setting is searchable by itself."""
import html
import re
import time

_CACHE = {'at': 0.0, 'rows': []}
HEADING = re.compile(r'<h2 id="([\w-]+)"[^>]*>(.*?)</h2>(.*?)(?=<h2 id=|$)', re.S)
TAGS = re.compile(r'<(script|style)\b.*?</\1>|<[^>]+>', re.S)


def _plain(fragment):
    return re.sub(r'\s+', ' ', html.unescape(TAGS.sub(' ', fragment))).strip()


def index():
    """[{'sec', 'id', 'title', 'text'}] — rebuilt at most every 10 minutes."""
    if time.monotonic() - _CACHE['at'] < 600 and _CACHE['rows']:
        return _CACHE['rows']
    from mailbrief.web import settings
    sections = {'boxes': settings.boxes_section, 'me': settings.me_section, 'money': settings.money_section,
                'clients': settings.clients_section, 'auto': settings.auto_section, 'tidy': settings.tidy_section,
                'data': settings.data_section, 'connect': settings.connect_section}
    names = {k: f'{icon} {title}' for k, icon, title in settings.SECTIONS}
    rows = [{'sec': 'boxes', 'where': names['boxes'], 'id': '', 'title': title, 'text': text} for title, text in (
        ('📬 התיבות שלי', 'תיבות מחוברות, בדיקת חיבור, הסרה, בדיקה, תדריך לתיבה, תמונת פרופיל'),
        ('➕ חיבור תיבה', 'חיבור עם Google, Microsoft, Outlook, Gmail, IMAP, סיסמת אפליקציה, Google לא אימתה את האפליקציה'),
        ('✍️ חתימה לכל תיבה', 'חתימה, לוגו, אתר, WhatsApp, וואטסאפ, תמונה בחתימה'),
        ('⏸️ השהיית אוטומציות', 'השהיה לשעתיים, עד מחר בבוקר, לעצור התראות'))]
    for sec, render in sections.items():
        try:
            page = render()
        except Exception:
            continue
        for anchor, title, body in HEADING.findall(page):
            rows.append({'sec': sec, 'where': names[sec], 'id': anchor, 'title': _plain(title), 'text': _plain(body)[:600]})
    _CACHE.update(at=time.monotonic(), rows=rows)
    return rows


BOX = '''<div style="position:relative;margin:0 0 12px">
<input type="search" id="set-q" placeholder="🔎 חיפוש בהגדרות — למשל: חתימה, נטפרי, גיבוי, שבת…" autocomplete="off"
 style="width:100%;font:inherit;padding:10px 14px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--ink)">
<ul id="set-r" role="listbox" style="display:none;position:absolute;inset-inline:0;top:100%;z-index:20;margin:4px 0 0;padding:6px;list-style:none;
 background:var(--surface);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);max-height:360px;overflow:auto"></ul></div>
<script>(function(){var q=document.getElementById('set-q'),r=document.getElementById('set-r'),rows=null;if(!q)return;
function norm(s){return (s||'').toLowerCase().replace(/[״"׳']/g,'');}
function show(){var t=norm(q.value.trim());r.innerHTML='';if(!t||!rows){r.style.display='none';return;}
var hits=rows.map(function(x){var ti=norm(x.title).indexOf(t),tx=norm(x.text).indexOf(t);return {x:x,s:ti>=0?0:tx>=0?1:9,at:tx};})
.filter(function(h){return h.s<9;}).sort(function(a,b){return a.s-b.s;}).slice(0,12);
if(!hits.length){var li=document.createElement('li');li.className='muted';li.style.padding='6px 10px';li.textContent='לא נמצא — אפשר לנסות מילה אחרת, או Ctrl+K';r.appendChild(li);}
hits.forEach(function(h){var li=document.createElement('li'),a=document.createElement('a');a.href='/?s='+h.x.sec+'#'+h.x.id;
a.style.cssText='display:block;padding:7px 10px;border-radius:8px;text-decoration:none;color:var(--ink)';
var b=document.createElement('b');b.textContent=h.x.title;var s=document.createElement('div');s.className='muted';s.style.fontSize='12.5px';
var snip=h.s===1?h.x.text.slice(Math.max(0,h.at-30),h.at+70):h.x.text.slice(0,90);s.textContent=h.x.where+' · '+snip+'…';
a.appendChild(b);a.appendChild(s);a.onmouseenter=function(){a.style.background='var(--bg)';};a.onmouseleave=function(){a.style.background='';};
li.appendChild(a);r.appendChild(li);});r.style.display='block';}
q.addEventListener('focus',function(){if(!rows)fetch('/settings_index.json',{credentials:'same-origin'}).then(function(x){return x.json();}).then(function(d){rows=d;show();});});
q.addEventListener('input',show);q.addEventListener('keydown',function(ev){if(ev.key==='Enter'){var a=r.querySelector('a');if(a){ev.preventDefault();a.click();}}
if(ev.key==='Escape'){q.value='';show();}});document.addEventListener('click',function(ev){if(!ev.target.closest('#set-r')&&ev.target!==q)r.style.display='none';});})();</script>'''
