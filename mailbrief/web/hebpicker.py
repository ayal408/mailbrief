"""📅 The Hebrew date picker: every date field in MailBrief (type=date / datetime-local) opens this calendar instead of the
browser's — the civil month with the Hebrew date in each day (ה׳ בחשוון), Shabbat and the holidays marked, and the full
Hebrew date written next to the field. The field itself stays a normal date field (forms, typing and "required" work as
before); add data-native to keep the browser's own picker. Pure page code, nothing goes to the internet."""

STYLE = """
input[type=date]:not([data-native])::-webkit-calendar-picker-indicator,input[type=datetime-local]:not([data-native])::-webkit-calendar-picker-indicator{display:none}
.hp-wrap{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap;max-width:100%}.hp-wrap>input{cursor:pointer}
.hp-open{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:10px;padding:5px 9px;cursor:pointer;font:inherit;font-size:14px;line-height:1}
.hp-open:hover{border-color:var(--accent)}.hp-heb{font-size:12px;color:var(--muted);white-space:nowrap}
#hp{position:fixed;z-index:90;width:318px;max-width:calc(100vw - 16px);background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:18px;
box-shadow:0 18px 50px rgba(20,10,40,.28);padding:12px;display:none;font-family:Rubik,system-ui,sans-serif;direction:rtl;user-select:none}
#hp.on{display:block;animation:hpin .15s ease}@keyframes hpin{from{opacity:0;transform:translateY(-4px)}}
#hp .hd{display:flex;align-items:center;gap:6px;margin-bottom:6px}#hp .hd .t{flex:1;text-align:center;line-height:1.25}
#hp .hd .t b{font-size:15px;display:block}#hp .hd .t span{font-size:12px;color:var(--accent);font-weight:500}
#hp button{font:inherit;cursor:pointer}#hp .nav{border:0;background:var(--bg);color:var(--ink);border-radius:10px;width:32px;height:32px;font-size:16px}
#hp .nav:hover{background:color-mix(in srgb,var(--accent) 14%,var(--bg))}
#hp .g{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}#hp .wd{font-size:11px;color:var(--muted);text-align:center;padding:2px 0}
#hp .wd.sh{color:var(--accent)}
#hp .d{border:0;background:none;color:var(--ink);border-radius:10px;height:42px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0;padding:0;position:relative}
#hp .d b{font-size:14px;font-weight:500;line-height:1.1}#hp .d i{font-style:normal;font-size:10px;color:var(--muted);line-height:1.1}
#hp .d:hover:not(:disabled){background:color-mix(in srgb,var(--accent) 12%,transparent)}
#hp .d.out{opacity:.35}#hp .d.sh{background:color-mix(in srgb,var(--accent) 6%,transparent)}#hp .d.hol{background:color-mix(in srgb,var(--accent-2) 14%,transparent)}
#hp .d.hol i{color:var(--accent-2);font-weight:700}#hp .d.today{box-shadow:inset 0 0 0 1.5px var(--accent)}
#hp .d.sel{background:var(--accent)!important;color:#fff}#hp .d.sel i{color:#fff}#hp .d:disabled{opacity:.25;cursor:default}
#hp .d .m1{position:absolute;top:1px;inset-inline-start:3px;font-size:8px;color:var(--accent);font-weight:700}
#hp .info{min-height:18px;font-size:12px;color:var(--muted);text-align:center;margin:6px 0 4px}
#hp .tm{display:flex;gap:6px;align-items:center;justify-content:center;margin:4px 0 6px;font-size:13px}
#hp .tm select{font:inherit;font-size:14px;padding:5px 8px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
#hp .ft{display:flex;gap:6px;flex-wrap:wrap;justify-content:center}#hp .ft button{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:5px 11px;font-size:13px}
#hp .ft button:hover{border-color:var(--accent)}#hp .ft .ok{background:var(--accent);color:#fff;border-color:var(--accent)}
"""

HTML = r"""
<div id="hp" role="dialog" aria-label="בחירת תאריך"></div>
<script>
(function(){
  var box = document.getElementById('hp'); if (!box || window.HebPicker) return;
  var HEB = new Intl.DateTimeFormat('he-u-ca-hebrew', {day: 'numeric', month: 'long', year: 'numeric'});
  var CIVIL = new Intl.DateTimeFormat('he-IL', {month: 'long', year: 'numeric'});
  var LONG = new Intl.DateTimeFormat('he-IL', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
  function gem(n){                                     // 28 -> כ״ח, 5787 -> תשפ״ז
    var ones = ['', 'א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ז', 'ח', 'ט'], tens = ['', 'י', 'כ', 'ל', 'מ', 'נ', 'ס', 'ע', 'פ', 'צ'], hund = ['', 'ק', 'ר', 'ש', 'ת'], s = '';
    n = n % 1000; while (n >= 400) { s += 'ת'; n -= 400; } if (n >= 100) { s += hund[Math.floor(n / 100)]; n %= 100; }
    s += n === 15 ? 'טו' : n === 16 ? 'טז' : tens[Math.floor(n / 10)] + ones[n % 10];
    return s.length > 1 ? s.slice(0, -1) + '״' + s.slice(-1) : s + '׳';
  }
  function heb(d){ var p = {}; HEB.formatToParts(d).forEach(function(x){ p[x.type] = x.value; }); return {d: +p.day, m: p.month, y: +p.year}; }
  function hebText(d, withYear){ var h = heb(d); return gem(h.d) + ' ב' + h.m + (withYear === false ? '' : ' ' + gem(h.y)); }
  function addDays(d, n){ var x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function holiday(d){                                 // [name, yom tov?] — the main holidays, by the Hebrew date
    var h = heb(d), m = h.m, n = h.d;
    if (m === 'תשרי') { if (n <= 2) return ['ראש השנה', 1]; if (n === 10) return ['יום כיפור', 1]; if (n === 15) return ['סוכות', 1];
      if (n > 15 && n < 21) return ['חוה״מ סוכות', 0]; if (n === 21) return ['הושענא רבה', 0]; if (n === 22) return ['שמחת תורה', 1]; }
    for (var k = 0; k < 8; k++) { var b = heb(addDays(d, -k)); if (b.m === 'כסלו' && b.d === 25) return ['חנוכה ' + gem(k + 1), 0]; }
    if (m === 'שבט' && n === 15) return ['ט״ו בשבט', 0];
    if ((m === 'אדר' || m === 'אדר ב׳') && n === 14) return ['פורים', 0]; if ((m === 'אדר' || m === 'אדר ב׳') && n === 15) return ['שושן פורים', 0];
    if (m === 'ניסן') { if (n === 15) return ['פסח', 1]; if (n > 15 && n < 21) return ['חוה״מ פסח', 0]; if (n === 21) return ['שביעי של פסח', 1]; }
    if (m === 'אייר' && n === 18) return ['ל״ג בעומר', 0];
    if (m === 'סיוון' && n === 6) return ['שבועות', 1];
    if (m === 'אב' && n === 9) return ['תשעה באב', 0];
    return null;
  }
  function pad(n){ return (n < 10 ? '0' : '') + n; }
  function iso(d){ return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function parse(v){ var m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(v || ''); return m ? new Date(+m[1], m[2] - 1, +m[3], +(m[4] || 9), +(m[5] || 0)) : null; }
  function same(a, b){ return a && b && a.toDateString() === b.toDateString(); }

  var S = {input: null, view: null, sel: null, hh: 9, mm: 0};
  function label(input){
    var span = input.parentNode.querySelector('.hp-heb[data-for="' + input.dataset.hp + '"]'), d = parse(input.value);
    if (!span) return;
    span.textContent = d ? hebText(d) + (holiday(d) ? ' · ' + holiday(d)[0] : '') : '';
  }
  var seq = 0;
  function upgrade(input){
    if (input.dataset.hp || input.hasAttribute('data-native')) return;
    input.dataset.hp = String(++seq);
    var btn = document.createElement('button'); btn.type = 'button'; btn.className = 'hp-open'; btn.textContent = '📅'; btn.title = 'לוח שנה עברי';
    var span = document.createElement('span'); span.className = 'hp-heb'; span.dataset.for = input.dataset.hp;
    input.insertAdjacentElement('afterend', span); input.insertAdjacentElement('afterend', btn);
    btn.addEventListener('click', function(){ open(input); });
    input.addEventListener('click', function(ev){ ev.preventDefault(); open(input); });
    input.addEventListener('keydown', function(ev){ if (ev.key === 'Enter' || (ev.key === ' ' && !input.value) || (ev.altKey && ev.key === 'ArrowDown')) { ev.preventDefault(); open(input); } });
    input.addEventListener('input', function(){ label(input); }); input.addEventListener('change', function(){ label(input); });
    label(input);
  }
  function scan(root){ Array.prototype.forEach.call((root || document).querySelectorAll('input[type=date],input[type=datetime-local]'), upgrade); }

  function open(input){
    S.input = input; var d = parse(input.value);
    S.sel = d; S.view = new Date((d || new Date()).getFullYear(), (d || new Date()).getMonth(), 1);
    S.hh = d ? d.getHours() : 9; S.mm = d ? d.getMinutes() - d.getMinutes() % 5 : 0;
    draw(); box.classList.add('on'); place();
    var focus = box.querySelector('.d.sel') || box.querySelector('.d.today') || box.querySelector('.d:not(:disabled)'); if (focus) focus.focus();
  }
  function close(){ box.classList.remove('on'); if (S.input) S.input.focus(); S.input = null; }
  function place(){
    var r = S.input.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
    var top = r.bottom + 6 + h > window.innerHeight ? Math.max(8, r.top - h - 6) : r.bottom + 6;
    box.style.top = top + 'px'; box.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w)) + 'px';
  }
  function bounds(){ return {min: parse(S.input.min), max: parse(S.input.max)}; }
  function draw(){
    var timed = S.input.type === 'datetime-local', b = bounds(), today = new Date();
    var first = S.view, start = addDays(first, -first.getDay()), last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
    var h1 = heb(first), h2 = heb(last);
    var title = '<b>' + CIVIL.format(first) + '</b><span>' + h1.m + (h1.m !== h2.m ? ' – ' + h2.m : '') + ' ' + gem(h2.y) + '</span>';
    var html = '<div class="hd"><button type="button" class="nav" data-go="-1" title="החודש הקודם">›</button><div class="t">' + title + '</div><button type="button" class="nav" data-go="1" title="החודש הבא">‹</button></div><div class="g">';
    ['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש'].forEach(function(w, i){ html += '<div class="wd' + (i === 6 ? ' sh' : '') + '">' + w + '</div>'; });
    for (var i = 0; i < 42; i++) {
      var d = addDays(start, i); if (i >= 35 && d.getMonth() !== first.getMonth()) break;
      var h = heb(d), hol = holiday(d), off = (b.min && d < new Date(b.min.getFullYear(), b.min.getMonth(), b.min.getDate())) || (b.max && d > b.max);
      var cls = 'd' + (d.getMonth() !== first.getMonth() ? ' out' : '') + (d.getDay() === 6 ? ' sh' : '') + (hol ? ' hol' : '') + (same(d, today) ? ' today' : '') + (same(d, S.sel) ? ' sel' : '');
      html += '<button type="button" class="' + cls + '" data-day="' + iso(d) + '"' + (off ? ' disabled' : '') + ' title="' + LONG.format(d) + ' · ' + hebText(d) + (hol ? ' · ' + hol[0] : '') + (d.getDay() === 6 ? ' · שבת' : '') + '">' +
        (h.d === 1 ? '<span class="m1">' + h.m + '</span>' : '') + '<b>' + d.getDate() + '</b><i>' + (hol && hol[1] ? '✡' : gem(h.d)) + '</i></button>';
    }
    html += '</div><div class="info" id="hp-info">' + (S.sel ? LONG.format(S.sel) + ' · ' + hebText(S.sel) + (holiday(S.sel) ? ' · ' + holiday(S.sel)[0] : '') : 'בוחרים יום') + '</div>';
    if (timed) {
      var hours = '', mins = '';
      for (var hh = 0; hh < 24; hh++) hours += '<option value="' + hh + '"' + (hh === S.hh ? ' selected' : '') + '>' + pad(hh) + '</option>';
      for (var mm = 0; mm < 60; mm += 5) mins += '<option value="' + mm + '"' + (mm === S.mm ? ' selected' : '') + '>' + pad(mm) + '</option>';
      html += '<div class="tm">🕘 שעה <select id="hp-m" aria-label="דקות">' + mins + '</select>:<select id="hp-h" aria-label="שעה">' + hours + '</select></div>';
    }
    html += '<div class="ft"><button type="button" data-q="0">היום</button><button type="button" data-q="1">מחר</button><button type="button" data-q="7">בעוד שבוע</button>' +
      (S.input.required ? '' : '<button type="button" data-q="clear">ניקוי</button>') + (timed ? '<button type="button" class="ok" data-q="ok">אישור</button>' : '') + '</div>';
    box.innerHTML = html;
  }
  function commit(){
    if (!S.input) return; var timed = S.input.type === 'datetime-local', d = S.sel;
    S.input.value = d ? iso(d) + (timed ? 'T' + pad(S.hh) + ':' + pad(S.mm) : '') : '';
    S.input.dispatchEvent(new Event('input', {bubbles: true})); S.input.dispatchEvent(new Event('change', {bubbles: true}));
    label(S.input); close();
  }
  box.addEventListener('click', function(ev){
    var t = ev.target.closest('button'); if (!t || t.disabled) return;
    if (t.dataset.go) { S.view = new Date(S.view.getFullYear(), S.view.getMonth() + +t.dataset.go, 1); draw(); return; }
    if (t.dataset.day) { S.sel = parse(t.dataset.day); if (S.input.type === 'datetime-local') { draw(); var f = box.querySelector('.d.sel'); if (f) f.focus(); } else commit(); return; }
    var q = t.dataset.q;
    if (q === 'clear') { S.sel = null; commit(); return; }
    if (q === 'ok') { if (S.sel) commit(); return; }
    if (q !== undefined) { var n = new Date(); n = new Date(n.getFullYear(), n.getMonth(), n.getDate() + +q); S.sel = n; S.view = new Date(n.getFullYear(), n.getMonth(), 1);
      if (S.input.type === 'datetime-local') draw(); else commit(); }
  });
  box.addEventListener('change', function(ev){ if (ev.target.id === 'hp-h') S.hh = +ev.target.value; if (ev.target.id === 'hp-m') S.mm = +ev.target.value; });
  box.addEventListener('keydown', function(ev){
    if (ev.key === 'Escape') { ev.stopPropagation(); close(); return; }
    var cell = ev.target.closest && ev.target.closest('.d'); if (!cell) return;
    var step = {ArrowLeft: 1, ArrowRight: -1, ArrowDown: 7, ArrowUp: -7}[ev.key];             // RTL: left = the next day
    if (step) { ev.preventDefault(); var d = addDays(parse(cell.dataset.day), step);
      if (d.getMonth() !== S.view.getMonth()) { S.view = new Date(d.getFullYear(), d.getMonth(), 1); draw(); }
      var next = box.querySelector('[data-day="' + iso(d) + '"]'); if (next) next.focus(); }
  });
  document.addEventListener('mousedown', function(ev){ if (box.classList.contains('on') && !box.contains(ev.target) && ev.target !== S.input && !ev.target.closest('.hp-open')) close(); });
  window.addEventListener('resize', function(){ if (S.input) place(); });
  scan(document);
  new MutationObserver(function(list){ list.forEach(function(m){ Array.prototype.forEach.call(m.addedNodes, function(n){ if (n.nodeType === 1) { if (n.matches && n.matches('input[type=date],input[type=datetime-local]')) upgrade(n); else if (n.querySelectorAll) scan(n); } }); }); })
    .observe(document.body, {childList: true, subtree: true});
  window.HebPicker = {open: open, hebText: hebText, gem: gem, holiday: holiday};
})();
</script>
"""
