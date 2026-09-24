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
    '/greetings': ['מתזמנת את הברכות…', ''],
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
    if (!u && /^https?:/.test(a.href)) { a.target = '_blank'; return; }      // another site: the user's own browser
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
    ['☀️ היום שלי', '/today'], ['⚡ מיון מהיר', '/triage'], ['✉️ מייל מתוזמן', '/compose'], ['🗓️ ברכות חג ללקוחות', '/greetings'], ['🔎 30 הימים שלי במבט אחד', '/insights'],
    ['⚙️ הגדרות ותיבות', '/?s=boxes'], ['👤 הפרופיל שלי', '/?s=me#profile'], ['✉️ סיכום יומי במייל', '/?s=me#daily'], ['🔕 שעות שקטות ו-VIP', '/?s=me#quiet'],
    ['🧾 חשבוניות שלא הגיעו', '/?s=money#missing'], ['🧮 מע״מ החודש', '/?s=money#vat'], ['🏷️ סיווג ספקים', '/?s=money#vendors'],
    ['📦 לרואה החשבון', '/?s=money#accountant'], ['📤 ייצוא לחשבשבת', '/?s=money#export'],
    ['💰 מעקב תשלומים מלקוחות', '/?s=clients#debts'], ['🎂 ימי הולדת של לקוחות', '/?s=clients#dates'],
    ['🏷️ הכללים שלי', '/?s=auto#rules'], ['📝 תבניות תשובה', '/?s=auto#templates'], ['🏖️ מצב חופשה', '/?s=auto#vacation'],
    ['🧹 ניקוי הדואר הנכנס', '/?s=tidy#clean'], ['✂️ ניוזלטרים שלא נפתחו', '/?s=tidy#unopened'],
    ['☁️ גיבוי ל-Google Drive', '/?s=data#cloud'], ['📦 העברת נתונים', '/?s=data#migrate'], ['📅 חיבור יומן ומשימות', '/?s=connect#gapps'],
    ['📊 לוח בקרה', '/dashboard'], ['📈 המייל במספרים', '/stats'], ['⚡ אוטומציות', '/automations'], ['👥 לקוחות', '/clients'],
    ['📰 ניוזלטרים ורשימת קריאה', '/reading'], ['🔍 חיפוש', '/search'], ['❓ מדריך ובדיקת תקינות', '/help'], ['📋 דוח תקלה', '/help#report'],
    ['📎 כל הקבצים המצורפים', '/files'], ['📊 תקציב חודשי', '/?s=money#budget'], ['⚖️ מי זול יותר', '/?s=money#compare'],
    ['🧾 מסמכים להחזר מס', '/?s=money#tax'], ['⚡ קיצורי טקסט', '/?s=auto#snippets'], ['🔓 בדיקת דליפות', '/?s=me#leaks'],
    ['📋 דוח שבועי לשותף', '/?s=clients#share'], ['🖨️ הדפסת היום שלי', '/today?print=1'],
    ['♿ נגישות', 'javascript:a11y'], ['⌨️ קיצורי מקלדת', 'javascript:keys'], ['🎓 סיור היכרות', 'javascript:tour'],
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
    if (i[1] === 'javascript:a11y') { if (window.MB && MB.a11y) MB.a11y(); return; }
    if (i[1] === 'javascript:keys') { if (window.MB && MB.keys) MB.keys(); return; }
    if (i[1] === 'javascript:tour') { if (window.MB && MB.tour) MB.tour(); return; }
    if (i[1].indexOf('http') === 0) { window.open(i[1], '_blank'); return; }
    var u = new URL(i[1], location.href);
    if (u.pathname === location.pathname && u.search === location.search && u.hash) { location.hash = u.hash; return; }
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
ul.sortable{margin:0;padding-inline-start:18px;max-height:340px;overflow:auto}
ul.sortable li{transition:background-color .3s}ul.sortable li.moved{background:color-mix(in srgb,var(--accent) 10%,transparent)}
.saved{font-size:12px;color:var(--good);opacity:0;transition:opacity .3s}.saved.on{opacity:1}
@media (prefers-reduced-motion:reduce){.pop,.floaty,.fchip.on,.ripple{animation:none!important}}
"""

HTML += """
<canvas id="mb-confetti"></canvas>
<script>
(function(){
  var still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  function sortLists(){
    Array.prototype.forEach.call(document.querySelectorAll('select.mb-sort'), function(sel){
      var list = document.getElementById(sel.dataset.for); if (!list) return;
      function apply(){
        var rows = Array.prototype.slice.call(list.querySelectorAll('li[data-days]')), how = sel.value;
        rows.sort(function(a, b){
          if (how === 'new') return (+a.dataset.days) - (+b.dataset.days);
          if (how === 'name') return a.dataset.name.localeCompare(b.dataset.name, 'he');
          if (how === 'account') return a.dataset.account.localeCompare(b.dataset.account) || (+b.dataset.days) - (+a.dataset.days);
          return (+b.dataset.days) - (+a.dataset.days);
        });
        rows.forEach(function(r){ list.appendChild(r); r.classList.add('moved'); setTimeout(function(){ r.classList.remove('moved'); }, 400); });
      }
      try { sel.value = localStorage.getItem('mb-sort-' + sel.dataset.for) || 'old'; } catch(e){}
      if (sel.value !== 'old') apply();
      sel.onchange = function(){ try { localStorage.setItem('mb-sort-' + sel.dataset.for, sel.value); } catch(e){} apply(); };
    });
  }
  function fx(){
  sortLists();
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


# ---- accessibility (a button on the side of every page) and keyboard shortcuts ----------------------------------------
STYLE += """
#mb-a11y-btn{position:fixed;left:0;top:50%;transform:translateY(-50%);z-index:70;border:1px solid var(--line);border-left:0;
border-radius:0 14px 14px 0;background:var(--accent);color:#fff;font-size:22px;width:44px;height:52px;cursor:pointer;
box-shadow:var(--shadow);display:grid;place-items:center;padding:0}
#mb-a11y-btn:hover,#mb-a11y-btn:focus-visible{width:50px;outline:3px solid var(--accent-2);outline-offset:2px}
#mb-a11y{position:fixed;left:0;top:50%;transform:translate(-110%,-50%);z-index:71;width:min(310px,calc(100vw - 20px));
background:var(--surface);color:var(--ink);border:1px solid var(--line);border-left:0;border-radius:0 20px 20px 0;
box-shadow:0 20px 60px rgba(0,0,0,.25);padding:16px 18px;transition:transform .25s ease;max-height:92vh;overflow:auto}
#mb-a11y.on{transform:translate(0,-50%)}
#mb-a11y h3{margin:0 0 10px;font-size:18px;display:flex;justify-content:space-between;align-items:center}
#mb-a11y .row{display:flex;gap:6px;align-items:center;justify-content:space-between;margin:8px 0}
#mb-a11y button{font:inherit;font-size:14px;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:10px;padding:7px 10px;cursor:pointer}
#mb-a11y button[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff}
#mb-a11y .sizes{flex-direction:column;align-items:stretch}#mb-a11y .sizes span:last-child{display:flex;gap:4px}#mb-a11y .sizes button{flex:1;font-weight:700;padding:7px 4px}
#mb-a11y .note{font-size:12.5px;color:var(--muted);margin:6px 0 0}
html[data-fs="-1"] body{zoom:.92}html[data-fs="1"] body{zoom:1.12}html[data-fs="2"] body{zoom:1.25}html[data-fs="3"] body{zoom:1.4}
html[data-contrast]{--ink:#000;--muted:#1f1f1f;--line:#4a4a4a;--bg:#fff;--surface:#fff;--accent:#4c1d95;--accent-2:#9a3412;--oval:transparent}
@media (prefers-color-scheme:dark){html[data-contrast]:not([data-theme=light]){--ink:#fff;--muted:#e5e5e5;--line:#bdbdbd;--bg:#000;--surface:#000;--accent:#c4b5fd;--accent-2:#fdba74}}
html[data-contrast][data-theme=dark]{--ink:#fff;--muted:#e5e5e5;--line:#bdbdbd;--bg:#000;--surface:#000;--accent:#c4b5fd;--accent-2:#fdba74}
html[data-contrast] a,html[data-links] a{text-decoration:underline!important;text-underline-offset:3px}
html[data-contrast] .g,html[data-contrast] h1.name{background:none!important;-webkit-text-fill-color:currentColor;color:var(--ink)!important}
html[data-contrast] *:focus-visible,html[data-focus] *:focus-visible{outline:3px solid var(--accent-2)!important;outline-offset:2px}
html[data-still] *,html[data-still] *::before,html[data-still] *::after{animation:none!important;transition:none!important}
html[data-spacing] body{letter-spacing:.03em;word-spacing:.14em;line-height:1.85}
html[data-links] a{font-weight:600}
html[data-cursor],html[data-cursor] *{cursor:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'%3E%3Cpath d='M4 2l28 16-12 3-6 12z' fill='black' stroke='white' stroke-width='2'/%3E%3C/svg%3E") 4 2,auto!important}
.mb-reading{background:color-mix(in srgb,var(--accent-2) 22%,transparent)!important;border-radius:6px}
#mb-keys{position:fixed;inset:0;z-index:80;display:none;place-items:center;background:rgba(0,0,0,.35)}
#mb-keys.on{display:grid}
#mb-keys .card{background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:20px;padding:20px 24px;width:min(460px,calc(100vw - 32px));box-shadow:var(--shadow)}
#mb-keys table{width:100%;box-shadow:none}#mb-keys td{padding:5px 8px;font-size:14px}
kbd{font-family:inherit;font-size:12px;border:1px solid var(--line);border-bottom-width:2px;border-radius:6px;padding:1px 6px;background:var(--bg)}
"""

HTML += """
<button id="mb-a11y-btn" type="button" aria-label="נגישות" title="נגישות (Alt+A)" aria-expanded="false" aria-controls="mb-a11y">♿</button>
<div id="mb-a11y" role="dialog" aria-label="התאמות נגישות">
<h3>♿ נגישות <button type="button" data-close aria-label="סגירה">✕</button></h3>
<div class="row sizes"><span>גודל טקסט</span><span><button type="button" data-fs="-1" aria-label="קטן">א-</button>
<button type="button" data-fs="0" aria-label="רגיל">א</button><button type="button" data-fs="1" aria-label="גדול">א+</button>
<button type="button" data-fs="2" aria-label="גדול מאוד">א++</button><button type="button" data-fs="3" aria-label="ענק">א+++</button></span></div>
<div class="row"><span>ניגודיות גבוהה</span><button type="button" data-flag="contrast" aria-pressed="false">כבוי</button></div>
<div class="row"><span>עצירת אנימציות</span><button type="button" data-flag="still" aria-pressed="false">כבוי</button></div>
<div class="row"><span>ריווח טקסט לקריאה נוחה</span><button type="button" data-flag="spacing" aria-pressed="false">כבוי</button></div>
<div class="row"><span>הדגשת קישורים</span><button type="button" data-flag="links" aria-pressed="false">כבוי</button></div>
<div class="row"><span>סמן עכבר גדול</span><button type="button" data-flag="cursor" aria-pressed="false">כבוי</button></div>
<div class="row"><span>מסגרת בולטת במקלדת</span><button type="button" data-flag="focus" aria-pressed="false">כבוי</button></div>
<div class="row"><span>🔊 הקראה</span><span><button type="button" id="mb-read">▶ הקראת הדף</button> <button type="button" id="mb-stop">⏹</button></span></div>
<div class="row"><span>קצב הקראה</span><span><button type="button" data-rate="0.8">איטי</button><button type="button" data-rate="1">רגיל</button><button type="button" data-rate="1.25">מהיר</button></span></div>
<p class="note" id="mb-voice-note">טקסט מסומן? ההקראה מתחילה ממנו. הקול — מ-Windows.</p>
<div class="row"><button type="button" id="mb-a11y-reset">↺ איפוס הכול</button><button type="button" id="mb-keys-open">⌨️ קיצורי מקלדת</button></div>
</div>
<div id="mb-keys" role="dialog" aria-label="קיצורי מקלדת"><div class="card"><h3 style="margin-top:0">⌨️ קיצורי מקלדת</h3>
<table><tbody>
<tr><td><kbd>Ctrl</kbd>+<kbd>K</kbd> או <kbd>/</kbd></td><td>חיפוש מהיר של כל דבר</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>T</kbd></td><td>☀️ היום שלי</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>Q</kbd></td><td>⚡ מיון מהיר</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>M</kbd></td><td>✉️ מייל מתוזמן</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>S</kbd></td><td>⚙️ הגדרות</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>D</kbd></td><td>📊 לוח בקרה</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>N</kbd></td><td>📈 במספרים</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>C</kbd></td><td>👥 לקוחות</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>R</kbd></td><td>📰 ניוזלטרים</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>A</kbd></td><td>⚡ אוטומציות</td></tr>
<tr><td><kbd>G</kbd> ואז <kbd>H</kbd></td><td>❓ מדריך</td></tr>
<tr><td><kbd>Alt</kbd>+<kbd>A</kbd></td><td>♿ נגישות</td></tr>
<tr><td><kbd>?</kbd></td><td>החלון הזה</td></tr>
<tr><td><kbd>Esc</kbd></td><td>סגירה</td></tr>
</tbody></table><p class="note" style="color:var(--muted);font-size:13px">במיון המהיר יש קיצורים משלו: 1–5, R, O, ←, Z.</p></div></div>
<script>
(function(){
  if (window.__mbA11y) return; window.__mbA11y = true;
  var root = document.documentElement, panel = document.getElementById('mb-a11y'), btn = document.getElementById('mb-a11y-btn');
  var FLAGS = ['contrast', 'still', 'spacing', 'links', 'cursor', 'focus'];
  function get(){ try { return JSON.parse(localStorage.getItem('mb-a11y') || '{}'); } catch(e){ return {}; } }
  function put(s){ try { localStorage.setItem('mb-a11y', JSON.stringify(s)); } catch(e){} }
  function apply(){
    var s = get();
    if (s.fs) root.setAttribute('data-fs', s.fs); else root.removeAttribute('data-fs');
    FLAGS.forEach(function(f){ if (s[f]) root.setAttribute('data-' + f, ''); else root.removeAttribute('data-' + f); });
    panel.querySelectorAll('[data-fs]').forEach(function(b){ b.setAttribute('aria-pressed', String((s.fs || 0) == b.dataset.fs)); });
    panel.querySelectorAll('[data-flag]').forEach(function(b){ var on = !!s[b.dataset.flag]; b.setAttribute('aria-pressed', String(on)); b.textContent = on ? 'פעיל' : 'כבוי'; });
    panel.querySelectorAll('[data-rate]').forEach(function(b){ b.setAttribute('aria-pressed', String((s.rate || 1) == b.dataset.rate)); });
  }
  function toggle(open){
    var on = open === undefined ? !panel.classList.contains('on') : open;
    panel.classList.toggle('on', on); btn.setAttribute('aria-expanded', String(on));
    if (on) { var first = panel.querySelector('[data-fs="1"]'); if (first) first.focus(); } else btn.focus();
  }
  btn.onclick = function(){ toggle(); };
  panel.querySelector('[data-close]').onclick = function(){ toggle(false); };
  panel.querySelectorAll('[data-fs]').forEach(function(b){ b.onclick = function(){ var s = get(); s.fs = +b.dataset.fs; put(s); apply(); }; });
  panel.querySelectorAll('[data-flag]').forEach(function(b){ b.onclick = function(){ var s = get(); s[b.dataset.flag] = !s[b.dataset.flag]; put(s); apply(); }; });
  panel.querySelectorAll('[data-rate]').forEach(function(b){ b.onclick = function(){ var s = get(); s.rate = +b.dataset.rate; put(s); apply(); }; });
  document.getElementById('mb-a11y-reset').onclick = function(){ put({}); apply(); stop(); };

  // read aloud with the voices Windows has (Hebrew when installed)
  var synth = window.speechSynthesis, marked = [];
  function voice(){
    var list = synth ? synth.getVoices() : [];
    return list.filter(function(v){ return /^he|^iw/i.test(v.lang); })[0] || null;
  }
  function stop(){ if (synth) synth.cancel(); marked.forEach(function(el){ el.classList.remove('mb-reading'); }); marked = []; }
  function blocks(){
    var main = document.querySelector('main'); if (!main) return [];
    return Array.prototype.filter.call(main.querySelectorAll('h1,h2,h3,p,li,.item,td,label,summary'), function(el){
      return el.offsetParent !== null && el.innerText.trim() && !el.querySelector('h1,h2,h3,p,li,.item,td');
    });
  }
  function read(){
    stop();
    if (!synth) { note('הדפדפן הזה לא תומך בהקראה'); return; }
    var sel = String(window.getSelection() || '').trim(), parts = sel ? [{text: sel}] : blocks().map(function(el){ return {el: el, text: el.innerText.trim()}; });
    var v = voice(), rate = get().rate || 1;
    if (!v) note('לא נמצא קול עברי ב-Windows. להוספה: הגדרות ← זמן ושפה ← דיבור ← הוספת קולות ← עברית');
    parts.slice(0, 400).forEach(function(p){
      var u = new SpeechSynthesisUtterance(p.text.slice(0, 1200)); u.lang = 'he-IL'; u.rate = rate; if (v) u.voice = v;
      if (p.el) { u.onstart = function(){ marked.forEach(function(x){ x.classList.remove('mb-reading'); }); p.el.classList.add('mb-reading'); marked.push(p.el);
        p.el.scrollIntoView({block: 'center', behavior: 'smooth'}); }; }
      synth.speak(u);
    });
    var last = parts.length; if (!last) note('אין מה להקריא בדף הזה');
  }
  function note(text){ var n = document.getElementById('mb-voice-note'); if (n) n.textContent = text; }
  document.getElementById('mb-read').onclick = read;
  document.getElementById('mb-stop').onclick = stop;
  if (synth) synth.onvoiceschanged = function(){};

  // keyboard shortcuts: G then a letter jumps to a page, ? shows them, Alt+A opens accessibility
  var keys = document.getElementById('mb-keys'), pending = 0;
  var GO = {t: '/today', q: '/triage', m: '/compose', s: '/?s=boxes', d: '/dashboard', n: '/stats', c: '/clients', r: '/reading', a: '/automations', h: '/help'};
  var HE = {'א': 't', 'ק': 'r', 'ר': 'r', 'ם': 'o', 'פ': 'p', 'ש': 'a', 'ד': 's', 'ג': 'd', 'כ': 'f', 'ע': 'g', 'י': 'h', 'ח': 'j', 'ל': 'k', 'ך': 'l',
            'ז': 'z', 'ס': 'x', 'ב': 'c', 'ה': 'v', 'נ': 'b', 'מ': 'n', 'צ': 'm', '/': 'q', 'ט': 'y', 'ו': 'u', 'ן': 'i', 'ת': ','};
  document.getElementById('mb-keys-open').onclick = function(){ toggle(false); keys.classList.add('on'); };
  keys.onclick = function(ev){ if (ev.target === keys) keys.classList.remove('on'); };
  window.addEventListener('keydown', function(ev){
    var typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    var k = (ev.code && ev.code.indexOf('Key') === 0) ? ev.code.slice(3).toLowerCase() : (HE[ev.key] || ev.key.toLowerCase());
    if (ev.altKey && k === 'a') { ev.preventDefault(); toggle(); return; }
    if (ev.key === 'Escape') { keys.classList.remove('on'); if (panel.classList.contains('on')) toggle(false); stop(); return; }
    if (typing || ev.ctrlKey || ev.metaKey || ev.altKey || document.getElementById('tri-acts')) return;   // quick sort has its own keys
    if (ev.key === '?') { keys.classList.toggle('on'); return; }
    if (k === 'g') { pending = Date.now(); return; }
    if (pending && Date.now() - pending < 1500 && GO[k]) {
      pending = 0; ev.preventDefault();
      var a = document.createElement('a'); a.href = GO[k]; document.body.appendChild(a); a.click(); a.remove();   // the page-swap navigation
    }
  });

  // text shortcuts: ";thanks" + space in any text box becomes the full paragraph (Settings -> rules and templates)
  var SNIPS = null;
  function snips(){ if (SNIPS) return Promise.resolve(SNIPS);
    return fetch('/snippets.json').then(function(r){ return r.json(); }).then(function(s){ SNIPS = s; return s; }).catch(function(){ return []; }); }
  document.addEventListener('input', function(ev){
    var el = ev.target;
    if (!el || !(el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && el.type === 'text'))) return;
    var pos = el.selectionStart, before = el.value.slice(0, pos), hit = before.match(/(^|\\s);([^\\s;]{1,20})([ \\n])$/);
    if (!hit) return;
    snips().then(function(list){
      var s = list.filter(function(x){ return x.key === hit[2]; })[0]; if (!s) return;
      var start = pos - hit[2].length - 2;
      el.value = el.value.slice(0, start) + s.text + hit[3] + el.value.slice(pos);
      el.selectionStart = el.selectionEnd = start + s.text.length + 1;
      el.dispatchEvent(new Event('change'));
    });
  });
  window.MB = window.MB || {};
  window.MB.a11y = function(){ toggle(true); };
  window.MB.keys = function(){ keys.classList.add('on'); };
  apply();
})();
</script>"""


# ---- the first-run tour: five bubbles that point at what matters most ------------------------------------------------
STYLE += """
#mb-tour-dim{position:fixed;inset:0;z-index:84;background:rgba(20,12,40,.35);display:none}
#mb-tour-dim.on{display:block;animation:mbfade .25s ease}
.mb-tour-spot{position:relative;z-index:85!important;box-shadow:0 0 0 4px var(--accent-2),0 0 0 9999px rgba(20,12,40,.0)!important;border-radius:14px}
#mb-tour{position:fixed;z-index:86;width:min(330px,calc(100vw - 24px));background:var(--surface);color:var(--ink);border:1px solid var(--line);
border-radius:18px;padding:16px 18px;box-shadow:0 20px 60px rgba(0,0,0,.3);display:none;animation:mbpop .3s ease}
#mb-tour.on{display:block}
#mb-tour h4{margin:0 0 6px;font-size:17px}#mb-tour p{margin:0 0 12px;color:var(--muted);font-size:14.5px;line-height:1.55}
#mb-tour .row{display:flex;justify-content:space-between;align-items:center;gap:8px}
#mb-tour .dots{display:flex;gap:5px}#mb-tour .dots i{width:7px;height:7px;border-radius:50%;background:var(--line)}#mb-tour .dots i.on{background:var(--accent)}
#mb-tour button{font:inherit;font-size:14px;border-radius:10px;padding:7px 14px;cursor:pointer;border:1px solid var(--line);background:transparent;color:var(--ink)}
#mb-tour button.next{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
"""

HTML += """
<div id="mb-tour-dim"></div>
<div id="mb-tour" role="dialog" aria-live="polite" aria-label="סיור קצר"><h4 id="mb-tour-t"></h4><p id="mb-tour-p"></p>
<div class="row"><div class="dots" id="mb-tour-dots"></div><div><button type="button" id="mb-tour-skip">דילוג</button>
<button type="button" class="next" id="mb-tour-next">הבא ←</button></div></div></div>
<script>
(function(){
  if (window.__mbTour) return; window.__mbTour = true;
  var STEPS = [
    ['#mb-tabs a[href="/"]', '📬 מתחילים כאן', 'בהגדרות מחברים את תיבת המייל — כפתור „חיבור עם Google” ואישור. בלי סיסמאות, והמייל נשאר רק במחשב שלך.'],
    ['#mb-tabs a[href="/today"]', '☀️ היום שלי', 'מה דחוף, מי מחכה לתשובה, מה לתשלום ומה ביומן — בדף אחד. נפתח לבד כשנכנסים למחשב.'],
    ['#mb-tabs a[href="/today"]', '⚡ מיון מהיר', 'ב„היום שלי” יש כפתור „מיון מהיר”: מייל אחרי מייל — בוצע, תזכורת, תשובה או נודניק — במקש אחד. כמה דקות ביום, ותיבה מסודרת.'],
    ['.kbtn', '⌨️ מוצאים הכול', 'Ctrl+K (או /) פותח חיפוש מהיר של כל דף ופעולה. ? מציג את כל קיצורי המקלדת.'],
    ['#mb-a11y-btn', '♿ נגישות', 'טקסט גדול, ניגודיות, הקראה בקול ועוד — מהכפתור בצד המסך, בכל דף. זהו, אפשר להתחיל! 🎉']
  ];
  var box = document.getElementById('mb-tour'), dim = document.getElementById('mb-tour-dim'), n = 0, spot = null;
  function done(){ try { localStorage.setItem('mb-tour', 'done'); } catch(e){} }
  function clear(){ if (spot) spot.classList.remove('mb-tour-spot'); spot = null; }
  function close(){ clear(); box.classList.remove('on'); dim.classList.remove('on'); done(); }
  function place(){
    var s = STEPS[n], el = document.querySelector(s[0]);
    clear();
    document.getElementById('mb-tour-t').textContent = s[1];
    document.getElementById('mb-tour-p').textContent = s[2];
    document.getElementById('mb-tour-next').textContent = n === STEPS.length - 1 ? 'יאללה! ✓' : 'הבא ←';
    document.getElementById('mb-tour-dots').innerHTML = STEPS.map(function(_, i){ return '<i' + (i === n ? ' class="on"' : '') + '></i>'; }).join('');
    box.classList.add('on'); dim.classList.add('on');
    if (!el) { box.style.top = '30%'; box.style.left = '50%'; box.style.transform = 'translateX(-50%)'; return; }
    spot = el; el.classList.add('mb-tour-spot'); el.scrollIntoView({block: 'nearest'});
    var r = el.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight;
    var top = r.bottom + 12 + h < innerHeight ? r.bottom + 12 : Math.max(12, r.top - h - 12);
    var left = Math.min(Math.max(12, r.left + r.width / 2 - w / 2), innerWidth - w - 12);
    box.style.transform = ''; box.style.top = top + 'px'; box.style.left = left + 'px';
  }
  function start(){ n = 0; place(); document.getElementById('mb-tour-next').focus(); }
  document.getElementById('mb-tour-next').onclick = function(){ if (n < STEPS.length - 1) { n++; place(); } else close(); };
  document.getElementById('mb-tour-skip').onclick = close;
  dim.onclick = close;
  window.addEventListener('keydown', function(ev){ if (ev.key === 'Escape' && box.classList.contains('on')) close(); });
  window.addEventListener('resize', function(){ if (box.classList.contains('on')) place(); });
  window.MB = window.MB || {}; window.MB.tour = start;
  var seen = true; try { seen = localStorage.getItem('mb-tour') === 'done'; } catch(e){}
  if (!seen && document.getElementById('mb-tabs') && !/^[/](welcome|oauth)/.test(location.pathname)) setTimeout(start, 900);
})();
</script>"""


BOOT = ("<script>try{var d=document.documentElement,t=localStorage.getItem('mb-theme');if(t==='light'||t==='dark')"
        "d.setAttribute('data-theme',t);var a=JSON.parse(localStorage.getItem('mb-a11y')||'{}');if(a.fs)d.setAttribute('data-fs',a.fs);"
        "['contrast','still','spacing','links','cursor','focus'].forEach(function(f){if(a[f])d.setAttribute('data-'+f,'')})}catch(e){}</script>")
