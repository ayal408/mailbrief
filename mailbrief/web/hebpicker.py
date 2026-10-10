"""📅 The Hebrew date picker: every date field in MailBrief (type=date / datetime-local) opens this calendar instead of the
browser's. It follows ngx-hebrew-datepicker (github.com/ayal408/angular-hebrew-datepicker): the Hebrew month as the grid
(כ״ח with the civil day beside it), a month list and a year list in gematria, the civil months of the view in a bar, and
the browser's own ICU Hebrew calendar (Intl, he-u-ca-hebrew), leap years included, so no calendar library. MailBrief adds
Shabbat and the holidays as kept in Israel, a time for datetime fields, quick "today / tomorrow / in a week", a switch
to the civil month grid, and the full Hebrew date written next to the field. The field itself stays a normal date field
(forms, typing and "required" work as before); add data-native to keep the browser's own picker. Pure page code,
nothing goes to the internet."""

STYLE = """
input[type=date]:not([data-native])::-webkit-calendar-picker-indicator,input[type=datetime-local]:not([data-native])::-webkit-calendar-picker-indicator{display:none}
input[data-hp]{cursor:pointer}
.hp-open{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:10px;padding:5px 9px;cursor:pointer;font:inherit;font-size:14px;line-height:1}
.hp-open:hover{border-color:var(--accent)}.hp-heb{font-size:12px;color:var(--muted);white-space:nowrap}
#hp{position:fixed;z-index:90;width:318px;max-width:calc(100vw - 16px);box-sizing:border-box;overflow-y:auto;background:var(--surface);color:var(--ink);
border:1px solid var(--line);border-radius:18px;box-shadow:0 18px 50px rgba(20,10,40,.28);padding:12px;display:none;font-family:Rubik,system-ui,sans-serif;direction:rtl;user-select:none}
#hp.on{display:block;animation:hpin .15s ease}@keyframes hpin{from{opacity:0;transform:translateY(-4px)}}
#hp button{font:inherit;cursor:pointer}
#hp .hd{display:flex;align-items:center;gap:5px}
#hp .nav{flex:none;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:9px;width:32px;height:32px;font-size:17px;line-height:1;padding:0}
#hp .nav:hover{border-color:var(--accent)}
#hp .hd select{flex:1;min-width:0;height:32px;padding:0 6px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink);font:inherit;font-size:14px;font-weight:600}
#hp .bar{display:flex;align-items:center;gap:6px;margin-top:7px;padding:4px 8px;border-radius:9px;background:var(--bg);font-size:12px;color:var(--muted)}
#hp .bar span{flex:1;text-align:center}#hp .bar button{border:0;background:none;color:var(--accent);padding:0;font-size:12px;text-decoration:underline;white-space:nowrap}
#hp .g{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-top:7px}#hp .wd{font-size:11px;font-weight:700;color:var(--muted);text-align:center;padding:2px 0}
#hp .wd.sh{color:var(--accent)}
#hp .d{border:1px solid transparent;background:none;color:var(--ink);border-radius:10px;height:40px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;padding:0;position:relative}
#hp .d b{font-size:14px;font-weight:600;line-height:1}#hp .d i{font-style:normal;font-size:10px;color:var(--muted);line-height:1}
#hp .d:hover:not(:disabled){background:color-mix(in srgb,var(--accent) 12%,transparent)}#hp .d:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
#hp .d.sh{background:color-mix(in srgb,var(--accent) 6%,transparent)}#hp .d.hol{background:color-mix(in srgb,var(--accent-2) 14%,transparent)}
#hp .d.yt::after{content:'';position:absolute;top:4px;inset-inline-end:4px;width:6px;height:6px;border-radius:50%;background:var(--accent-2)}
#hp .d.today{border-color:var(--accent)}
#hp .d.sel{background:var(--accent)!important;color:#fff}#hp .d.sel i{color:#fff;opacity:.85}#hp .d:disabled{opacity:.25;cursor:default}
#hp .d .m1{position:absolute;top:2px;inset-inline-start:3px;font-size:8px;color:var(--accent);font-weight:700}#hp .d.sel .m1{color:#fff}
#hp .info{min-height:18px;font-size:12px;color:var(--muted);text-align:center;margin:7px 0 4px}
#hp .tm{display:flex;gap:6px;align-items:center;justify-content:center;margin:4px 0 6px;font-size:13px}
#hp .tm select{font:inherit;font-size:14px;padding:5px 8px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
#hp .ft{display:flex;gap:6px;flex-wrap:wrap;justify-content:center;padding-top:7px;border-top:1px solid var(--line)}
#hp .ft button{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:5px 11px;font-size:13px}
#hp .ft button:hover:not(:disabled){border-color:var(--accent)}#hp .ft button:disabled{opacity:.4;cursor:default}#hp .ft .ok{background:var(--accent);color:#fff;border-color:var(--accent)}
"""

HTML = r"""
<div id="hp" role="dialog" aria-label="בחירת תאריך"></div>
<script>
(function(){
  var box = document.getElementById('hp'); if (!box || window.HebPicker) return;
  // Every day here is a UTC-noon Date for one calendar day: day arithmetic stays clear of DST and time-zone edges
  var DAY = 86400000, HEB = new Intl.DateTimeFormat('he-u-ca-hebrew', {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'});
  var LONG = new Intl.DateTimeFormat('he-IL', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'});
  var MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];
  function day(y, m, d){ return new Date(Date.UTC(y, m, d, 12)); }
  function local(dt){ return day(dt.getFullYear(), dt.getMonth(), dt.getDate()); }
  function add(d, n){ return new Date(d.getTime() + n * DAY); }
  function pad(n){ return (n < 10 ? '0' : '') + n; }
  function iso(d){ return d.toISOString().slice(0, 10); }
  function parse(v){                                   // 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM' -> {d, hh, mm}
    var m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(v || ''); if (!m) return null;
    var d = day(+m[1], m[2] - 1, +m[3]); return d.getUTCMonth() === m[2] - 1 ? {d: d, hh: m[4] ? +m[4] : 9, mm: m[5] ? +m[5] : 0} : null;
  }
  function gem(n){                                     // 28 -> כ״ח, 5787 -> תשפ״ז
    var ones = ['', 'א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ז', 'ח', 'ט'], tens = ['', 'י', 'כ', 'ל', 'מ', 'נ', 'ס', 'ע', 'פ', 'צ'];
    var hund = ['', 'ק', 'ר', 'ש', 'ת', 'תק', 'תר', 'תש', 'תת', 'תתק'], s = '';
    n = n % 1000; s = hund[Math.floor(n / 100)]; n %= 100;
    s += n === 15 ? 'טו' : n === 16 ? 'טז' : tens[Math.floor(n / 10)] + ones[n % 10];
    return s.length > 1 ? s.slice(0, -1) + '״' + s.slice(-1) : s + '׳';
  }
  var memo = {}, memoSize = 0;
  function heb(d){
    var k = d.getTime();
    if (!memo[k]) { if (++memoSize > 4000) { memo = {}; memoSize = 1; }
      var p = {}; HEB.formatToParts(d).forEach(function(x){ p[x.type] = x.value; }); memo[k] = {d: +p.day, m: p.month, y: +p.year}; }
    return memo[k];
  }
  function hebText(d, withYear){ var h = heb(d); return gem(h.d) + ' ב' + h.m + (withYear === false ? '' : ' ' + gem(h.y)); }
  function holiday(d){                                 // [name, yom tov?, minor?] — by the Hebrew date, as kept in Israel
    var h = heb(d), m = h.m, n = h.d, w = d.getUTCDay(), adar = m === 'אדר' || m === 'אדר ב׳';   // w: 0 Sunday … 6 Shabbat
    if (m === 'אלול' && n === 29) return ['ערב ראש השנה', 0];
    if (m === 'תשרי') { if (n <= 2) return ['ראש השנה', 1]; if ((n === 3 && w !== 6) || (n === 4 && w === 0)) return ['צום גדליה', 0];
      if (n === 9) return ['ערב יום כיפור', 0]; if (n === 10) return ['יום כיפור', 1]; if (n === 14) return ['ערב סוכות', 0]; if (n === 15) return ['סוכות', 1];
      if (n > 15 && n < 21) return ['חוה״מ סוכות', 0]; if (n === 21) return ['הושענא רבה', 0]; if (n === 22) return ['שמיני עצרת · שמחת תורה', 1]; }
    if (m === 'כסלו' && n >= 25) return ['חנוכה ' + gem(n - 24), 0];
    if (m === 'טבת' && n <= 3) { var k = heb(add(d, -n)).d === 30 ? 6 : 5; if (n <= 8 - k) return ['חנוכה ' + gem(k + n), 0]; }   // Kislev of 29 or 30 days
    if (m === 'טבת' && n === 10) return ['עשרה בטבת', 0];
    if (m === 'שבט' && n === 15) return ['ט״ו בשבט', 0];
    if (adar && ((n === 13 && w !== 6) || (n === 11 && w === 4))) return ['תענית אסתר', 0];   // on Shabbat: the Thursday before
    if (adar && n === 14) return ['פורים', 0]; if (adar && n === 15) return ['שושן פורים', 0];
    if (m === 'ניסן') { if (n === 14) return ['ערב פסח', 0]; if (n === 15) return ['פסח', 1]; if (n > 15 && n < 21) return ['חוה״מ פסח', 0]; if (n === 21) return ['שביעי של פסח', 1];
      if ((n === 27 && w !== 5 && w !== 0) || (n === 26 && w === 4) || (n === 28 && w === 1)) return ['יום השואה', 0]; }
    if (m === 'אייר') {                                // Yom HaAtzmaut moves off Friday / Shabbat / Monday, Yom HaZikaron the day before
      if ((n === 5 && w === 3) || ((n === 3 || n === 4) && w === 4) || (n === 6 && w === 2)) return ['יום העצמאות', 0];
      if ((n === 4 && w === 2) || ((n === 2 || n === 3) && w === 3) || (n === 5 && w === 1)) return ['יום הזיכרון', 0];
      if (n === 18) return ['ל״ג בעומר', 0]; if (n === 28) return ['יום ירושלים', 0]; }
    if (m === 'סיוון' && n === 5) return ['ערב שבועות', 0]; if (m === 'סיוון' && n === 6) return ['שבועות', 1];
    if (m === 'תמוז' && ((n === 17 && w !== 6) || (n === 18 && w === 0))) return ['צום י״ז בתמוז', 0];
    if (m === 'אב' && ((n === 9 && w !== 6) || (n === 10 && w === 0))) return ['תשעה באב', 0];
    if (m === 'אב' && n === 15) return ['ט״ו באב', 0];
    if ((n === 1 && m !== 'תשרי') || n === 30) return ['ראש חודש', 0, 1];
    return null;
  }
  function describe(d){ var hol = holiday(d); return hebText(d) + (hol ? ' · ' + hol[0] : ''); }

  // The month shown: a Hebrew month (the default, as in ngx-hebrew-datepicker) or a civil one
  var CAL = {
    heb: {
      start: function(d){ return add(d, 1 - heb(d).d); },
      next: function(s){ return CAL.heb.start(add(s, 30)); },          // 29 or 30 days: day 31 is always the next month
      prev: function(s){ return CAL.heb.start(add(s, -1)); },
      same: function(a, b){ return heb(a).m === heb(b).m && heb(a).y === heb(b).y; },
      year: function(s){ return heb(s).y; }, yearName: gem, monthName: function(s){ return heb(s).m; },
      months: function(s){                             // the first day of each month of the Hebrew year, Tishrei first
        var y = heb(s).y, c = CAL.heb.start(s), out = [];
        while (heb(CAL.heb.prev(c)).y === y) c = CAL.heb.prev(c);
        for (; heb(c).y === y; c = CAL.heb.next(c)) out.push(c);
        return out;
      },
      inYear: function(s, y){                          // the same month in year y; Adar <-> Adar I / II falls on Adar
        var guess = CAL.heb.start(add(s, Math.round((y - heb(s).y) * 365.2468))), ms = CAL.heb.months(guess), name = heb(s).m;
        return ms.filter(function(x){ return heb(x).m === name; })[0] || ms.filter(function(x){ return heb(x).m.indexOf('אדר') === 0; })[0] || guess;
      },
      main: function(d){ return gem(heb(d).d); }, side: function(d){ return d.getUTCDate(); },
      first: function(d){ return d.getUTCDate() === 1 ? MONTHS[d.getUTCMonth()] : ''; },
      range: function(days){                           // the civil months this Hebrew month spans
        var a = days[0], b = days[days.length - 1], ma = MONTHS[a.getUTCMonth()], mb = MONTHS[b.getUTCMonth()];
        if (a.getUTCFullYear() !== b.getUTCFullYear()) return ma + ' ' + a.getUTCFullYear() + ' – ' + mb + ' ' + b.getUTCFullYear();
        return (ma === mb ? ma : ma + ' – ' + mb) + ' ' + a.getUTCFullYear();
      }
    },
    civ: {
      start: function(d){ return day(d.getUTCFullYear(), d.getUTCMonth(), 1); },
      next: function(s){ return day(s.getUTCFullYear(), s.getUTCMonth() + 1, 1); },
      prev: function(s){ return day(s.getUTCFullYear(), s.getUTCMonth() - 1, 1); },
      same: function(a, b){ return a.getUTCMonth() === b.getUTCMonth() && a.getUTCFullYear() === b.getUTCFullYear(); },
      year: function(s){ return s.getUTCFullYear(); }, yearName: String, monthName: function(s){ return MONTHS[s.getUTCMonth()]; },
      months: function(s){ var out = []; for (var i = 0; i < 12; i++) out.push(day(s.getUTCFullYear(), i, 1)); return out; },
      inYear: function(s, y){ return day(y, s.getUTCMonth(), 1); },
      main: function(d){ return d.getUTCDate(); }, side: function(d){ var hol = holiday(d); return hol && hol[1] ? '✡' : gem(heb(d).d); },
      first: function(d){ return heb(d).d === 1 ? heb(d).m : ''; },
      range: function(days){
        var a = heb(days[0]), b = heb(days[days.length - 1]);
        return a.m + (a.m !== b.m ? ' – ' + b.m : '') + ' ' + gem(b.y);
      }
    }
  };

  var S = {input: null, mode: 'heb', view: null, sel: null, hh: 9, mm: 0, focus: null};
  try { if (localStorage.getItem('hp-mode') === 'civ') S.mode = 'civ'; } catch (e) {}
  function cal(){ return CAL[S.mode]; }
  function today(){ return local(new Date()); }
  function days(start){ var c = cal(), out = []; for (var d = start; c.same(d, start); d = add(d, 1)) out.push(d); return out; }

  function label(input){
    var span = input.parentNode && input.parentNode.querySelector('.hp-heb[data-for="' + input.dataset.hp + '"]'), v = parse(input.value);
    if (span) span.textContent = v ? describe(v.d) : '';
  }
  var seq = 0;
  function upgrade(input){
    if (input.dataset.hp || input.hasAttribute('data-native')) return;
    input.dataset.hp = String(++seq);
    var btn = document.createElement('button'); btn.type = 'button'; btn.className = 'hp-open'; btn.textContent = '📅'; btn.title = 'לוח שנה עברי';
    var span = document.createElement('span'); span.className = 'hp-heb'; span.dataset.for = input.dataset.hp;
    input.insertAdjacentElement('afterend', span); input.insertAdjacentElement('afterend', btn);
    btn.addEventListener('click', function(){ if (S.input === input) close(); else open(input); });
    input.addEventListener('click', function(ev){ ev.preventDefault(); open(input); });
    input.addEventListener('keydown', function(ev){ if (ev.key === 'Enter' || (ev.key === ' ' && !input.value) || (ev.altKey && ev.key === 'ArrowDown')) { ev.preventDefault(); open(input); } });
    input.addEventListener('input', function(){ label(input); }); input.addEventListener('change', function(){ label(input); });
    label(input);
  }
  function scan(root){ Array.prototype.forEach.call((root || document).querySelectorAll('input[type=date],input[type=datetime-local]'), upgrade); }

  function open(input){
    if (input.disabled || input.readOnly) return;
    S.input = input; var v = parse(input.value);
    S.sel = v ? v.d : null; S.hh = v ? v.hh : 9; S.mm = v ? v.mm - v.mm % 5 : 0;
    S.focus = S.sel || today(); S.view = cal().start(S.focus);
    draw(); box.classList.add('on'); place(); focusDay();
  }
  function close(){ box.classList.remove('on'); var input = S.input; S.input = null; if (input) input.focus(); }
  function place(){
    if (!S.input) return;
    var r = S.input.getBoundingClientRect(), w = box.offsetWidth, below = window.innerHeight - r.bottom - 12, above = r.top - 12;
    var up = below < box.scrollHeight && above > below, room = Math.max(220, up ? above : below);
    box.style.maxHeight = room + 'px';
    box.style.top = (up ? Math.max(6, r.top - 6 - Math.min(room, box.scrollHeight)) : r.bottom + 6) + 'px';
    box.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w)) + 'px';
  }
  function bounds(){ var a = parse(S.input.min), b = parse(S.input.max); return {min: a && a.d, max: b && b.d}; }
  function blocked(d){ var b = bounds(); return !!((b.min && d < b.min) || (b.max && d > b.max)); }
  function focusDay(){
    var f = box.querySelector('[data-day="' + (S.focus ? iso(S.focus) : '') + '"]:not(:disabled)') || box.querySelector('.d.sel') ||
      box.querySelector('.d.today') || box.querySelector('.d:not(:disabled)');
    if (f) f.focus();
  }
  function draw(){
    var c = cal(), timed = S.input.type === 'datetime-local', t = today(), list = days(S.view), b = bounds();
    var ms = c.months(S.view), y = c.year(S.view), from = (b.min ? c.year(c.start(b.min)) : y - 30), to = (b.max ? c.year(c.start(b.max)) : y + 30);
    var html = '<div class="hd"><button type="button" class="nav" data-go="-1" title="החודש הקודם (PageUp)">›</button>' +
      '<select id="hp-mo" aria-label="חודש">' + ms.map(function(m, i){ return '<option value="' + i + '"' + (c.same(m, S.view) ? ' selected' : '') + '>' + c.monthName(m) + '</option>'; }).join('') + '</select>' +
      '<select id="hp-yr" aria-label="שנה">';
    for (var yy = Math.min(from, y); yy <= Math.max(to, y); yy++) html += '<option value="' + yy + '"' + (yy === y ? ' selected' : '') + '>' + c.yearName(yy) + '</option>';
    html += '</select><button type="button" class="nav" data-go="1" title="החודש הבא (PageDown)">‹</button></div>' +
      '<div class="bar"><span>' + c.range(list) + '</span><button type="button" data-mode="1">' + (S.mode === 'heb' ? 'לוח לועזי' : 'לוח עברי') + '</button></div><div class="g">';
    ['א׳', 'ב׳', 'ג׳', 'ד׳', 'ה׳', 'ו׳', 'ש׳'].forEach(function(w, i){ html += '<div class="wd' + (i === 6 ? ' sh' : '') + '">' + w + '</div>'; });
    for (var i = 0; i < S.view.getUTCDay(); i++) html += '<div></div>';
    list.forEach(function(d){
      var hol = holiday(d), k = iso(d), first = c.first(d), w = d.getUTCDay();
      var cls = 'd' + (w === 6 ? ' sh' : '') + (hol && !hol[2] ? ' hol' : '') + (hol && hol[1] ? ' yt' : '') + (k === iso(t) ? ' today' : '') + (S.sel && k === iso(S.sel) ? ' sel' : '');
      html += '<button type="button" class="' + cls + '" data-day="' + k + '" tabindex="-1"' + (blocked(d) ? ' disabled' : '') +
        ' title="' + LONG.format(d) + ' · ' + describe(d) + (w === 6 ? ' · שבת' : '') + '">' + (first ? '<span class="m1">' + first + '</span>' : '') +
        '<b>' + c.main(d) + '</b><i>' + c.side(d) + '</i></button>';
    });
    html += '</div><div class="info">' + (S.sel ? LONG.format(S.sel) + ' · ' + describe(S.sel) : 'בוחרים יום') + '</div>';
    if (timed) {
      var hours = '', mins = '';
      for (var hh = 0; hh < 24; hh++) hours += '<option value="' + hh + '"' + (hh === S.hh ? ' selected' : '') + '>' + pad(hh) + '</option>';
      for (var mm = 0; mm < 60; mm += 5) mins += '<option value="' + mm + '"' + (mm === S.mm ? ' selected' : '') + '>' + pad(mm) + '</option>';
      html += '<div class="tm">🕘 שעה <select id="hp-m" aria-label="דקות">' + mins + '</select>:<select id="hp-h" aria-label="שעה">' + hours + '</select></div>';
    }
    html += '<div class="ft">' + [[0, 'היום'], [1, 'מחר'], [7, 'בעוד שבוע']].map(function(q){ return '<button type="button" data-q="' + q[0] + '"' + (blocked(add(t, q[0])) ? ' disabled' : '') + '>' + q[1] + '</button>'; }).join('') +
      (S.input.required ? '' : '<button type="button" data-q="clear">ניקוי</button>') + (timed ? '<button type="button" class="ok" data-q="ok">אישור</button>' : '') + '</div>';
    box.innerHTML = html;
    var f = box.querySelector('[data-day="' + (S.focus ? iso(S.focus) : '') + '"]') || box.querySelector('.d:not(:disabled)'); if (f) f.tabIndex = 0;
  }
  function show(start, focus){ S.view = start; S.focus = focus || start; draw(); place(); }
  function commit(){
    if (!S.input) return; var timed = S.input.type === 'datetime-local', d = S.sel, input = S.input;
    input.value = d ? iso(d) + (timed ? 'T' + pad(S.hh) + ':' + pad(S.mm) : '') : '';
    input.dispatchEvent(new Event('input', {bubbles: true})); input.dispatchEvent(new Event('change', {bubbles: true}));
    label(input); close();
  }
  function pick(d){                                    // a day chosen: a date field is done, a date-and-time field waits for "אישור"
    if (blocked(d)) return; S.sel = d;
    if (S.input.type === 'datetime-local') { show(cal().start(d), d); focusDay(); } else commit();
  }
  box.addEventListener('click', function(ev){
    var t = ev.target.closest('button'); if (!t || t.disabled) return;
    if (t.dataset.go) { show(+t.dataset.go > 0 ? cal().next(S.view) : cal().prev(S.view)); return; }
    if (t.dataset.mode) { S.mode = S.mode === 'heb' ? 'civ' : 'heb'; try { localStorage.setItem('hp-mode', S.mode); } catch (e) {}
      show(cal().start(S.focus || S.view), S.focus); return; }
    if (t.dataset.day) { pick(parse(t.dataset.day).d); return; }
    var q = t.dataset.q;
    if (q === 'clear') { S.sel = null; commit(); return; }
    if (q === 'ok') { if (S.sel) commit(); return; }
    if (q !== undefined) pick(add(today(), +q));
  });
  box.addEventListener('change', function(ev){
    var id = ev.target.id, v = +ev.target.value;
    if (id === 'hp-h') S.hh = v; if (id === 'hp-m') S.mm = v;
    if (id === 'hp-mo') { var m = cal().months(S.view)[v]; if (m) show(m); }
    if (id === 'hp-yr') show(cal().inYear(S.view, v));
  });
  box.addEventListener('keydown', function(ev){
    if (ev.key === 'Escape') { ev.stopPropagation(); close(); return; }
    if (ev.key === 'PageUp' || ev.key === 'PageDown') { ev.preventDefault(); show(ev.key === 'PageDown' ? cal().next(S.view) : cal().prev(S.view)); focusDay(); return; }
    var cell = ev.target.closest && ev.target.closest('.d'); if (!cell) return;
    var step = {ArrowLeft: 1, ArrowRight: -1, ArrowDown: 7, ArrowUp: -7}[ev.key];             // RTL: left = the next day
    if (step) { ev.preventDefault(); var d = add(parse(cell.dataset.day).d, step);
      if (!cal().same(d, S.view)) show(cal().start(d), d); else S.focus = d;
      var next = box.querySelector('[data-day="' + iso(d) + '"]'); if (next) next.focus(); }
  });
  document.addEventListener('mousedown', function(ev){ if (box.classList.contains('on') && !box.contains(ev.target) && ev.target !== S.input && !ev.target.closest('.hp-open')) close(); });
  window.addEventListener('resize', place); window.addEventListener('scroll', function(){ if (S.input) place(); }, true);
  scan(document);
  new MutationObserver(function(list){ list.forEach(function(m){ Array.prototype.forEach.call(m.addedNodes, function(n){ if (n.nodeType === 1) { if (n.matches && n.matches('input[type=date],input[type=datetime-local]')) upgrade(n); else if (n.querySelectorAll) scan(n); } }); }); })
    .observe(document.body, {childList: true, subtree: true});
  window.HebPicker = {open: open, gem: gem,                                     // for other page code: local Dates in, as before
    hebText: function(dt, withYear){ return hebText(local(dt), withYear); }, holiday: function(dt){ return holiday(local(dt)); }};
})();
</script>
"""
