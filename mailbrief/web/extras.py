"""Page-wide extras shown on every page: the loading animation and the Ctrl+K command palette (plain JS, no libraries)."""

STYLE = """
#mb-load{position:fixed;inset:0;z-index:50;display:none;place-items:center;background:color-mix(in srgb,var(--bg) 78%,transparent);
backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
#mb-load.on{display:grid;animation:mbfade .25s ease}@keyframes mbfade{from{opacity:0}}
#mb-load .card{text-align:center;background:var(--surface);border:1px solid var(--line);border-radius:24px;padding:28px 36px;box-shadow:var(--shadow);min-width:280px}
#mb-load .sky{position:relative;height:90px;overflow:hidden}
#mb-load .env{position:absolute;inset-inline-start:50%;top:18px;font-size:46px;animation:mbfly 1.6s ease-in-out infinite;transform:translateX(50%)}
@keyframes mbfly{0%{transform:translate(50%,6px) rotate(-8deg)}50%{transform:translate(50%,-8px) rotate(8deg)}100%{transform:translate(50%,6px) rotate(-8deg)}}
#mb-load .spark{position:absolute;font-size:16px;opacity:0;animation:mbspark 1.6s ease-in-out infinite}
#mb-load .spark.a{top:10px;inset-inline-start:28%}#mb-load .spark.b{top:52px;inset-inline-start:66%;animation-delay:.5s}#mb-load .spark.c{top:24px;inset-inline-start:72%;animation-delay:1s}
@keyframes mbspark{0%,100%{opacity:0;transform:scale(.4)}40%{opacity:1;transform:scale(1.1)}}
#mb-load .track{height:6px;border-radius:99px;background:var(--line);overflow:hidden;margin:14px 0 10px}
#mb-load .track i{display:block;height:100%;width:40%;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--accent-2));animation:mbbar 1.3s ease-in-out infinite}
@keyframes mbbar{0%{transform:translateX(160%)}100%{transform:translateX(-260%)}}
#mb-load .msg{font-weight:500}#mb-load .sub{color:var(--muted);font-size:13px;min-height:20px}
#mb-load .x{position:absolute;top:14px;inset-inline-end:16px;font:inherit;border:0;background:transparent;color:var(--muted);cursor:pointer;font-size:18px}
@media (prefers-reduced-motion:reduce){#mb-load .env,#mb-load .spark,#mb-load .track i{animation:none}#mb-load .spark{opacity:1}}
.kbtn{font-size:12.5px;border:1px dashed var(--line);border-radius:999px;padding:5px 10px;color:var(--muted);background:transparent;cursor:pointer;white-space:nowrap;font-family:inherit}
.kbtn:hover{border-color:var(--accent);color:var(--ink)}
.tbtn{font-size:16px;line-height:1;border:1px solid var(--line);border-radius:999px;width:34px;height:32px;background:var(--surface);cursor:pointer;
display:inline-grid;place-items:center;padding:0;flex:none}.tbtn:hover{border-color:var(--accent)}
#mb-bar{position:fixed;top:0;inset-inline:0;height:3px;z-index:90;pointer-events:none;opacity:0;transform:scaleX(0);transform-origin:right;
background:linear-gradient(90deg,var(--accent-2),var(--accent));box-shadow:0 0 10px var(--accent)}
#mb-bar.on{opacity:1;animation:mbgrow 6s cubic-bezier(.1,.8,.2,1) forwards}@keyframes mbgrow{from{transform:scaleX(0)}to{transform:scaleX(.92)}}
#mb-bar.done{opacity:0;transform:scaleX(1);transition:transform .2s ease,opacity .35s ease .2s}
.busy{pointer-events:none;opacity:.9}
.busy::before{content:'';display:inline-block;width:.85em;height:.85em;margin-inline-end:7px;vertical-align:-1px;border-radius:50%;
border:2px solid currentColor;border-top-color:transparent;animation:mbspin .7s linear infinite}
@keyframes mbspin{to{transform:rotate(360deg)}}
#mb-pal{position:fixed;inset:0;z-index:60;display:none;align-items:flex-start;justify-content:center;padding-top:12vh;background:rgba(20,10,40,.35)}
#mb-pal.on{display:flex;animation:mbfade .15s ease}
#mb-pal .box2{width:min(560px,92vw);background:var(--surface);border:1px solid var(--line);border-radius:18px;box-shadow:0 24px 60px rgba(20,10,40,.3);overflow:hidden}
#mb-pal input{width:100%;font:inherit;font-size:17px;padding:16px 18px;border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--ink);outline:none}
#mb-pal ul{list-style:none;margin:0;padding:6px;max-height:50vh;overflow:auto}
#mb-pal li{padding:10px 12px;border-radius:10px;cursor:pointer;display:flex;justify-content:space-between;gap:8px}
#mb-pal li.sel{background:color-mix(in srgb,var(--accent) 14%,transparent)}#mb-pal li small{color:var(--muted)}
#mb-pal .hint{padding:8px 14px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}
"""


HTML = """
<div id="mb-bar"></div>
<div id="mb-load" role="status" aria-live="polite"><div class="card" style="position:relative">
<button class="x" type="button" title="הסתרה" onclick="MB.hide()">✕</button>
<div class="sky"><span class="env">📬</span><span class="spark a">✨</span><span class="spark b">✨</span><span class="spark c">⭐</span></div>
<div class="track"><i></i></div><div class="msg" id="mb-msg">רגע אחד…</div><div class="sub" id="mb-sub"></div></div></div>
<div id="mb-pal" onclick="if(event.target===this)MB.close()"><div class="box2">
<input id="mb-q" placeholder="לאן הולכים? אפשר גם להקליד מה לחפש במייל…" autocomplete="off">
<ul id="mb-list"></ul><div class="hint">↑↓ בחירה · Enter פתיחה · Esc סגירה · Ctrl+K מכל דף</div></div></div>
<script>
(function(){
  var MSGS = {
    '/today': ['מכינה את היום שלך…', 'בודקת מזג אוויר, יומן ומשימות'],
    '/search': ['מחפשת בכל התיבות…', 'עוברת על המיילים — זה יכול לקחת כמה שניות'],
    '/import_receipts': ['מייבאת קבלות מ-90 הימים האחרונים…', 'זה לוקח כמה דקות — אפשר להשאיר את הדף פתוח'],
    '/archive_backfill': ['שומרת מיילים חשובים בארכיון…', 'זה לוקח כמה דקות'],
    '/run': ['מכינה תדריך…', 'קוראת את כל התיבות'],
    '/health': ['בודקת שהכול תקין…', 'מתחברת לכל תיבה ולכל שירות'],
    '/check': ['בודקת מיילים חדשים…', ''],
    '/build_history': ['בונה היסטוריה…', 'עוברת על 30 הימים האחרונים'],
    '/wf_test': ['בודקת מה האוטומציה הייתה תופסת…', 'עוברת על השבוע האחרון'],
    '/first_look': ['עוברת על 30 הימים האחרונים…', 'ניוזלטרים, מנויים ומי מחכה לתשובה — דקה-שתיים']
  };
  var LONG = ['עדיין עובדת על זה ☕', 'כמעט שם…', 'מיילים רבים, סבלנות קטנה 🙂'];
  var el = document.getElementById('mb-load'), timer = null, ticker = null;
  function show(path){
    var m = MSGS[path] || ['טוען…', ''];
    document.getElementById('mb-msg').textContent = m[0];
    document.getElementById('mb-sub').textContent = m[1];
    clearTimeout(timer); clearInterval(ticker);
    timer = setTimeout(function(){
      el.classList.add('on'); var n = 0;
      ticker = setInterval(function(){ document.getElementById('mb-sub').textContent = LONG[n++ % LONG.length]; }, 7000);
    }, 350);                                  // quick pages never show it
  }
  function hide(){ clearTimeout(timer); clearInterval(ticker); el.classList.remove('on'); }
  function local(url){ try { var u = new URL(url, location.href); return u.origin === location.origin ? u : null; } catch(e){ return null; } }
  // ---- instant tab switching (like the surprise box): fetch the page, swap only <main> ----
  var bar = document.getElementById('mb-bar'), cache = {};
  function progress(on){
    if (on) { bar.className = ''; void bar.offsetWidth; bar.className = 'on'; }
    else { bar.className = 'done'; setTimeout(function(){ if (bar.className === 'done') bar.className = ''; }, 700); }
  }
  function busy(el){ if (el && el.classList) el.classList.add('busy'); }
  function swappable(u){ return u.origin === location.origin && !/^[/](reports|unsub|oauth)/.test(u.pathname) && document.querySelector('main'); }
  function load(path){
    var hit = cache[path];
    if (hit && Date.now() - hit.t < 15000) return hit.p;
    var p = fetch(path, {credentials: 'same-origin'}).then(function(r){
      if (!r.ok) throw new Error(r.status);
      return r.text().then(function(t){ return {html: t, url: r.url}; });
    });
    cache[path] = {t: Date.now(), p: p};
    p.catch(function(){ delete cache[path]; });
    return p;
  }
  function setActive(path){
    Array.prototype.forEach.call(document.querySelectorAll('nav.tabs a'), function(a){
      var p = new URL(a.href).pathname;
      a.classList.toggle('on', p === path || (p === '/clients' && path === '/client'));
    });
  }
  function runScripts(root){
    Array.prototype.forEach.call(root.querySelectorAll('script'), function(old){
      var s = document.createElement('script'); s.textContent = old.textContent; old.parentNode.replaceChild(s, old);
    });
  }
  function navigate(href, push, trigger){
    var u = new URL(href, location.href), main = document.querySelector('main');
    busy(trigger); progress(true); main.classList.add('fading');
    var slow = setTimeout(function(){ show(u.pathname); }, 1600);   // really slow: the big loading card too
    load(u.pathname + u.search).then(function(res){
      var doc = new DOMParser().parseFromString(res.html, 'text/html'), fresh = doc.querySelector('main');
      if (!fresh) throw new Error('no page');
      var final = new URL(res.url);
      document.title = doc.title;
      main.innerHTML = fresh.innerHTML;
      runScripts(main);
      if (push) history.pushState({mb: 1}, '', final.pathname + final.search + u.hash);
      setActive(final.pathname);
      clearTimeout(slow); hide(); progress(false);
      main.classList.remove('fading', 'swap'); void main.offsetWidth; main.classList.add('swap');
      if (trigger && trigger.classList) trigger.classList.remove('busy');
      var target = u.hash && document.getElementById(u.hash.slice(1)), tabs = document.getElementById('mb-tabs');
      if (target) target.scrollIntoView({behavior: 'smooth'});
      else if (push && tabs && window.scrollY > tabs.offsetTop) window.scrollTo({top: tabs.offsetTop, behavior: 'smooth'});
      if (window.MB.fx) window.MB.fx();
    }).catch(function(){ location.href = href; });
  }
  document.addEventListener('click', function(ev){
    var a = ev.target.closest && ev.target.closest('a[href]');
    if (!a || ev.defaultPrevented || ev.button || ev.ctrlKey || ev.metaKey || ev.shiftKey || a.target === '_blank' || a.hasAttribute('download')) return;
    var u = local(a.href);
    if (!u || (u.pathname === location.pathname && u.search === location.search && u.hash)) return;
    if (swappable(u)) { ev.preventDefault(); navigate(u.href, true, a.closest('nav.tabs') || a.classList.contains('gift') ? a : null); return; }
    busy(a); progress(true); show(u.pathname);
  });
  document.addEventListener('submit', function(ev){
    var f = ev.target, b = ev.submitter;
    if (ev.defaultPrevented) return;
    var action = (b && b.getAttribute('formaction')) || f.getAttribute('action') || location.pathname;
    var u = local(action);
    if (!u || f.target === '_blank') return;
    if ((f.getAttribute('method') || 'get').toLowerCase() === 'get' && swappable(u)) {   // search box etc.
      ev.preventDefault();
      u.search = new URLSearchParams(new FormData(f, b)).toString();
      navigate(u.href, true, b);
      return;
    }
    cache = {};                                 // something changes: don't reuse prefetched pages
    busy(b); progress(true); show(u.pathname);
  });
  document.addEventListener('pointerover', function(ev){        // start loading a tab the moment the mouse is on it
    var a = ev.target.closest && ev.target.closest('nav.tabs a, a.gift');
    if (a) { var u = local(a.href); if (u && u.pathname !== location.pathname) load(u.pathname + u.search); }
  });
  window.addEventListener('popstate', function(){ navigate(location.href, false); });
  window.addEventListener('pageshow', function(){ hide(); progress(false);
    Array.prototype.forEach.call(document.querySelectorAll('.busy'), function(b){ b.classList.remove('busy'); }); });

  // the typed line under the name, like the surprise box
  var hello = document.getElementById('mb-hello');
  if (hello) {
    var h = new Date().getHours();
    var greet = h < 5 ? 'לילה טוב' : h < 12 ? 'בוקר טוב' : h < 17 ? 'צהריים טובים' : h < 21 ? 'ערב טוב' : 'לילה טוב';
    var who = hello.dataset.name, back = hello.dataset.back;   // from the first-run welcome
    hello.textContent = greet + (who ? ' ' + who : '') + (back ? ', ' + back : '') + '!';
  }
  var nav = document.getElementById('mb-tabs');
  function stuck(){ if (nav) nav.classList.toggle('stuck', window.scrollY > 0 && nav.getBoundingClientRect().top <= 0.5); }
  window.addEventListener('scroll', stuck, {passive: true}); stuck();
  var LINES = ['MailBrief — המייל שלך, מסודר ✨', 'בלי AI, בלי ענן — הכול נשאר במחשב שלך 🔒', 'קבלות, אוטומציות, יומן ומשימות — במקום אחד',
               'בשבת ובחג הכול נח 🕯️', 'Ctrl+K — לכל מקום בשנייה ⌨️'];
  var typed = document.getElementById('mb-type'), li = 0, ci = 0, back = false;
  function type(){
    if (!typed) return;
    var line = LINES[li];
    if (!back) { ci++; if (ci > line.length) { back = true; return setTimeout(type, 2200); } }
    else { ci -= 2; if (ci <= 0) { ci = 0; back = false; li = (li + 1) % LINES.length; } }
    typed.textContent = Array.from(line).slice(0, ci).join('');
    setTimeout(type, back ? 25 : 55);
  }
  if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) { if (typed) typed.textContent = LINES[0]; } else type();
  window.addEventListener('keydown', function(ev){ if (ev.key === 'Escape') { hide(); close(); } });

  var ITEMS = [
    ['☀️ היום שלי', '/today'], ['🔎 30 הימים שלי במבט אחד', '/insights'], ['⚙️ הגדרות ותיבות', '/'], ['📊 לוח בקרה', '/dashboard'], ['📈 המייל במספרים', '/stats'],
    ['⚡ אוטומציות', '/automations'], ['👥 לקוחות', '/clients'], ['📚 רשימת קריאה', '/reading'], ['🔍 חיפוש', '/search'],
    ['❓ מדריך ובדיקת תקינות', '/help'], ['📅 חיבור יומן ומשימות', '/#gapps'], ['🏖️ מצב חופשה', '/#vacation'],
    ['📝 תבניות תשובה', '/#templates'], ['🏷️ הכללים שלי', '/#rules'], ['📰 ניוזלטרים וביטול מנויים', '/#news'],
    ['✉️ סיכום יומי במייל', '/#daily'], ['👤 הפרופיל שלי', '/#profile'],
    ['📅 Google Calendar', 'https://calendar.google.com/'], ['✅ Google Tasks', 'https://tasks.google.com/']
  ];
  var pal = document.getElementById('mb-pal'), q = document.getElementById('mb-q'), list = document.getElementById('mb-list'), sel = 0, shown = [];
  function norm(s){ return s.toLowerCase().replace(/[^\\p{L}\\p{N} ]/gu, '').trim(); }
  function render(){
    var text = q.value.trim(), t = norm(text);
    shown = ITEMS.filter(function(i){ return !t || norm(i[0]).indexOf(t) >= 0; });
    if (text) shown.push(['🔍 חיפוש בכל התיבות: „' + text + '”', '/search?q=' + encodeURIComponent(text)]);
    sel = Math.min(sel, shown.length - 1); if (sel < 0) sel = 0;
    list.innerHTML = '';
    shown.forEach(function(i, n){
      var li = document.createElement('li'); li.textContent = i[0];
      if (i[1].indexOf('http') === 0) { var s = document.createElement('small'); s.textContent = '↗'; li.appendChild(s); }
      if (n === sel) li.className = 'sel';
      li.onmouseenter = function(){ sel = n; mark(); }; li.onclick = function(){ go(n); };
      list.appendChild(li);
    });
  }
  function mark(){ Array.prototype.forEach.call(list.children, function(li, n){ li.className = n === sel ? 'sel' : ''; }); }
  function go(n){
    var i = shown[n]; if (!i) return; close();
    if (i[1].indexOf('http') === 0) { window.open(i[1], '_blank'); return; }
    var u = new URL(i[1], location.href);
    if (u.pathname === location.pathname && u.hash) { location.hash = u.hash; return; }
    if (swappable(u)) navigate(u.href, true); else { show(u.pathname); location.href = i[1]; }
  }
  function open(){ pal.classList.add('on'); q.value = ''; sel = 0; render(); setTimeout(function(){ q.focus(); }, 0); }
  function close(){ pal.classList.remove('on'); }
  q.addEventListener('input', function(){ sel = 0; render(); });
  q.addEventListener('keydown', function(ev){
    if (ev.key === 'ArrowDown') { sel = (sel + 1) % shown.length; mark(); ev.preventDefault(); }
    else if (ev.key === 'ArrowUp') { sel = (sel - 1 + shown.length) % shown.length; mark(); ev.preventDefault(); }
    else if (ev.key === 'Enter') { go(sel); ev.preventDefault(); }
  });
  window.addEventListener('keydown', function(ev){
    var typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if ((ev.ctrlKey || ev.metaKey) && (ev.key === 'k' || ev.key === 'K' || ev.code === 'KeyK')) { ev.preventDefault(); pal.classList.contains('on') ? close() : open(); }
    else if (ev.key === '/' && !typing && !pal.classList.contains('on')) { ev.preventDefault(); open(); }
  });
  var MODES = ['auto', 'light', 'dark'], ICONS = {auto: '🌗', light: '☀️', dark: '🌙'},
      NAMES = {auto: 'לפי Windows', light: 'בהיר', dark: 'כהה'};
  function mode(){ try { return localStorage.getItem('mb-theme') || 'auto'; } catch(e){ return 'auto'; } }
  function paint(){
    var m = mode(), b = document.getElementById('mb-theme');
    if (m === 'auto') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', m);
    if (b) { b.textContent = ICONS[m]; b.title = 'מצב תצוגה: ' + NAMES[m] + ' (לחיצה להחלפה)'; }
  }
  function theme(){
    var next = MODES[(MODES.indexOf(mode()) + 1) % MODES.length];
    try { localStorage.setItem('mb-theme', next); } catch(e){}
    paint();
  }
  paint();
  window.addEventListener('storage', paint);  // another open tab switched
  window.MB = {show: show, hide: hide, open: open, close: close, theme: theme};
})();
</script>"""


# ---- animations and the focus timer ----------------------------------------------------------------------------------

STYLE += """
.pop{animation:mbpop .5s cubic-bezier(.2,.8,.2,1.15) backwards}
@keyframes mbpop{from{opacity:0;transform:translateY(14px) scale(.97)}}
.floaty{display:inline-block;animation:mbfloat 4s ease-in-out infinite}
@keyframes mbfloat{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-5px) rotate(12deg)}}
button,.kbtn,.tbtn{position:relative;overflow:hidden}
.ripple{position:absolute;border-radius:50%;pointer-events:none;background:currentColor;opacity:.28;transform:scale(0);animation:mbripple .55s ease-out forwards}
@keyframes mbripple{to{transform:scale(2.6);opacity:0}}
.box h3{transition:transform .2s}.box:hover h3{transform:translateX(-3px)}
main > .item.urgent:first-of-type,main > div > .item.urgent{animation:mbslide .5s cubic-bezier(.2,.8,.2,1.2) both}
@keyframes mbslide{from{opacity:0;transform:translateY(-10px) scale(.98)}}
#mb-confetti{position:fixed;inset:0;pointer-events:none;z-index:70}
.fchip{display:none;font-size:13px;font-weight:500;border-radius:999px;padding:5px 11px;color:#fff;cursor:pointer;white-space:nowrap;border:0;
background:linear-gradient(90deg,var(--accent),var(--accent-2));font-variant-numeric:tabular-nums;box-shadow:0 4px 14px color-mix(in srgb,var(--accent) 35%,transparent)}
.fchip.on{display:inline-block;animation:mbpulse 2s ease-in-out infinite}
@keyframes mbpulse{50%{box-shadow:0 4px 22px color-mix(in srgb,var(--accent-2) 55%,transparent)}}
.focus{display:grid;place-items:center;gap:8px;text-align:center}
.focus .ring{position:relative;width:150px;height:150px}.focus .ring svg{transform:rotate(-90deg)}
.focus .ring .t{position:absolute;inset:0;display:grid;place-items:center;font-size:30px;font-weight:700;font-variant-numeric:tabular-nums}
.focus .ring circle.bar2{transition:stroke-dashoffset .5s linear}
.focus .row{display:flex;gap:6px;flex-wrap:wrap;justify-content:center}
.focus .row button{font:inherit;font-size:13px;padding:5px 12px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer}
.focus .row button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
textarea.notes{width:100%;min-height:150px;font:inherit;font-size:15px;line-height:1.6;padding:10px 12px;border-radius:12px;border:1px solid var(--line);
background:color-mix(in srgb,#fde68a 16%,var(--surface));color:var(--ink);resize:vertical}
.saved{font-size:12px;color:var(--good);opacity:0;transition:opacity .3s}.saved.on{opacity:1}
@media (prefers-reduced-motion:reduce){.pop,.floaty,.fchip.on,.ripple{animation:none!important}}
"""

HTML += """
<canvas id="mb-confetti"></canvas>
<script>
(function(){
  var still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  function fx(){
  // cards and rows rise one after another
  if (!still) Array.prototype.forEach.call(document.querySelectorAll('main .box, main .kpi, main > .item, main section > .item, main .scroll'), function(el, i){
    el.style.animationDelay = Math.min(i * 45, 700) + 'ms'; el.classList.add('pop');
  });

  // numbers count up (KPI cards)
  if (!still) Array.prototype.forEach.call(document.querySelectorAll('.kpi b'), function(el){
    var text = el.textContent, m = text.match(/^([^\\d-]*)(-?[\\d,]+(?:\\.\\d+)?)(.*)$/);
    if (!m) return;
    var target = parseFloat(m[2].replace(/,/g, '')), dec = (m[2].split('.')[1] || '').length, t0 = null;
    if (!isFinite(target) || target === 0) return;
    function step(t){
      t0 = t0 || t; var p = Math.min(1, (t - t0) / 900), v = target * (1 - Math.pow(1 - p, 3));
      el.textContent = m[1] + v.toLocaleString('en-US', {minimumFractionDigits: dec, maximumFractionDigits: dec}) + m[3];
      if (p < 1) requestAnimationFrame(step); else el.textContent = text;
    }
    requestAnimationFrame(step);
  });
  }
  fx();

  // ripple on every button
  document.addEventListener('pointerdown', function(ev){
    var b = ev.target.closest && ev.target.closest('button,.kbtn,.tbtn');
    if (!b || still) return;
    var r = b.getBoundingClientRect(), s = Math.max(r.width, r.height), d = document.createElement('span');
    d.className = 'ripple'; d.style.width = d.style.height = s + 'px';
    d.style.left = (ev.clientX - r.left - s / 2) + 'px'; d.style.top = (ev.clientY - r.top - s / 2) + 'px';
    b.appendChild(d); setTimeout(function(){ d.remove(); }, 600);
  });

  // confetti
  var cv = document.getElementById('mb-confetti'), cx = cv.getContext('2d'), bits = [], running = false;
  function confetti(n, ox, oy){
    if (still) return;
    cv.width = innerWidth; cv.height = innerHeight;
    var colors = ['#7c3aed', '#f97316', '#a78bfa', '#fbbf24', '#16a34a', '#ec4899', '#06b6d4'];
    var x0 = ox == null ? innerWidth / 2 : ox, y0 = oy == null ? innerHeight / 3 : oy, spread = ox == null ? 200 : 40;
    for (var i = 0; i < (n || 140); i++) bits.push({x: x0 + (Math.random() - .5) * spread, y: y0,
      vx: (Math.random() - .5) * 14, vy: -Math.random() * 12 - 4, r: Math.random() * 6 + 4, c: colors[i % colors.length],
      a: Math.random() * 6, va: (Math.random() - .5) * .3, life: 0});
    if (!running) { running = true; requestAnimationFrame(tick); }
  }
  function tick(){
    cx.clearRect(0, 0, cv.width, cv.height);
    bits = bits.filter(function(b){ return b.y < cv.height + 20 && b.life < 260; });
    bits.forEach(function(b){
      b.vy += .32; b.vx *= .99; b.x += b.vx; b.y += b.vy; b.a += b.va; b.life++;
      cx.save(); cx.translate(b.x, b.y); cx.rotate(b.a); cx.fillStyle = b.c; cx.fillRect(-b.r / 2, -b.r / 4, b.r, b.r / 2); cx.restore();
    });
    if (bits.length) requestAnimationFrame(tick); else { running = false; cx.clearRect(0, 0, cv.width, cv.height); }
  }
  // finishing a task (or adding an invitation / recipe) celebrates on the next page
  document.addEventListener('submit', function(ev){
    var a = (ev.submitter && ev.submitter.getAttribute('formaction')) || ev.target.getAttribute('action') || '';
    if (/gtask_done|invite_add|wf_recipe/.test(a)) try { sessionStorage.setItem('mb-party', '1'); } catch(e){}
  });
  try { if (sessionStorage.getItem('mb-party')) { sessionStorage.removeItem('mb-party'); setTimeout(function(){ confetti(); }, 350); } } catch(e){}

  // focus timer: the end time lives in localStorage, so it keeps running across pages
  var chip = document.getElementById('mb-focus'), LEN = {focus: 25, short: 5, long: 15}, NAMES = {focus: 'ריכוז', short: 'הפסקה קצרה', long: 'הפסקה ארוכה'};
  function get(){ try { return JSON.parse(localStorage.getItem('mb-focus') || 'null'); } catch(e){ return null; } }
  function put(v){ try { v ? localStorage.setItem('mb-focus', JSON.stringify(v)) : localStorage.removeItem('mb-focus'); } catch(e){} }
  function fmt(ms){ var s = Math.max(0, Math.round(ms / 1000)); return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }
  function left(st){ return st.paused != null ? st.paused : st.end - Date.now(); }
  function beep(){
    try {
      var ac = new (window.AudioContext || window.webkitAudioContext)();
      [0, .25, .5].forEach(function(d, i){
        var o = ac.createOscillator(), g = ac.createGain(); o.frequency.value = [660, 880, 990][i];
        o.connect(g); g.connect(ac.destination); g.gain.setValueAtTime(.18, ac.currentTime + d);
        g.gain.exponentialRampToValueAtTime(.001, ac.currentTime + d + .22); o.start(ac.currentTime + d); o.stop(ac.currentTime + d + .25);
      });
    } catch(e){}
  }
  function draw(){
    var st = get(), card = document.getElementById('mb-timer');
    if (st && st.paused == null && st.end <= Date.now()) {
      put(null); beep(); confetti(90);
      if (window.Notification && Notification.permission === 'granted') new Notification('⏱️ ' + NAMES[st.mode] + ' הסתיים', {body: st.mode === 'focus' ? 'כל הכבוד! זמן להפסקה ☕' : 'חוזרים לעבודה 💪'});
      st = null;
    }
    if (chip) {
      chip.classList.toggle('on', !!st);
      if (st) chip.textContent = (st.mode === 'focus' ? '🍅 ' : '☕ ') + fmt(left(st)) + (st.paused != null ? ' ⏸' : '');
    }
    if (card) {
      var mode = st ? st.mode : (card.dataset.mode || 'focus'), total = LEN[mode] * 60000, ms = st ? left(st) : total;
      card.querySelector('.t').textContent = fmt(ms);
      card.querySelector('.bar2').style.strokeDashoffset = String(2 * Math.PI * 64 * (1 - ms / total));
      card.querySelector('[data-go]').textContent = !st ? '▶ התחלה' : st.paused != null ? '▶ המשך' : '⏸ השהיה';
      Array.prototype.forEach.call(card.querySelectorAll('[data-mode]'), function(b){ b.classList.toggle('on', b.dataset.mode === mode); });
      card.querySelector('.lbl').textContent = NAMES[mode];
    }
  }
  window.MBFocus = {
    mode: function(m){ var card = document.getElementById('mb-timer'); if (get()) return; if (card) card.dataset.mode = m; draw(); },
    go: function(){
      var st = get(), card = document.getElementById('mb-timer');
      if (!st) {
        var m = (card && card.dataset.mode) || 'focus';
        put({mode: m, end: Date.now() + LEN[m] * 60000});
        if (window.Notification && Notification.permission === 'default') Notification.requestPermission();
      } else if (st.paused != null) { st.end = Date.now() + st.paused; st.paused = null; put(st); }
      else { st.paused = st.end - Date.now(); put(st); }
      draw();
    },
    reset: function(){ put(null); draw(); }
  };
  if (chip) chip.onclick = function(){ location.href = '/today#focus'; };
  draw(); setInterval(draw, 1000);
  window.addEventListener('storage', draw);
  window.MB.confetti = confetti;
  function hello(){ var g = document.getElementById('mb-gift'), r = g ? g.getBoundingClientRect() : {top: 90};
    confetti(110, innerWidth * .25, r.top + 90); setTimeout(function(){ confetti(110, innerWidth * .75, r.top + 90); }, 180); }
  try { if (!sessionStorage.getItem('mb-hello')) { sessionStorage.setItem('mb-hello', '1'); setTimeout(hello, 400); } } catch(e){}
  var gift = document.getElementById('mb-gift'); if (gift) gift.onclick = hello;   // the envelope throws confetti, like the gift
  window.MB.fx = function(){ fx(); draw(); };
})();
</script>"""


BOOT = ("<script>try{var t=localStorage.getItem('mb-theme');if(t==='light'||t==='dark')"
        "document.documentElement.setAttribute('data-theme',t)}catch(e){}</script>")
