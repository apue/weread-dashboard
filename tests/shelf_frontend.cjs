// Offline interaction contract checks for the bookshelf. No browser or npm packages.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
  constructor(id='') { this.id=id; this.value=id==='shelf-search'?'':id==='shelf-sort'?'recent':'all'; this.hidden=false; this.disabled=false; this.textContent=''; this.innerHTML=''; this.events={}; this.attrs={}; this.dataset={}; this.isConnected=true; this.animations=[]; this.classList={add(){},remove(){}}; }
  addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
  setAttribute(k,v){this.attrs[k]=v;}
  querySelector(sel){ if(sel==='.detail-sheet') return sheet; if(sel==='.detail-frame')return frame; if(sel==='.dialog-backdrop')return backdrop; if(sel==='.cover-art')return new Element(); return new Element(); }
  querySelectorAll(){return [];}
  get options(){return [...this.innerHTML.matchAll(/<option value="([^"]*)"/g)].map(m=>({value:m[1]}));}
  closest(sel){return this.closestTarget?.[sel]||null;}
  showModal(){this.open=true;}
  close(){this.open=false;}
  focus(options){this.focusOptions=options;}
  getBoundingClientRect(){return {left:0,top:0};}
  animate(frames, options={}){const animation={frames,options,cancel(){},finished:Promise.resolve()};this.animations.push(animation);return animation;}
  hasAttribute(){return false;}
  insertAdjacentHTML(_where,html){this.innerHTML+=html;}
}
const sheet=new Element('sheet'),frame=new Element('frame'),backdrop=new Element('backdrop');
const elements=new Map();
const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
const docEvents={};
const document={getElementById:get,body:new Element('body'),activeElement:null,querySelectorAll(){return [];},addEventListener(type,fn){(docEvents[type]??=[]).push(fn);}};
const events=(id,type)=>get(id).events[type]?.[0];
const items=[
  {id:'book:1',kind:'book',title:'Alpha',author:'A',category:'Fiction',readUpdateTime:30,finished:null,progress:null},
  {id:'book:2',kind:'book',title:'Beta',author:'B',category:'History',readUpdateTime:20,finished:null,progress:null},
  {id:'album:3',kind:'album',title:'Gamma',author:'C',category:'未分类',readUpdateTime:10,finished:null,progress:null}
];
const calls=[]; let detailResolvers={};
const shelf={items,syncedAt:null,demo:false,notesSyncedAt:null};
const fetch=async(url,opts={})=>{
  calls.push({url,opts});
  if(url==='/api/shelf')return {ok:true,json:async()=>shelf};
  if(url==='/api/shelf/sync')return {ok:true,json:async()=>({...shelf,syncedAt:'2026-01-01T00:00:00Z'})};
  if(url==='/api/notes/sync')return {ok:true,json:async()=>({syncedAt:'2026-01-01T00:00:00Z',bookCount:1})};
  if(url.startsWith('/api/book/sync?'))return {ok:true,json:async()=>({info:{newRating:765,newRatingCount:7},progress:{recordReadingTime:0,readingTime:8690},notes:null,errors:[]})};
  if(url.startsWith('/api/book?id='))return new Promise(resolve=>{detailResolvers[decodeURIComponent(url.split('id=')[1])]=()=>resolve({ok:true,json:async()=>({id:decodeURIComponent(url.split('id=')[1]),info:{newRating:765,newRatingCount:7},progress:{recordReadingTime:0,readingTime:8690},notes:{noteCount:2,reviewCount:3,bookmarkCount:5,total:10},errors:[]})});});
  throw Error(`Unexpected data request: ${url}`);
};
const storage={getItem(){throw Error('storage unavailable');},setItem(){throw Error('storage unavailable');},removeItem(){throw Error('storage unavailable');}};
const ctx=vm.createContext({document,window:{scrollY:0,scrollTo(){}},fetch,localStorage:storage,CSS:{escape:x=>x},matchMedia:()=>({matches:false}),requestAnimationFrame:fn=>fn(),console,Date,Math,Map,Set,String,Number,JSON,Error,encodeURIComponent,decodeURIComponent});
vm.runInContext(readFileSync('web/shelf.js','utf8'),ctx);
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
  await tick(); await tick();
  assert.equal(calls.filter(x=>x.url==='/api/shelf').length,1,'initial shelf cache is fetched once');
  assert.equal(calls.filter(x=>x.url==='/api/shelf/sync').length,1,'page load triggers one background sync');
  assert.match(get('book-wall').innerHTML,/Alpha/);
  assert.match(get('book-wall').innerHTML,/Beta/);
  assert.match(get('book-wall').innerHTML,/Gamma/);
  assert.match(get('recent-books').innerHTML,/最近读过/,'unknown progress is not rendered as zero');
  const baseline=calls.length;
  get('shelf-search').value='alpha'; events('shelf-search','input')();
  get('shelf-sort').value='title'; events('shelf-sort','change')();
  get('shelf-search').value=''; events('shelf-search','input')();
  const sorted=get('book-wall').innerHTML;
  assert.ok(sorted.indexOf('Alpha')<sorted.indexOf('Beta')&&sorted.indexOf('Beta')<sorted.indexOf('Gamma'),'title sort is applied in memory');
  get('shelf-kind').value='album'; events('shelf-kind','change')();
  assert.equal(calls.length,baseline,'search, sorting and filtering are entirely local');
  assert.match(get('book-wall').innerHTML,/Gamma/);
  assert.doesNotMatch(get('book-wall').innerHTML,/Alpha|Beta/);

  // Open two books before the first cache response returns. The late first response must not replace book 2.
  const card1=new Element('card1');card1.dataset={bookId:'book:1'};card1.closest=sel=>sel==='#book-wall'?get('book-wall'):null;
  const card2=new Element('card2');card2.dataset={bookId:'book:2'};card2.closest=sel=>sel==='#book-wall'?get('book-wall'):null;
  const dispatch=id=>{const card=id==='book:1'?card1:card2;const target={closest:sel=>sel==='[data-book-id]'?card:null};docEvents.click[0]({target});};
  dispatch('book:1'); dispatch('book:2');
  await tick();
  assert.match(get('detail-body').innerHTML,/正在读取简介/,'new details start with an explicit loading placeholder');
  const openingAnimations=frame.animations.length;
  detailResolvers['book:1'](); await tick();
  assert.equal(get('detail-title').textContent,'Beta','opening a second book updates active dialog title');
  detailResolvers['book:2'](); await tick();
  assert.equal(frame.animations.length,openingAnimations,'async detail data updates do not replay the card entrance');
  assert.match(get('detail-body').innerHTML,/想法\/点评 3 · 书签 5 · 划线 2 · 合计 10/,'note fields retain their distinct meanings');
  assert.match(get('detail-body').innerHTML,/微信读书推荐值/);
  assert.match(get('detail-body').innerHTML,/76\.5%/,'upstream recommendation value 765 is displayed as 76.5 percent');
  assert.doesNotMatch(get('detail-body').innerHTML,/\b765\b|765\/10/,'raw recommendation score is never shown directly');
  assert.doesNotMatch(get('detail-body').innerHTML,/累计阅读/,'do not infer cumulative time from raw readingTime when recordReadingTime is zero');
  assert.doesNotMatch(get('detail-body').innerHTML,/已读 0%/,'unknown progress stays unknown');
  assert.equal(calls.filter(x=>x.url.startsWith('/api/book/sync')&&x.url.includes('part=all')).length,1,'missing book details are fetched once after the cached detail');
  const noteButton={};docEvents.click[0]({target:{closest:sel=>sel==='#notes-sync'?noteButton:null}});
  await tick();
  assert.equal(calls.filter(x=>x.url==='/api/notes/sync').length,1,'detail note action requests independent overview sync');
  assert.equal(calls.filter(x=>x.url.startsWith('/api/book?id=')).length,3,'after note sync, active book notes are reloaded');
  detailResolvers['book:2'](); await tick();
  events('detail-close','click')();
  await tick();
  assert.equal(get('book-dialog').open,false,'close button dismisses detail');
  assert.equal(card2.focusOptions?.preventScroll,true,'focus returns to the invoking book card without scrolling');
  dispatch('album:3'); await tick();
  assert.equal(calls.filter(x=>x.url.includes('album%3A3')||x.url.includes('articles')).length,0,'album and article entries never query the electronic book detail API');
  console.log('Bookshelf cache, one-time sync, local filters, storage failure, async detail and unknown-value checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
