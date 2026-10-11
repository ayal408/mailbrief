"""📅 The Hebrew calendar tab: a Hebrew month (כ״ח with the civil day beside it), the holidays as kept in Israel, candle
lighting / havdalah and the parasha for the chosen city (Hebcal), the Google Calendar events (when Calendar is connected),
and MailBrief's own reminders and scheduled emails. The month grid is page code on the browser's ICU Hebrew calendar,
like the date picker; the events come from /calendar.json."""
import datetime as dt
import json

from mailbrief import config, net
from mailbrief.storage import load_json
from mailbrief.web.layout import heading, page


def _day(text):
    try:
        return dt.date.fromisoformat(text[:10])
    except (TypeError, ValueError):
        return None


def events(start, end):
    """[{'day', 'time', 'title', 'kind', 'link'}] between two dates (inclusive), plus a note when Calendar can't be read."""
    from mailbrief.features.calendar import CITIES
    out, notes = [], []
    city = load_json(config.SETTINGS_FILE, {}).get('city', 'ירושלים')
    lat, lon = CITIES.get(city, CITIES['ירושלים'])
    data = net.cached_json(f'hebcal|{start}|{city}', f'https://www.hebcal.com/hebcal?v=1&cfg=json&c=on&s=on&maj=on&geo=pos&latitude={lat}'
                           f'&longitude={lon}&tzid=Asia/Jerusalem&lg=he&start={start}&end={end}', 24 * 60)
    for item in (data or {}).get('items', []):
        kind, when = item.get('category'), item.get('date', '')
        if kind in ('candles', 'havdalah') and 'T' in when:
            out.append({'day': when[:10], 'time': when[11:16], 'kind': 'shabbat',
                        'title': ('🕯️ הדלקת נרות' if kind == 'candles' else '✨ הבדלה'), 'link': ''})
        elif kind == 'parashat':
            out.append({'day': when[:10], 'time': '', 'kind': 'parasha', 'title': '📖 ' + (item.get('hebrew') or item.get('title', '')), 'link': ''})
    if data is None:
        notes.append(f'זמני שבת ל{city} לא נטענו (אין אינטרנט?)')
    try:
        from mailbrief.features.google_apps import events_on, gapps_account
        acc = gapps_account()
        if acc:
            for ev in events_on(acc, start, (end - start).days + 1):
                out.append({'day': ev['day'], 'time': '' if ev['time'] == 'כל היום' else ev['time'], 'kind': 'google',
                            'title': ev['title'], 'link': ev['link']})
    except Exception as exc:
        notes.append(f'Google Calendar: {exc}')
    for r in load_json(config.REMINDERS_FILE, []):
        d = _day(r.get('due', ''))
        if d and start <= d <= end:
            out.append({'day': d.isoformat(), 'time': r['due'][11:16], 'kind': 'reminder', 'title': '⏰ ' + (r.get('subject') or 'תזכורת'),
                        'link': r.get('link', '')})
    from mailbrief.features.outbox import outbox
    for it in outbox():
        d = _day(it.get('send_at', ''))
        if d and start <= d <= end and it.get('status') == 'waiting':
            out.append({'day': d.isoformat(), 'time': it['send_at'][11:16], 'kind': 'send', 'link': '',
                        'title': '📤 ' + (it.get('subject') or 'מייל מתוזמן') + (f" ← {it['to']}" if it.get('to') else '')})
    out.sort(key=lambda x: (x['day'], x['time'] or '00:00'))
    return {'events': out, 'notes': notes, 'city': city}


CSS = r"""
#cal{max-width:1100px;margin:0 auto}
.cal-hd{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.cal-hd h2{margin:0;font-size:24px;flex:1;min-width:200px}.cal-hd h2 small{display:block;font-size:13px;color:var(--muted);font-weight:400}
.cal-hd button{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:10px;padding:7px 12px;font:inherit;cursor:pointer}
.cal-hd button:hover{border-color:var(--accent)}
.cal-g{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px}
.cal-wd{text-align:center;font-size:12px;font-weight:700;color:var(--muted);padding:4px 0}.cal-wd.sh{color:var(--accent)}
.cal-d{min-height:96px;border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:5px 6px;cursor:pointer;display:flex;flex-direction:column;gap:2px;overflow:hidden;text-align:start}
.cal-d:hover{border-color:var(--accent)}.cal-d.out{opacity:.4}.cal-d.sh{background:color-mix(in srgb,var(--accent) 5%,var(--surface))}
.cal-d.yt{background:color-mix(in srgb,var(--accent-2) 12%,var(--surface))}.cal-d.today{box-shadow:inset 0 0 0 2px var(--accent)}.cal-d.pick{border-color:var(--accent-2);border-width:2px}
.cal-n{display:flex;align-items:baseline;justify-content:space-between;gap:4px}.cal-n b{font-size:17px}.cal-n i{font-style:normal;font-size:11px;color:var(--muted)}
.cal-h{font-size:11px;font-weight:600;color:var(--accent-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cal-e{font-size:11px;border-radius:5px;padding:0 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:color-mix(in srgb,var(--accent) 12%,transparent)}
.cal-e.google{background:color-mix(in srgb,#0ea5e9 18%,transparent)}.cal-e.reminder{background:color-mix(in srgb,#f97316 18%,transparent)}
.cal-e.send{background:color-mix(in srgb,#16a34a 18%,transparent)}.cal-e.shabbat,.cal-e.parasha{background:none;color:var(--muted);padding:0}
.cal-more{font-size:11px;color:var(--muted)}
.cal-day{margin-top:14px;border:1px solid var(--line);border-radius:14px;background:var(--surface);padding:14px 16px}
.cal-day h3{margin:0 0 8px}.cal-day .row{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid var(--line)}.cal-day .row:last-child{border:0}
.cal-day .t{min-width:48px;color:var(--muted);font-variant-numeric:tabular-nums}.cal-note{font-size:12px;color:var(--muted);margin-top:8px}
@media(max-width:700px){.cal-d{min-height:64px}.cal-e{display:none}.cal-d.has::after{content:"•";color:var(--accent);font-size:16px;line-height:1}}
"""

JS = r"""
(function(){
var DAY = 864e5, HEB = new Intl.DateTimeFormat('he-IL-u-ca-hebrew', {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'});
var WD = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'];
function utc(y, m, d){ return new Date(Date.UTC(y, m, d, 12)); }
function add(d, n){ return new Date(d.getTime() + n * DAY); }
function iso(d){ return d.toISOString().slice(0, 10); }
function heb(d){ var p = {}; HEB.formatToParts(d).forEach(function(x){ p[x.type] = x.value; }); return {d: +p.day, m: p.month, y: +p.year}; }
function gem(n){ return window.HebPicker ? HebPicker.gem(n) : String(n); }
function holiday(d){ return window.HebPicker ? HebPicker.holiday(new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 12)) : null; }
function monthStart(d){ return add(d, 1 - heb(d).d); }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
var now = new Date(), today = utc(now.getFullYear(), now.getMonth(), now.getDate());
var view = monthStart(today), pick = today, data = {}, notes = [];
try { var saved = localStorage.getItem('cal-view'); if (saved) view = monthStart(new Date(saved + 'T12:00:00Z')); } catch (e) {}
function load(first, last){
  return fetch('/calendar.json?start=' + iso(first) + '&end=' + iso(last), {cache: 'no-store'}).then(function(r){ return r.json(); }).then(function(d){
    data = {}; d.events.forEach(function(e){ (data[e.day] = data[e.day] || []).push(e); }); notes = d.notes || []; draw();
  }).catch(function(){ notes = ['האירועים לא נטענו']; draw(); });
}
function range(){
  var first = add(view, -view.getUTCDay()), end = monthStart(add(view, 30)), last = add(end, -1);
  last = add(last, 6 - last.getUTCDay());
  return [first, last];
}
function draw(){
  var r = range(), h = heb(view), endDay = add(monthStart(add(view, 30)), -1);
  var civil = [view, endDay].map(function(d){ return d.toLocaleDateString('he-IL', {month: 'long', year: 'numeric', timeZone: 'UTC'}); });
  var html = '<div class="cal-hd"><button type="button" data-go="-1" title="החודש הקודם">→</button><h2>' + esc(h.m + ' ' + gem(h.y)) +
    '<small>' + esc(civil[0] === civil[1] ? civil[0] : civil[0] + ' – ' + civil[1]) + '</small></h2>' +
    '<button type="button" data-go="0">היום</button><button type="button" data-go="1" title="החודש הבא">←</button></div><div class="cal-g">' +
    WD.map(function(w, i){ return '<div class="cal-wd' + (i === 6 ? ' sh' : '') + '">' + w + '</div>'; }).join('');
  for (var d = r[0]; d <= r[1]; d = add(d, 1)) {
    var x = heb(d), hol = holiday(d), list = data[iso(d)] || [], inMonth = x.m === h.m;
    var shown = list.filter(function(e){ return e.kind !== 'parasha'; });
    html += '<div class="cal-d' + (inMonth ? '' : ' out') + (d.getUTCDay() === 6 ? ' sh' : '') + (hol && hol[1] ? ' yt' : '') + (+d === +today ? ' today' : '') +
      (+d === +pick ? ' pick' : '') + (list.length ? ' has' : '') + '" data-day="' + iso(d) + '"><div class="cal-n"><b>' + gem(x.d) + '</b><i>' + d.getUTCDate() + '</i></div>' +
      (hol ? '<div class="cal-h">' + esc(hol[0]) + '</div>' : '') +
      (d.getUTCDay() === 6 ? list.filter(function(e){ return e.kind === 'parasha'; }).map(function(e){ return '<div class="cal-h" style="color:var(--muted)">' + esc(e.title) + '</div>'; }).join('') : '') +
      shown.slice(0, 3).map(function(e){ return '<div class="cal-e ' + e.kind + '" title="' + esc(e.title) + '">' + (e.time ? e.time + ' ' : '') + esc(e.title) + '</div>'; }).join('') +
      (shown.length > 3 ? '<div class="cal-more">ועוד ' + (shown.length - 3) + '</div>' : '') + '</div>';
  }
  html += '</div>' + dayBox() + (notes.length ? '<div class="cal-note">' + notes.map(esc).join(' · ') + '</div>' : '');
  document.getElementById('cal').innerHTML = html;
}
function dayBox(){
  var list = data[iso(pick)] || [], hol = holiday(pick), x = heb(pick);
  var g = iso(pick).replace(/-/g, ''), next = iso(add(pick, 1)).replace(/-/g, '');
  return '<div class="cal-day"><h3>יום ' + WD[pick.getUTCDay()] + ', ' + gem(x.d) + ' ב' + esc(x.m) + ' ' + gem(x.y) +
    ' <span class="muted" style="font-size:14px;font-weight:400">· ' + pick.toLocaleDateString('he-IL', {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'}) + '</span></h3>' +
    (hol ? '<div class="row"><span class="t"></span><b>' + esc(hol[0]) + '</b></div>' : '') +
    (list.length ? list.map(function(e){ return '<div class="row"><span class="t">' + (e.time || '') + '</span><span>' +
      (e.link ? '<a href="' + esc(e.link) + '" target="_blank">' + esc(e.title) + '</a>' : esc(e.title)) + '</span></div>'; }).join('') : (hol ? '' : '<div class="muted">אין אירועים ביום הזה</div>')) +
    '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><a class="kbtn" target="_blank" href="https://calendar.google.com/calendar/r/eventedit?dates=' + g + '/' + next + '">➕ אירוע ב-Google Calendar</a>' +
    '<a class="kbtn" href="/inbox?compose=1">✉️ מייל חדש</a></div></div>';
}
function go(n){
  view = n === 0 ? monthStart(today) : n > 0 ? monthStart(add(view, 30)) : monthStart(add(view, -1));
  if (n === 0) pick = today;
  try { localStorage.setItem('cal-view', iso(view)); } catch (e) {}
  var r = range(); draw(); load(r[0], r[1]);
}
document.getElementById('cal').addEventListener('click', function(ev){
  var b = ev.target.closest('[data-go]'); if (b) { go(+b.dataset.go); return; }
  var c = ev.target.closest('[data-day]'); if (c && !ev.target.closest('a')) { pick = new Date(c.dataset.day + 'T12:00:00Z'); draw(); }
});
function start(){ var r = range(); draw(); load(r[0], r[1]); }
if (window.HebPicker) start(); else setTimeout(start, 0);      // the date picker's helpers load with the page
})();
"""


def calendar_page():
    return page('לוח שנה', f'<style>{CSS}</style>{heading("📅", "לוח שנה עברי")}<div id="cal"></div><script>{JS}</script>', '/calendar')


def calendar_json(query):
    try:
        start, end = dt.date.fromisoformat(query.get('start', '')), dt.date.fromisoformat(query.get('end', ''))
    except ValueError:
        start = dt.date.today().replace(day=1)
        end = start + dt.timedelta(days=41)
    end = min(end, start + dt.timedelta(days=62))
    return json.dumps(events(start, end), ensure_ascii=False)
