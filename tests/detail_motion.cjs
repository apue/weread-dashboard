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
  constructor(id=''){this.id=id;this.value=id==='shelf-search'?'':id==='shelf-sort'?'recent':'all';this.hidden=false;this.disabled=false;this.textContent='';this._innerHTML='';this.events={};this.dataset={};this.attrs={};this.isConnected=true;this.open=false;this.focusCalls=[];this._classes=new Set();this.classList={add:(...xs)=>xs.forEach(x=>this._setClass(x,true)),remove:(...xs)=>xs.forEach(x=>this._setClass(x,false)),contains:x=>this._classes.has(x),toggle:(x,on)=>{const next=on===undefined?!this._classes.has(x):!!on;this._setClass(x,next);return next;}};this.animations=[];this.style={};this.scrollTop=0;this.clientHeight=0;this.scrollHeight=0;}
  _setClass(name,yes){if(yes)this._classes.add(name);else this._classes.delete(name);if(this.id==='intro-copy')this.clientHeight=this._classes.has('is-collapsed')?Math.min(this.scrollHeight,80):this.scrollHeight;}
  get innerHTML(){return this._innerHTML;}
  set innerHTML(value){this._innerHTML=value;if(this.id!=='detail-body')return;const el=get('intro-copy'),button=get('intro-toggle');const match=value.match(/<p id="intro-copy" class="([^"]*)"[^>]*>([\s\S]*?)<\/p>/);if(!match){el.scrollHeight=0;el.clientHeight=0;button.hidden=true;return;}el._classes=new Set(match[1].split(/\s+/).filter(Boolean));const plain=match[2].replace(/<[^>]*>/g,'').replace(/&(?:amp|lt|gt|quot|#39);/g,'x');el.scrollHeight=Math.max(20,Math.ceil(plain.length/40)*20);el.clientHeight=el.classList.contains('is-collapsed')?Math.min(el.scrollHeight,80):el.scrollHeight;button.hidden=/\shidden(?:\s|>)/.test(value.match(/<button id="intro-toggle"[^>]*>/)?.[0]||'');const expanded=value.match(/<button id="intro-toggle"[^>]*aria-expanded="([^"]+)"/);const controls=value.match(/<button id="intro-toggle"[^>]*aria-controls="([^"]+)"/);button.attrs['aria-expanded']=expanded?.[1]||'false';button.attrs['aria-controls']=controls?.[1]||null;button.textContent=match[1].includes('is-collapsed')?'查看更多':'收起';}
  addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
  dispatch(type,event={}){for(const fn of this.events[type]||[])fn({target:this,preventDefault(){},...event});}
  setAttribute(k,v){this.attrs[k]=v;}
  getAttribute(k){return this.attrs[k]??null;}
  hasAttribute(k){return Object.hasOwn(this.attrs,k);}
  querySelector(sel){if(sel==='.detail-sheet')return sheet;if(sel==='.detail-frame')return frame;if(sel==='.detail-copy')return copy;if(sel==='.detail-cover')return cover;if(sel==='.dialog-backdrop')return backdrop;return null;}
  querySelectorAll(){return [];}
  showModal(){this.open=true;}
  close(){this.open=false;this.closeCount=(this.closeCount||0)+1;}
  focus(options){this.focusCalls.push(options);document.activeElement=this;}
  getBoundingClientRect(){return {left:10,top:20,width:100,height:120};}
  cloneNode(){const clone=new Element(this.id);clone.scrollHeight=this.scrollHeight;clone.clientHeight=this.clientHeight;clone._classes=new Set(this._classes);return clone;}
  remove(){this.isConnected=false;}
  append(node){(this.children||(this.children=[])).push(node);}
  animate(frames,options){const a=new Animation(this,frames,options);this.animations.push(a);return a;}
  insertAdjacentHTML(_where,html){this.innerHTML+=html;}
  closest(){return null;}
}
const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
const sheet=new Element('sheet'),frame=new Element('frame'),copy=new Element('detail-copy'),cover=new Element('cover'),backdrop=new Element('backdrop');
const docEvents={};const document={activeElement:null,body:new Element('body'),getElementById:get,querySelectorAll(){return [];},addEventListener(type,fn){(docEvents[type]??=[]).push(fn);}};
const resizeState={pending:[],observes:0,delivered:0};
const resizeObservers=[];
class FakeResizeObserver {
  constructor(callback){this.callback=callback;this.targets=new Set();resizeObservers.push(this);}
  observe(target){this.targets.add(target);resizeState.observes++;resizeState.pending.push(()=>{resizeState.delivered++;this.callback([{target,contentRect:{width:target.clientWidth,height:target.clientHeight}}]);});}
  disconnect(){this.targets.clear();}
  trigger(width){this.callback([{target:get('detail-body'),contentRect:{width,height:get('detail-body').clientHeight}}]);}
}
get('detail-body').clientWidth=760;get('detail-body').clientHeight=500;get('detail-body').scrollHeight=900;
let scrollY=87;const scrollCalls=[];const window={get scrollY(){return scrollY;},scrollTo(x){scrollCalls.push(x);scrollY=x.top;}};
let reduce=false;
const originalAnimate=Element.prototype.animate;
const items=['a','b'].map((id,i)=>({id:`book:${id}`,kind:'book',title:`Book ${id}`,author:'Writer',category:'Fiction',readUpdateTime:10-i,progress:null}));
const shelf={items,syncedAt:null,demo:false,notesSyncedAt:null};const pending={};const pendingFresh=[];const resolvedFresh=[];const requests=[];
const fetch=async url=>{
  requests.push(url);
  if(url==='/api/shelf')return{ok:true,json:async()=>shelf};
  if(url==='/api/shelf/sync')return{ok:true,json:async()=>({...shelf,syncedAt:'2026-01-01T00:00:00Z'})};
  if(url==='/api/notes/sync')return{ok:true,json:async()=>({})};
  if(url.startsWith('/api/book?id='))return new Promise(resolve=>{
    const id=decodeURIComponent(url.split('id=')[1]);
    const intro=id==='book:a'?'CACHE INTRO '+'较长的虚构简介用于验证真实溢出展开。'.repeat(45)+' <img src=x> & <script>bad()</script>': 'SHORT INTRO';
    (pending[id]??=[]).push(()=>resolve({ok:true,json:async()=>({id,info:{intro,newRating:500,newRatingCount:1},progress:{progress:42},notes:{reviewCount:2,bookmarkCount:3,noteCount:4,total:9},errors:[]})}));
  });
  if(url.startsWith('/api/book/sync?')&&url.includes('part=all'))return new Promise(resolve=>pendingFresh.push({url,resolve:data=>resolve({ok:true,json:async()=>data})}));
  if(url.startsWith('/api/book/sync?'))return{ok:true,json:async()=>({progress:{progress:42}})};
  throw Error(`Unexpected request ${url}`);
};
const ctx=vm.createContext({document,window,fetch,localStorage:{getItem(){return null},setItem(){},removeItem(){}},CSS:{escape:x=>x},matchMedia:q=>({matches:q.includes('prefers-reduced-motion')&&reduce}),getComputedStyle:()=>({lineHeight:'20px',overflowY:'auto',opacity:'1'}),requestAnimationFrame:fn=>fn(),cancelAnimationFrame(){},ResizeObserver:FakeResizeObserver,console,Date,Math,Map,Set,String,Number,JSON,Error,encodeURIComponent,decodeURIComponent,setTimeout,clearTimeout});
vm.runInContext(readFileSync('web/shelf.js','utf8'),ctx);
const tick=()=>new Promise(r=>setImmediate(r));
const openCard=id=>{const card=new Element(`card-${id}`);card.dataset.bookId=id;card.closest=sel=>sel==='#book-wall'?get('book-wall'):null;for(const fn of docEvents.click||[])fn({target:{closest:sel=>sel==='[data-book-id]'?card:null}});return card;};
const clickSelector=selector=>{const target=selector==='#intro-toggle'?get('intro-toggle'):new Element('click-target');for(const fn of docEvents.click||[])fn({target:{closest:sel=>sel===selector?target:null}});if(target.events.click?.length)target.dispatch('click');};
const settle=async id=>{await tick();const q=pending[id]||[];q.shift()?.();await tick();};
const flushResize=async()=>{let rounds=0;while(resizeState.pending.length&&rounds<8){const next=resizeState.pending.shift();next();rounds++;await tick();}assert.equal(resizeState.pending.length,0,'unchanged-size ResizeObserver notifications do not reschedule themselves indefinitely');return rounds;};
const resizeIntro=(width,height)=>{get('detail-body').clientWidth=width;get('intro-copy').scrollHeight=height;resizeObservers[0].trigger(width);};
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
  assert.match(get('detail-body').innerHTML,/读取中/,'unknown recommendation is marked loading rather than absent');
  const feedback=first.animations.at(-1);assert.ok(feedback.options.duration>=80&&feedback.options.duration<=100,'source card gets a short selection feedback');
  const entrance=frame.animations.at(-1);assert.equal(entrance.options.duration,320,'opening uses the 320ms card animation');
  assert.equal(entrance.options.delay,40,'card entrance follows the backdrop by 40ms');
  const backdropEntrance=backdrop.animations.at(-1);
  assert.equal(backdropEntrance.options.duration,220,'opening backdrop uses the synchronized 220ms fade');
  assert.equal(backdropEntrance.options.delay,0,'backdrop starts immediately');
  const secondaryEntrance=copy.animations.at(-1);assert.equal(secondaryEntrance.options.duration,200,'secondary content has a short fade');
  assert.equal(secondaryEntrance.options.delay,100,'secondary content follows the card entrance');
  assert.equal(entrance.target,frame,'the inner detail frame animates; its positioning wrapper does not');
  assert.equal(entrance.options.easing,'ease-in-out','entrance uses a gradual easing curve');
  assert.ok(entrance.frames.every(f=>!String(f.transform).includes('translate')),'entrance does not animate position with translate');
  await settle('book:a');
  assert.match(get('detail-body').innerHTML,/CACHE INTRO/,'cached GET content replaces the loading placeholder before fresh sync returns');
  assert.match(get('detail-body').innerHTML,/&lt;img src=x&gt;/,'long intro HTML is escaped before rendering');
  assert.doesNotMatch(get('detail-body').innerHTML,/<img src=x>/,'intro content cannot inject markup');
  assert.ok(get('intro-copy').scrollHeight>get('intro-copy').clientHeight,'long intro is detected by measured overflow');
  assert.equal(get('intro-toggle').hidden,false,'overflowing intro exposes its expansion button');
  assert.equal(get('intro-toggle').getAttribute('aria-controls'),'intro-copy','intro toggle names its controlled paragraph');
  await settleFresh(regularSync('a'),{info:{intro:'FRESH INTRO '+'较长的新版简介用于保持展开状态。'.repeat(40),newRating:650,newRatingCount:3},progress:{progress:88},notes:{reviewCount:5,bookmarkCount:6,noteCount:7,total:18},errors:[]});
  assert.match(get('detail-body').innerHTML,/FRESH INTRO/,'fresh sync content replaces cached content asynchronously');
  assert.equal(get('intro-toggle').hidden,false,'long fresh content retains its expansion button');
  const beforeExpandRequests=requests.length;
  clickSelector('#intro-toggle');
  assert.equal(requests.length,beforeExpandRequests,'expanding the intro is entirely local');
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'true','expanded state is exposed accessibly');
  assert.equal(get('intro-toggle').textContent,'收起','toggle label changes while expanded');
  assert.equal(get('intro-copy').classList.contains('is-collapsed'),false,'expanded paragraph removes the collapsed clamp');
  assert.equal(get('intro-copy').clientHeight,get('intro-copy').scrollHeight,'expanded content exposes its full measured height');
  const focusedToggle=get('intro-toggle');assert.equal(document.activeElement,focusedToggle,'the expansion button keeps focus after toggling');
  get('detail-body').scrollTop=150;
  const observerCount=resizeState.observes;
  const notificationCount=await flushResize();
  assert.ok(notificationCount<=1,'an unchanged initial ResizeObserver notification settles after one measure');
  assert.equal(resizeState.observes,observerCount,'measurement does not disconnect and reobserve the same scroll container');
  assert.equal(get('detail-body').scrollTop,150,'a no-width-change observer callback does not reset expanded scroll position');
  // A responsive remeasure that now fits four lines must synchronize the real clamp class.
  resizeIntro(1180,80);
  assert.equal(get('intro-copy').classList.contains('is-collapsed'),true,'when wider layout fits four lines, measurement reapplies the actual clamp');
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'false','width remeasure that fits content resets aria state');
  assert.equal(get('intro-toggle').hidden,true,'width remeasure hides the no-longer-needed button');
  assert.equal(get('intro-copy').clientHeight,get('intro-copy').scrollHeight,'the re-clamped paragraph reports consistent measured dimensions');
  // A later narrower layout overflows the collapsed client height and restores the action.
  resizeIntro(480,220);
  assert.equal(get('intro-copy').classList.contains('is-collapsed'),true,'narrow layout retains the real collapsed clamp');
  assert.equal(get('intro-copy').clientHeight,80,'collapsed client height remains bound to the four-line clamp');
  assert.ok(get('intro-copy').scrollHeight>get('intro-copy').clientHeight,'narrow layout reports actual overflow again');
  assert.equal(get('intro-toggle').hidden,false,'narrow layout makes the expansion action available again');
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'false','restored button starts collapsed accessibly');
  clickSelector('#intro-toggle');
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'true','restored button expands content after a width cycle');
  openCard('book:a');await settle('book:a');
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'true','same-book asynchronous refresh preserves expanded state');
  assert.equal(document.activeElement,focusedToggle,'asynchronous rendering restores focus to the expansion button');
  assert.equal(focusedToggle.focusCalls.at(-1)?.preventScroll,true,'restored intro focus does not move the page');
  await settleFresh(forcedSync('a'),{info:{intro:'FRESH INTRO '+'updated text '.repeat(40)},progress:{progress:88},notes:{reviewCount:5,bookmarkCount:6,noteCount:7,total:18},errors:[]});
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'true','fresh refresh does not collapse the expanded intro');
  const beforeCollapseRequests=requests.length;
  clickSelector('#intro-toggle');
  assert.equal(requests.length,beforeCollapseRequests,'collapsing the intro remains local');
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'false','collapsed state is exposed accessibly');
  assert.equal(get('intro-toggle').textContent,'查看更多','toggle label returns when collapsed');
  assert.equal(get('intro-copy').classList.contains('is-collapsed'),true,'collapse reapplies the clamp');
  assert.equal(document.activeElement,get('intro-toggle'),'collapse keeps focus on its button');
  clickSelector('#intro-toggle');
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'true','the intro can be expanded again before closing');
  assert.equal(dialog.children?.length||0,0,'opening does not add a ghost node to the dialog');
  close.dispatch('click');close.dispatch('click');
  assert.equal(feedback.cancelled,true,'closing cancels source-card feedback');
  assert.equal(entrance.cancelled,true,'starting close cancels an unfinished frame entrance');
  assert.equal(secondaryEntrance.cancelled,true,'closing cancels the secondary content entrance');
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
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'false','closing and reopening the book resets its intro to collapsed');
  await settle('book:a');
  close.dispatch('click');const oldExit=frame.animations.filter(a=>a.options.duration===180).at(-1),oldBackdropExit=backdrop.animations.at(-1);
  const other=openCard('book:b');await settle('book:b');await settleFresh(regularSync('b'),{info:{intro:'B FRESH'},progress:{progress:35},notes:null,errors:[]});
  assert.equal(get('intro-toggle').hidden,true,'short intro hides the expansion button');
  assert.ok(get('intro-copy').scrollHeight<=get('intro-copy').clientHeight,'short intro does not overflow its measured clamp');
  assert.equal(get('intro-toggle').getAttribute('aria-expanded'),'false','switching books resets expanded state');
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
  const openingCount=frame.animations.filter(a=>a.options.duration===320).length;
  clickSelector('#detail-retry');await settle('book:a');
  const retryUrl=forcedSync('a');
  assert.ok(requests.includes(retryUrl),'retry issues a forced detail refresh');
  assert.ok(pendingFresh.some(x=>x.url===retryUrl),'forced retry sync is pending before its response is resolved');
  await settleFresh(retryUrl,{info:null,progress:null,notes:null,errors:[]});
  assert.ok(resolvedFresh.includes(retryUrl),'the forced retry response itself was consumed');
  assert.ok(!pendingFresh.some(x=>x.url===retryUrl),'forced retry is no longer pending after consumption');
  assert.equal(frame.animations.filter(a=>a.options.duration===320).length,openingCount,'content refresh does not replay the frame entrance');
  assert.match(get('detail-body').innerHTML,/50\.0%/,'partial refresh preserves cached recommendation info');
  assert.match(get('detail-progress').textContent,/已读 42%/,'partial refresh preserves cached reading progress');
  assert.match(get('detail-body').innerHTML,/想法\/点评<\/span><strong>2<\/strong>/,'partial refresh preserves cached review count');
  assert.match(get('detail-body').innerHTML,/书签<\/span><strong>3<\/strong>/,'partial refresh preserves cached bookmark count');
  assert.match(get('detail-body').innerHTML,/划线<\/span><strong>4<\/strong>/,'partial refresh preserves cached highlight count');
  assert.match(get('detail-body').innerHTML,/合计 9/,'partial refresh preserves cached total count');
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
  reduce=true;const reducedCard=openCard('book:a');await settle('book:a');
  const reduced=frame.animations.at(-1);assert.ok(reduced.options.duration<=100,'reduced motion uses only a brief fade');
  assert.equal(reduced.options.delay,0,'reduced motion removes frame entrance delay');
  assert.ok(copy.animations.at(-1).options.duration<=100&&copy.animations.at(-1).options.delay===0,'reduced motion removes secondary delay');
  assert.ok(backdrop.animations.at(-1).options.duration<=100&&backdrop.animations.at(-1).options.delay===0,'reduced motion removes backdrop wait');
  assert.ok(reducedCard.animations.at(-1).options.duration<=100&&reducedCard.animations.at(-1).options.delay===0,'reduced motion removes source feedback wait');
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
