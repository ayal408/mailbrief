"""📝 The price-quote form: client, items (description · quantity · price), VAT, notes — then a PDF to look at, or sent."""
from mailbrief import config
from mailbrief.features.quote_pdf import next_number
from mailbrief.money.books import VAT_RATE
from mailbrief.storage import load_json
from mailbrief.util import e
from mailbrief.web.layout import heading, page
from mailbrief.web.token import TOKEN


FIELD = 'font:inherit;padding:9px 11px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);width:100%'


def quote_page(msg='', to='', name=''):
    accounts = ''.join(f'<option>{e(a["email"])}</option>' for a in load_json(config.ACCOUNTS_FILE, []))
    row = (f'<tr><td><input type="text" name="desc" placeholder="תיאור הפריט / השירות" style="{FIELD}"></td>'
           f'<td style="width:90px"><input type="number" name="qty" value="1" min="0" step="any" style="{FIELD}"></td>'
           f'<td style="width:130px"><input type="number" name="price" min="0" step="any" placeholder="₪" style="{FIELD}"></td>'
           '<td style="width:110px" class="q-sum muted">—</td></tr>')
    note = f'<div class="item urgent">{e(msg)}</div>' if msg else ''
    return page('הצעת מחיר', f'''{heading('📝', 'הצעת מחיר')}{note}
<p class="muted">ממלאים — ומקבלים PDF מסודר עם הלוגו והפרטים שלך (הלוגו מהחתימה של התיבה). ״שליחה״ מצרפת אותו למייל ללקוח
ומוסיפה למעקב הצעות המחיר (תזכורת אחרי שבוע בלי תשובה). זו הצעת מחיר ולא חשבונית מס.</p>
<form method="post" action="/quote_make" style="display:grid;gap:10px"><input type="hidden" name="t" value="{TOKEN}">
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px">
<label style="margin:0">שם הלקוח<input type="text" name="name" value="{e(name)}" required style="{FIELD}"></label>
<label style="margin:0">מייל הלקוח<input type="email" name="email" value="{e(to)}" dir="ltr" style="{FIELD}"></label>
<label style="margin:0">מהתיבה<select name="account" style="{FIELD}">{accounts}</select></label></div>
<div class="scroll"><table id="q-items"><thead><tr><th>תיאור</th><th>כמות</th><th>מחיר ליחידה</th><th>סה״כ</th></tr></thead>
<tbody>{row * 3}</tbody></table></div>
<div><button type="button" class="ghost" id="q-add" style="margin:0;padding:6px 14px">➕ שורה</button></div>
<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center">
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400"><input type="checkbox" name="vat" value="1" checked> כולל מע״מ {VAT_RATE:g}%
<span class="muted" style="font-size:13px">(עוסק פטור — להוריד את הסימון)</span></label>
<label style="margin:0;display:flex;gap:6px;align-items:center;font-weight:400">בתוקף <input type="number" name="valid" value="30" min="1" max="365" style="width:80px;{FIELD}"> ימים</label>
<b id="q-total" style="margin-inline-start:auto;font-size:18px"></b></div>
<label style="margin:0">הערות <span class="muted">(לא חובה — תנאי תשלום, לוחות זמנים…)</span><textarea name="notes" rows="3" style="{FIELD}"></textarea></label>
<div style="display:flex;gap:8px;flex-wrap:wrap"><button name="action" value="preview" class="ghost" style="margin:0">📄 יצירת PDF ופתיחה</button>
<button name="action" value="send" style="margin:0">📨 שליחה ללקוח</button>
<span class="muted" style="font-size:13px;align-self:center">מספר ההצעה הבא: {next_number(peek=True)}</span></div></form>
<script>(function(){{var body=document.querySelector('#q-items tbody'),vat=document.querySelector('[name=vat]'),out=document.getElementById('q-total');
var ROW={row!r};
function sum(){{var net=0;Array.prototype.forEach.call(body.rows,function(r){{var q=parseFloat(r.querySelector('[name=qty]').value)||0,
p=parseFloat(r.querySelector('[name=price]').value)||0,s=q*p;net+=s;r.querySelector('.q-sum').textContent=s?'₪'+s.toLocaleString('he-IL',{{maximumFractionDigits:2}}):'—';}});
var total=vat.checked?net*(1+{VAT_RATE}/100):net;out.textContent=net?'סה״כ: ₪'+total.toLocaleString('he-IL',{{maximumFractionDigits:2}}):'';}}
document.getElementById('q-add').onclick=function(){{body.insertAdjacentHTML('beforeend',ROW);}};
document.addEventListener('input',function(ev){{if(ev.target.closest&&ev.target.closest('#q-items,[name=vat]'))sum();}});vat.onchange=sum;sum();}})();</script>''', '/clients')
