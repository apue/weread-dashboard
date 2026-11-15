// Deterministic lifecycle checks for the native detail dialog and WAAPI contract.
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');

class Animation {
  constructor(target,frames,options){this.target=target;this.frames=frames;this.options=options;this.cancelled=false;this.finished=new Promise((resolve,reject)=>{this.resolve=resolve;this.reject=reject;});}
  cancel(){this.cancelled=true;this.reject(new Error('cancelled'));}
  finish(){this.resolve();}
}
class Element {
  constructor(id=''){this.id=id;this.value=id==='shelf-search'?'':id==='shelf-sort'?'recent':'all';this.hidden=false;this.disabled=false;this.textContent='';this.innerHTML='';this.events={};this.dataset={};this.attrs={};this.isConnected=true;this.open=false;this.focusCalls=[];this.classList={add(){},remove(){}};this.animations=[];this.style={};}
  addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
  dispatch(type,event={}){for(const fn of this.events[type]||[])fn({target:this,preventDefault(){},...event});}
  setAttribute(k,v){this.attrs[k]=v;}
  hasAttribute(k){return Object.hasOwn(this.attrs,k);}
  querySelector(sel){if(sel==='.detail-sheet')return sheet;if(sel==='.detail-frame')return frame;if(sel==='.detail-cover')return cover;if(sel==='.dialog-backdrop')return backdrop;return null;}
  querySelectorAll(){return [];}
  showModal(){this.open=true;}
  close(){this.open=false;this.closeCount=(this.closeCount||0)+1;}
  focus(options){this.focusCalls.push(options);document.activeElement=this;}
  getBoundingClientRect(){return {left:10,top:20,width:100,height:120};}
  animate(frames,options){const a=new Animation(this,frames,options);this.animations.push(a);return a;}
  insertAdjacentHTML(_where,html){this.innerHTML+=html;}
  closest(){return null;}
}
const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
const sheet=new Element('sheet'),frame=new Element('frame'),cover=new Element('cover'),backdrop=new Element('backdrop');
const docEvents={};const document={activeElement:null,body:new Element('body'),getElementById:get,querySelectorAll(){return [];},addEventListener(type,fn){(docEvents[type]??=[]).push(fn);}};
let scrollY=87;const scrollCalls=[];const window={get scrollY(){return scrollY;},scrollTo(x){scrollCalls.push(x);scrollY=x.top;}};
let reduce=false;
const originalAnimate=Element.prototype.animate;
const items=['a','b'].map((id,i)=>({id:`book:${id}`,kind:'book',title:`Book ${id}`,author:'Writer',category:'Fiction',readUpdateTime:10-i,progress:null}));
const shelf={items,syncedAt:null,demo:false,notesSyncedAt:null};const pending={};const pendingFresh=[];const resolvedFresh=[];const requests=[];
const fetch=async url=>{requests.push(url);if(url==='/api/shelf')return{ok:true,json:async()=>shelf};if(url==='/api/shelf/sync')return{ok:true,json:async()=>({...shelf,syncedAt:'2026-01-01T00:00:00Z'})};if(url==='/api/notes/sync')return{ok:true,json:async()=>({})};if(url.startsWith('/api/book?id='))return new Promise(resolve=>{const id=decodeURIComponent(url.split('id=')[1]);(pending[id]??=[]).push(()=>resolve({ok:true,json:async()=>({id,info:{intro:'CACHE INTRO',newRating:500,newRatingCount:1},progress:{progress:42},notes:{reviewCount:2,bookmarkCount:3,noteCount:4,total:9},errors:[]})}));});if(url.startsWith('/api/book/sync?')&&url.includes('part=all'))return new Promise(resolve=>pendingFresh.push({url,resolve:data=>resolve({ok:true,json:async()=>data})}));if(url.startsWith('/api/book/sync?'))return{ok:true,json:async()=>({progress:{progress:42}})};throw Error(`Unexpected request ${url}`);};
const ctx=vm.createContext({document,window,fetch,localStorage:{getItem(){return null},setItem(){},removeItem(){}},CSS:{escape:x=>x},matchMedia:q=>({matches:q.includes('prefers-reduced-motion')&&reduce}),requestAnimationFrame:fn=>fn(),console,Date,Math,Map,Set,String,Number,JSON,Error,encodeURIComponent,decodeURIComponent,setTimeout,clearTimeout});
vm.runInContext(readFileSync('web/shelf.js','utf8'),ctx);
const tick=()=>new Promise(r=>setImmediate(r));
const openCard=id=>{const card=new Element(`card-${id}`);card.dataset.bookId=id;card.closest=sel=>sel==='#book-wall'?get('book-wall'):null;for(const fn of docEvents.click||[])fn({target:{closest:sel=>sel==='[data-book-id]'?card:null}});return card;};
const clickSelector=selector=>{for(const fn of docEvents.click||[])fn({target:{closest:sel=>sel===selector?{}:null}});};
const settle=async id=>{await tick();const q=pending[id]||[];q.shift()?.();await tick();};
const settleFresh=async(url,data)=>{await tick();const i=pendingFresh.findIndex(x=>x.url===url);assert.notEqual(i,-1,`expected pending detail sync ${url}`);const [entry]=pendingFresh.splice(i,1);entry.resolve(data);resolvedFresh.push(url);await tick();assert.ok(!pendingFresh.some(x=>x.url===url),`sync ${url} was consumed`);};
const regularSync=id=>`/api/book/sync?id=book%3A${id}&part=all`;
const forcedSync=id=>`${regularSync(id)}&force=1`;
(async()=>{
  for(let i=0;i<10;i++)await tick();
  assert.equal((docEvents.click||[]).length,1,'document click handler is installed');
  assert.match(get('book-wall').innerHTML,/Book a/,`fixture shelf loaded before opening (${get('shelf-status').textContent})`);
  const dialog=get('book-dialog'),close=get('detail-close');
  let first=openCard('book:a');
  assert.equal(dialog.open,true,'native dialog opens synchronously from the selected shelf item');
  assert.match(get('detail-body').innerHTML,/正在读取简介/,'first frame uses a meaningful loading placeholder');
  assert.match(get('detail-body').innerHTML,/正在读取推荐值/,'unknown recommendation is marked loading rather than absent');
  const entrance=frame.animations.at(-1);assert.equal(entrance.options.duration,300,'opening uses the 300ms card animation');
  const backdropEntrance=backdrop.animations.at(-1);
  assert.equal(backdropEntrance.options.duration,220,'opening backdrop uses the synchronized 220ms fade');
  assert.equal(entrance.target,frame,'the inner detail frame animates; its positioning wrapper does not');
  assert.equal(entrance.options.easing,'ease-in-out','entrance uses a gradual easing curve');
  assert.ok(entrance.frames.every(f=>!String(f.transform).includes('translate')),'entrance does not animate position with translate');
  await settle('book:a');
  assert.match(get('detail-body').innerHTML,/CACHE INTRO/,'cached GET content replaces the loading placeholder before fresh sync returns');
  await settleFresh(regularSync('a'),{info:{intro:'FRESH INTRO',newRating:650,newRatingCount:3},progress:{progress:88},notes:{reviewCount:5,bookmarkCount:6,noteCount:7,total:18},errors:[]});
  assert.match(get('detail-body').innerHTML,/FRESH INTRO/,'fresh sync content replaces cached content asynchronously');
  assert.equal(dialog.children?.length||0,0,'opening does not add a ghost node to the dialog');
  close.dispatch('click');close.dispatch('click');
  assert.equal(entrance.cancelled,true,'starting close cancels an unfinished frame entrance');
  assert.equal(backdropEntrance.cancelled,true,'starting close cancels the active backdrop entrance');
  assert.equal(dialog.open,true,'dialog remains open until the exit animation completes');
  const exits=frame.animations.filter(a=>a.options.duration===180);assert.equal(exits.length,1,'repeated close does not queue duplicate exit animations');
  assert.equal(exits[0].options.easing,'ease-in-out','exit uses a gradual easing curve');
  assert.ok(exits[0].frames.every(f=>!String(f.transform).includes('translate')),'exit does not animate position with translate');
  exits[0].finish();await tick();
  assert.equal(dialog.open,false,'dialog closes after the exit animation');
  assert.equal(first.focusCalls.at(-1)?.preventScroll,true,'focus returns to the invoking card without scrolling');
  assert.equal(scrollCalls.at(-1)?.top,87,'the original page scroll position is restored');

  // Reopening while closing invalidates the old completion callback.
  const second=openCard('book:a');
  assert.match(get('detail-body').innerHTML,/FRESH INTRO/,'same-book reopen paints the session cache before its GET resolves');
  await settle('book:a');
  close.dispatch('click');const oldExit=frame.animations.filter(a=>a.options.duration===180).at(-1),oldBackdropExit=backdrop.animations.at(-1);
  const other=openCard('book:b');await settle('book:b');await settleFresh(regularSync('b'),{info:{intro:'B FRESH'},progress:{progress:35},notes:null,errors:[]});
  assert.equal(oldBackdropExit.cancelled,true,'reopening cancels the prior backdrop exit animation');
  const reopenedBackdrop=backdrop.animations.at(-1);oldExit.finish();oldBackdropExit.finish();await tick();
  assert.equal(dialog.open,true,'a stale close completion cannot close the newly opened dialog');
  assert.equal(reopenedBackdrop.target,backdrop,'reopen animates the same backdrop node');
  assert.equal(JSON.stringify(reopenedBackdrop.frames.map(f=>f.opacity)),'[0,1]','reopen restores the backdrop from transparent to visible');
  assert.equal(get('detail-title').textContent,'Book b','the newer selection remains active');
  dialog.dispatch('cancel');await tick();
  assert.equal(dialog.open,true,'cancel/Esc starts the same asynchronous close lifecycle');
  frame.animations.filter(a=>a.options.duration===180).at(-1).finish();await tick();
  assert.equal(dialog.open,false,'cancel/Esc closes after its animation');

  // Refresh content in place, retaining cached fields when a fresh response omits them.
  openCard('book:a');await settle('book:a');
  const openingCount=frame.animations.filter(a=>a.options.duration===300).length;
  clickSelector('#detail-retry');await settle('book:a');
  const retryUrl=forcedSync('a');
  assert.ok(requests.includes(retryUrl),'retry issues a forced detail refresh');
  assert.ok(pendingFresh.some(x=>x.url===retryUrl),'forced retry sync is pending before its response is resolved');
  await settleFresh(retryUrl,{info:null,progress:null,notes:null,errors:[]});
  assert.ok(resolvedFresh.includes(retryUrl),'the forced retry response itself was consumed');
  assert.ok(!pendingFresh.some(x=>x.url===retryUrl),'forced retry is no longer pending after consumption');
  assert.equal(frame.animations.filter(a=>a.options.duration===300).length,openingCount,'content refresh does not replay the frame entrance');
  assert.match(get('detail-body').innerHTML,/50\.0%/,'partial refresh preserves cached recommendation info');
  assert.match(get('detail-body').innerHTML,/已读 42%/,'partial refresh preserves cached reading progress');
  assert.match(get('detail-body').innerHTML,/点评 2 · 书签 3 · 划线 4 · 合计 9/,'partial refresh preserves cached notes');
  close.dispatch('click');frame.animations.filter(a=>a.options.duration===180).at(-1).finish();await tick();

  // An old in-flight response must not repopulate the per-session cache after shelf replacement.
  openCard('book:b');
  get('shelf-sync').dispatch('click');
  for(let i=0;i<6;i++)await tick();
  await settle('book:b');
  await settleFresh(regularSync('b'),{info:{intro:'OLD IN-FLIGHT FRESH'},progress:{progress:70},notes:null,errors:[]});
  close.dispatch('click');frame.animations.filter(a=>a.options.duration===180).at(-1).finish();await tick();
  openCard('book:b');
  assert.match(get('detail-body').innerHTML,/正在读取简介/,'successful shelf replacement invalidates cache and blocks an older GET from restoring it');
  await settle('book:b');
  await settleFresh(regularSync('b'),{info:{intro:'FRESH INTRO'},progress:{progress:50},notes:null,errors:[]});
  close.dispatch('click');frame.animations.filter(a=>a.options.duration===180).at(-1).finish();await tick();

  // Reduced motion must remove spatial transforms while retaining a usable short fade.
  reduce=true;openCard('book:a');await settle('book:a');
  const reduced=frame.animations.at(-1);assert.ok(reduced.options.duration<=100,'reduced motion uses only a brief fade');
  assert.ok(!JSON.stringify(reduced.frames).includes('scale')&&!JSON.stringify(reduced.frames).includes('translate'),'reduced motion has no scale or translation');
  close.dispatch('click');frame.animations.filter(a=>a.options.duration<=100).at(-1).finish();await tick();

  // No WAAPI support must still complete open and close via the fallback path.
  reduce=false;Element.prototype.animate=undefined;openCard('book:b');await settle('book:b');
  assert.equal(dialog.open,true,'dialog remains usable when Element.animate is unavailable');
  close.dispatch('click');await new Promise(r=>setTimeout(r,240));
  assert.equal(dialog.open,false,'fallback close completes without WAAPI');
  Element.prototype.animate=originalAnimate;
  console.log('Detail animation timing, close lifecycle, stale completion, reduced motion and no-WAAPI checks passed.');
})().catch(e=>{Element.prototype.animate=originalAnimate;console.error(e);process.exitCode=1;});
