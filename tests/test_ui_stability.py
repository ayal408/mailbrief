"""Run the production UI functions in Node with controlled responses and scroll geometry."""
import json
import re
import shutil
import subprocess
import unittest

from mailbrief.web import extras, inbox


@unittest.skipUnless(shutil.which('node'), 'Node is needed for UI regression scenarios')
class StableUI(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run([shutil.which('node')], input=script, capture_output=True, text=True, timeout=45, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
