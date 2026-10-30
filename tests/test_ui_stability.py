"""Run the production UI functions in Node with controlled responses and scroll geometry."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mailbrief.web import extras, inbox


@unittest.skipUnless(shutil.which('node'), 'Node is needed for UI regression scenarios')
class StableUI(unittest.TestCase):
    def run_js(self, script):
        # Run a CommonJS file explicitly: do not depend on Node's stdin/REPL
        # detection on Windows. Allow for cold-start scanning on hosted runners.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scenario.cjs'
            path.write_text(script, encoding='utf-8')
            result = subprocess.run([shutil.which('node'), str(path)], capture_output=True, text=True, timeout=90, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_profile_ignores_old_responses_and_closed_dialog(self):
        fn = inbox.JS.split('var profileSeq = 0;', 1)[1].split('function outside(', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var profileSeq=0,pending=[];
var button={focus(){}},dialog={open:false,innerHTML:'',showModal(){this.open=true;},close(){this.open=false;},querySelector(){return button;}};
function $(id){return id==='ib-profile'?dialog:button;}function api(){return new Promise(resolve=>pending.push(resolve));}function esc(s){return String(s||'');}function avatar(){return '';}
''' + fn + '''
(async()=>{showSenderProfile('one@example.com',{email:'old@example.com'});showSenderProfile('two@example.com',{email:'new@example.com'});
var row={account:'two@example.com',email:'new@example.com',name:'New sender',recent:[],count:0,waiting:0};
pending[1](row);await new Promise(setImmediate);var current=dialog.innerHTML;assert.ok(current.includes('New sender'));
pending[0]({...row,name:'Old sender'});await new Promise(setImmediate);assert.equal(dialog.innerHTML,current);
showSenderProfile('one@example.com',{email:'late@example.com'});closeSenderProfile();var closed=dialog.innerHTML;
pending[2]({...row,name:'Late sender'});await new Promise(setImmediate);assert.equal(dialog.innerHTML,closed);assert.equal(dialog.open,false);})();
''')

    def test_date_sections_and_quick_read_keep_account_scope(self):
        functions = inbox.JS.split('function dateSection(value, now){', 1)[1].split('function drawBulk(){', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var S={folder:'INBOX',groups:[{account:'work@example.com',unread:true,rows:[{uid:7,folder:'Archive'},{uid:8}]}]},actions=[];
function act(a,r){actions.push([a,r]);}
''' + 'function dateSection(value, now){' + functions + '''
var now=new Date(2026,0,1,12);assert.equal(dateSection(new Date(2026,0,1,8),now),'היום');assert.equal(dateSection(new Date(2025,11,31,23),now),'אתמול');assert.equal(dateSection('invalid',now),'ללא תאריך');
quickRead(0);assert.deepEqual(actions,[['read',[{a:'work@example.com',f:'Archive',u:7},{a:'work@example.com',f:'INBOX',u:8}]]]);
S.groups[0].unread=false;quickRead(0);assert.equal(actions[1][0],'unread');quickRead(99);assert.equal(actions.length,2);
''')

    def test_sender_search_uses_message_account_and_folder(self):
        fn = inbox.JS.split('function findSender(){', 1)[1].split('function copySender(){', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var input={},picked=[];
var S={acc:'*',unread:true,open:{account:'work@example.com',folder:'Archive',from:{email:'sender@example.com'}}};
function $(){return input;}function choose(a,f){picked.push([a,f]);S.open=null;}function toast(){}
''' + 'function findSender(){' + fn + '''
findSender();assert.deepEqual(picked,[['work@example.com','Archive']]);assert.equal(S.unread,false);assert.equal(S.q,'from:"sender@example.com"');assert.equal(input.value,S.q);
findSender();assert.equal(picked.length,1);
''')

    def test_copy_sender_handles_clipboard_success_and_rejection(self):
        fn = inbox.JS.split('function copySender(){', 1)[1].split('function outside(', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var S={open:{from:{email:'sender@example.com'}}},copied=[],notices=[];
var navigator={clipboard:{writeText(s){copied.push(s);return Promise.resolve();}}};function toast(t){notices.push(t);}
''' + 'function copySender(){' + fn + '''
(async()=>{copySender();await new Promise(setImmediate);assert.deepEqual(copied,['sender@example.com']);assert.match(notices[0],/הועתקה/);
navigator.clipboard.writeText=()=>Promise.reject(Error('blocked'));copySender();await new Promise(setImmediate);assert.match(notices[1],/נחסמה/);
navigator.clipboard=null;copySender();assert.match(notices[2],/לסמן/);})();
''')

    def test_page_navigation_collapses_header_and_restores_focus(self):
        fn = extras.HTML.split('  function setActive(path){', 1)[1].split('  function runScripts(', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var focused=false,menu={open:true},shell={open:true,contains(){return true;},querySelector(){return {focus(){focused=true;}};}};
var document={activeElement:{},querySelectorAll(){return [];},querySelector(){return menu;},getElementById(){return shell;}};
''' + 'function setActive(path){' + fn + '''
setActive('/inbox');assert.equal(shell.open,false);assert.equal(menu.open,false);assert.equal(focused,true);
''')

    def test_enter_searches_immediately_and_escape_clears(self):
        functions = inbox.JS.split('function runSearch(){', 1)[1].split("$('ib-q').value = S.q;", 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var S={q:'old',checked:{x:1},items:[1],groups:[1]},qTimer=1,input={value:'new'},queries=[];
function $(){return input;}function drawQuickFilters(){}function listContext(){}function syncUrl(){}function loadList(){queries.push(S.q);}
''' + 'function runSearch(){' + functions + '''
function event(key,composing){return {key,isComposing:composing,preventDefault(){},stopPropagation(){}};}
searchKey(event('Enter',true));assert.equal(queries.length,0);searchKey(event('Enter',false));assert.deepEqual(queries,['new']);assert.deepEqual(S.checked,{});
searchKey(event('Escape',false));assert.deepEqual(queries,['new','']);assert.equal(input.value,'');
''')

    def test_display_presets_preserve_palette_and_reset_every_setting(self):
        functions = inbox.JS.split('var LOOK = ', 1)[1].split('function lookMenu(btn){', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var saved=JSON.stringify({palette:'forest',font:'',rows:'cards'}),notices=[];
var localStorage={getItem(){return saved;},setItem(k,v){saved=v;}},classes={};
var box={dataset:{},style:{},classList:{toggle(k,v){classes[k]=v;}}},workspace={dataset:{},setAttribute(){}};var S={};
function $(id){return id==='ibx'?box:workspace;}function fitBox(){}function toast(t){notices.push(t);}
''' + 'var LOOK = ' + functions + '''
lookPreset('reading');assert.equal(workspace.dataset.palette,'forest');assert.equal(classes.bottom,true);assert.equal(classes.cards,false);
assert.equal(box.dataset.textSize,'large');assert.equal(JSON.parse(saved).palette,'forest');
lookPreset('compact');assert.equal(classes.dense,true);assert.equal(classes.comfortable,false);assert.equal(classes['no-snippet'],true);
lookPreset('cards');assert.equal(classes.cards,true);assert.equal(classes.nopane,true);assert.equal(classes.dense,false);
lookPreset('reset');assert.deepEqual(JSON.parse(saved),{});assert.equal(workspace.dataset.palette,'purple');assert.equal(classes.cards,false);
LOOK={palette:'__proto__',font:'__proto__'};applyLook();assert.equal(workspace.dataset.palette,'purple');assert.equal(box.style.fontFamily,'');
localStorage.setItem=()=>{throw Error('blocked');};lookPreset('reading');assert.equal(classes.bottom,true);assert.equal(notices.length,1);
''')

    def test_invalid_stored_display_preferences_use_defaults(self):
        expression = inbox.JS.split('var LOOK = ', 1)[1].split('var PALETTES', 1)[0]
        for stored in ['null', '[]', '"invalid"', '{bad']:
            self.run_js('const assert=require("node:assert/strict");var localStorage={getItem(){return ' + json.dumps(stored) + ';}};var LOOK = ' + expression + ';assert.deepEqual(LOOK,{});')

    def test_csv_exports_only_selection_and_escapes_formulas_and_quotes(self):
        functions = inbox.JS.split('function csvCell(value){', 1)[1].split('function exportMessages(', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var S={folder:'INBOX',checked:{one:1},groups:[
{key:'one',account:'a@example.com',rows:[{uid:1,from:{name:'=SUM(A1)',email:'sender@example.com'},subject:'a,"b"',at:'2026-10-30',flags:[],attach:true}]},
{key:'two',account:'b@example.com',rows:[{uid:1,from:{name:'Other',email:'other@example.com'},subject:'private',at:'2026-10-30',flags:['\\\\Seen'],attach:false}]}]};
''' + 'function csvCell(value){' + functions + '''
var csv=messageCSV(true);assert.equal(csv.charCodeAt(0),0xFEFF);assert.match(csv,/'=SUM/);assert.match(csv, /"a,""b"""/);
assert.ok(!csv.includes('private'));assert.ok(messageCSV(false).includes('private'));
S.checked={};assert.equal(messageCSV(true),'');assert.equal(csvCell('  +1').charCodeAt(1), 39);
''')

    def test_message_navigation_distinguishes_account_and_folder(self):
        functions = inbox.JS.split('function neighborIndex(delta){', 1)[1].split("var CAT =", 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var S={folder:'INBOX',open:{account:'b@example.com',folder:'INBOX',uid:1},groups:[
{account:'a@example.com',rows:[{uid:1}]},{account:'b@example.com',rows:[{uid:1,folder:'Sent'}]},
{account:'b@example.com',rows:[{uid:1}]},{account:'b@example.com',rows:[{uid:2}]}]};
var opened=[];function openGroup(i){opened.push(i);}function drawList(){}
''' + 'function neighborIndex(delta){' + functions + '''
assert.equal(neighborIndex(-1),1);assert.equal(neighborIndex(1),3);moveMessage(1);assert.deepEqual(opened,[3]);
S.open.uid=2;assert.equal(neighborIndex(1),-1);moveMessage(1);assert.deepEqual(opened,[3]);
S.open.uid=99;assert.equal(neighborIndex(-1),-1);
''')

    def test_quick_selection_only_changes_loaded_rows(self):
        fn = inbox.JS.split('function selectMessages(mode){', 1)[1].split('function csvCell(', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var S={checked:{a:1},groups:[{key:'a',unread:false},{key:'b',unread:true},{key:'c',unread:true}]};function drawList(){}
''' + 'function selectMessages(mode){' + fn + '''
selectMessages('unread');assert.deepEqual(S.checked,{b:1,c:1});selectMessages('invert');assert.deepEqual(S.checked,{a:1});
selectMessages('clear');assert.deepEqual(S.checked,{});assert.equal(S.lastCk,null);
''')

    def test_switching_mailboxes_restores_own_filters_and_clears_reader(self):
        switch = inbox.JS.split('function switchMailbox(acc){', 1)[1].split('function drawQuickFilters(){', 1)[0]
        choose = inbox.JS.split('function choose(acc, folder){', 1)[1].split('function selectedRefs(){', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var B={accounts:[{email:'a@example.com'},{email:'b@example.com'}]};
var S={acc:'a@example.com',folder:'Sent',q:'invoice',unread:true,open:{uid:7},checked:{old:1},items:[1],groups:[1],folders:{}};
var MAILBOX_STATE=Object.create(null),qTimer=1,input={},box={classList:{remove(){}}},requests=[];
function $(id){return id==='ib-q'?input:box;}var localStorage={setItem(){}};
function closeMenu(){}function closeSenderProfile(){}function drawFolders(){}function drawQuickFilters(){}function drawSavedSearches(){}function syncUrl(){}
function loadList(){requests.push([S.acc,S.folder,S.q,S.unread]);}function drawHome(){}function loadFolders(){}
''' + 'function choose(acc, folder){' + choose + 'function switchMailbox(acc){' + switch + '''
switchMailbox('b@example.com');assert.deepEqual(requests[0],['b@example.com','INBOX','',false]);assert.equal(S.open,null);assert.deepEqual(S.checked,{});
S.folder='Drafts';S.q='subject:work';switchMailbox('a@example.com');assert.deepEqual(requests[1],['a@example.com','Sent','invoice',true]);
switchMailbox('b@example.com');assert.deepEqual(requests[2],['b@example.com','Drafts','subject:work',false]);
switchMailbox('unknown@example.com');assert.equal(requests.length,3);
''')

    def test_saved_searches_are_separate_for_each_mailbox(self):
        functions = inbox.JS.split('function savedSearches(){', 1)[1].split('function drawMailboxes(){', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var data={},S={acc:'a@example.com',folder:'INBOX',unread:false},input={value:'from:client'};
var localStorage={getItem(k){return data[k]||null;},setItem(k,v){data[k]=v;}};
var saved={innerHTML:''};function $(id){return id==='ib-q'?input:saved;}function toast(){}function esc(t){return t;}function choose(a,f){S.acc=a;S.folder=f;}
''' + 'function savedSearches(){' + functions + '''
saveSearch();saveSearch();assert.equal(savedSearches().length,1);
S.acc='b@example.com';assert.deepEqual(savedSearches(),[]);input.value='has:attachment';saveSearch();
S.acc='a@example.com';assert.equal(savedSearches()[0].q,'from:client');openSavedSearch(0);assert.equal(S.q,'from:client');
data['ib-searches:a@example.com']='broken';assert.deepEqual(savedSearches(),[]);
''')

    def test_quick_filters_toggle_without_losing_search_words(self):
        fn = inbox.JS.split('function quickFilter(token){', 1)[1].split('function api(', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var qTimer=1,S={q:'from:client',unread:false},input={value:'from:client'};
function $(){return input;}function drawQuickFilters(){}function syncUrl(){}function loadList(){}
''' + 'function quickFilter(token){' + fn + '''
quickFilter('has:attachment');assert.equal(S.q,'from:client has:attachment');quickFilter('has:attachment');assert.equal(S.q,'from:client');
quickFilter('unread');assert.equal(S.unread,true);assert.equal(S.q,'from:client');quickFilter('all');assert.equal(S.q,'');assert.equal(S.unread,false);
''')

    def test_first_page_server_error_can_be_retried(self):
        fn = inbox.JS.split('function loadList(opts){', 1)[1].split("$('ib-cats').addEventListener", 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var listSeq=0,morePending=0,pending=[],rows={innerHTML:'',scrollTop:0},retry={};
var S={acc:'a',folder:'INBOX',page:0,q:'query',unread:false,items:[],checked:{}};
function $(id){return id==='ib-retry'?retry:id==='ib-more'?null:rows;}
function api(){return new Promise(resolve=>pending.push(resolve));}function group(items){return items;}
function drawList(){rows.innerHTML='loaded';}function toast(){}function esc(s){return s.replace(/</g,'&lt;');}
''' + 'function loadList(opts){' + fn + '''
(async()=>{var request=loadList();pending.shift()({items:[],errors:['<offline>'],total:0});await request;
assert.match(rows.innerHTML,/role="alert"/);assert.match(rows.innerHTML,/&lt;offline>/);assert.equal(typeof retry.onclick,'function');
retry.onclick();pending.shift()({items:[{key:'one'}],total:1});await new Promise(setImmediate);
assert.equal(rows.innerHTML,'loaded');assert.equal(S.items.length,1);})();
''')

    def test_older_navigation_response_cannot_replace_latest_page(self):
        fn = extras.HTML.split('  function navigate(', 1)[1].split("  document.addEventListener('click'", 1)[0]
        self.run_js('''
const assert=require('node:assert/strict'); var navigation=0, pending={}, paths=[];
var main={classList:{add(){},remove(){}},innerHTML:'original'}, location={href:'http://mailbrief.localhost/today'};
var document={querySelector(){return main;},getElementById(){return null;}};
var history={pushState(s,t,p){paths.push(p);}},window={MB:{},__ibx:null};
function DOMParser(){} DOMParser.prototype.parseFromString=function(html){return {title:html,querySelector(){return {innerHTML:html};}}};
function load(path){return new Promise(resolve=>pending[path]=resolve);} function busy(){} function progress(){}function hide(){}function show(){}function runScripts(){}function setActive(){}
function setTimeout(){return 1;}function clearTimeout(){}
''' + 'function navigate(' + fn + '''
(async()=>{navigate('/first',true);navigate('/second',true);await Promise.resolve();
pending['/second']({html:'second',url:'http://mailbrief.localhost/second'});await new Promise(setImmediate);
pending['/first']({html:'first',url:'http://mailbrief.localhost/first'});await new Promise(setImmediate);
assert.equal(main.innerHTML,'second');assert.deepEqual(paths,['/second']);})();
''')

    def test_mail_refresh_preserves_anchor_and_keyboard_focus(self):
        fn = inbox.JS.split('function drawList(){', 1)[1].split('function renderList(){', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var focused=false;
var old={dataset:{key:'selected'},getBoundingClientRect(){return {top:10,bottom:60};}};
var active={matches(){return true;},closest(){return old;}};
var rows={scrollTop:100,getBoundingClientRect(){return {top:0};},querySelectorAll(){return [old];},contains(){return true;}};
var document={activeElement:active};function $(id){return rows;}
function renderList(){rows.querySelectorAll=()=>[{dataset:{key:'selected'},getBoundingClientRect(){return {top:50,bottom:100};},querySelector(){return {focus(options){assert.equal(options.preventScroll,true);focused=true;}};}}];}
''' + 'function drawList(){' + fn + '''
drawList();assert.equal(rows.scrollTop,140);assert.equal(focused,true);
''')

    def test_fresh_response_after_cached_list_keeps_user_scroll(self):
        fn = inbox.JS.split('function loadList(opts){', 1)[1].split("$('ib-cats').addEventListener", 1)[0]
        self.run_js('''const assert=require('node:assert/strict');var listSeq=0,morePending=0,pending=[],rows={scrollTop:0},S={acc:'a',folder:'INBOX',page:0,q:'',unread:false,items:[],checked:{}};
function $(){return rows;}function api(){return new Promise(resolve=>pending.push(resolve));}function group(items){return items;}function drawList(){}function toast(){}function esc(s){return s;}
''' + 'function loadList(opts){' + fn + '''
(async()=>{loadList();pending[0]({items:[{key:'one'}],total:1});await new Promise(setImmediate);rows.scrollTop=320;
pending[1]({items:[{key:'two'},{key:'one'}],total:2});await new Promise(setImmediate);assert.equal(rows.scrollTop,320);})();
''')

    def test_load_more_retries_failed_page_and_ignores_double_click(self):
        fn = inbox.JS.split('function loadList(opts){', 1)[1].split("$('ib-cats').addEventListener", 1)[0]
        self.run_js('''const assert=require('node:assert/strict');var listSeq=0,morePending=0,pending=[],requests=[],notices=[];
var button={disabled:false,textContent:''},rows={scrollTop:280},S={acc:'a',folder:'INBOX',page:0,q:'',unread:false,items:[{key:'first'}],checked:{}};
function $(id){return id==='ib-more'?button:rows;}function api(path,params){requests.push(params.p);return new Promise((resolve,reject)=>pending.push({resolve,reject}));}
function group(items){return items;}function drawList(){}function toast(s){notices.push(s);}function esc(s){return s;}
''' + 'function loadList(opts){' + fn + '''
(async()=>{var first=loadList({more:1});loadList({more:1});assert.deepEqual(requests,[1]);assert.equal(button.disabled,true);
pending[0].reject(new Error('offline'));await first;assert.equal(S.page,0);assert.equal(button.disabled,false);assert.equal(notices.length,1);
var retry=loadList({more:1});assert.deepEqual(requests,[1,1]);pending[1].resolve({items:[{key:'second'}],total:150});await retry;
assert.equal(S.page,1);assert.equal(S.items.length,2);assert.equal(rows.scrollTop,280);
var next=loadList({more:1});assert.deepEqual(requests,[1,1,2]);pending[2].resolve({items:[{key:'third'}],total:150});await next;assert.equal(S.page,2);})();
''')

    def test_message_from_another_account_with_same_uid_cannot_overwrite_reader(self):
        fn = inbox.JS.split('function openMessage(', 1)[1].split('function moveOptions(', 1)[0]
        self.run_js('''
const assert=require('node:assert/strict');var pending=[],drawn=[],S={},WIDE=false;
var element={classList:{add(){},toggle(){}},innerHTML:''};function $(){return element;}
function api(){return new Promise(resolve=>pending.push(resolve));}function syncUrl(){}function drawMessage(){drawn.push(S.open.account);}function loadAllFolders(){}function esc(x){return x;}
function setTimeout(){return 1;}
''' + 'function openMessage(' + fn + '''
(async()=>{openMessage('first@example.com','INBOX',7);openMessage('second@example.com','INBOX',7);
pending[0]({account:'first@example.com',folder:'INBOX',uid:7});await new Promise(setImmediate);
assert.deepEqual(drawn,[]);assert.equal(S.open.account,'second@example.com');
pending[1]({account:'second@example.com',folder:'INBOX',uid:7});await new Promise(setImmediate);
assert.deepEqual(drawn,['second@example.com']);})();
''')

    def test_motion_enabled_by_default_and_user_can_disable(self):
        script = re.search(r'<script>(.*?)</script>', extras.BOOT, re.S)[1]
        self.run_js('const assert=require("node:assert/strict");var attrs={};var document={documentElement:{setAttribute(k,v){attrs[k]=v;}}};var localStorage={getItem(){return null;}};' + script + ';assert.equal(attrs["data-still"],undefined);')

    def test_scripts_remain_valid_javascript(self):
        scripts = [inbox.JS] + re.findall(r'<script>(.*?)</script>', extras.HTML + extras.BOOT, re.S)
        for script in scripts:
            result = subprocess.run(['node', '--check'], input=script, capture_output=True, text=True, timeout=45, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr + json.dumps(script[:50]))
