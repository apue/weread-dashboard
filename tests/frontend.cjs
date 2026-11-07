// Offline rendering-contract checks; no browser or third-party dependencies.
const {readFileSync} = require('node:fs');
const {execFileSync} = require('node:child_process');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const data = JSON.parse(execFileSync('python3', ['-c', 'import json; from dashboard import demo_snapshot; print(json.dumps(demo_snapshot()))'], {encoding:'utf8'}));
class Element {
  constructor(id='') { this.id=id;this.value=id==='range'?'3':'';this.style={};this.events={};this.clientWidth=1000;this.classList={remove(){},add(){}}; }
  set innerHTML(html) { this.html=html;if(this.id==='month')this.value=html.match(/value="([^"]+)"/)?.[1]||''; }
  get innerHTML() { return this.html||''; }
  addEventListener(name, fn) { this.events[name]=fn; }
  querySelectorAll() { return []; }
  querySelector() { return new Element(); }
}
const elements = new Map();
const document = {getElementById(id){if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);}};
const context=vm.createContext({document,console,Date,Math,Map,Number,String,JSON,Error,setTimeout,
  fetch:async()=>({ok:true,json:async()=>data})});
vm.runInContext(readFileSync('web/app.js','utf8'),context);
setImmediate(()=>{
  const get=id=>document.getElementById(id);
  assert.equal(get('content').hidden,false);
  assert.match(get('metrics').innerHTML,/累计阅读/);
  assert.equal((get('calendar').innerHTML.match(/class="calendar-month"/g)||[]).length,3);
  get('range').value='1';get('range').events.change();
  assert.equal((get('calendar').innerHTML.match(/class="calendar-month"/g)||[]).length,1);
  assert.equal(get('month').value,data.months.at(-1).month);
  data.months.at(-1).books[0].title='<img src=x onerror=alert(1)>';
  get('month').events.change();
  assert.ok(!get('books').innerHTML.includes('<img'));
  assert.ok(get('books').innerHTML.includes('&lt;img'));
  data.months.at(-1).dailyComplete=false;
  get('month').events.change();
  assert.match(get('cumulative').innerHTML,/日明细不完整/);
  console.log('Frontend rendering, filter, incomplete-data and escaping checks passed.');
});
