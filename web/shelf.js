'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = { items: [], loaded: false, syncing: null, active: null, opener: null, openerContainerId: null, openScrollY: 0, detailToken: 0, detailCacheEpoch: 0, notesSyncing: false, savedCategory: null, detailCache: new Map(), introExpanded: false, introObserver: null, lastIntroWidth: 0, introMeasureFrame: 0, closeAnimation: null, openAnimation: null, secondaryAnimation: null, backdropAnimation: null, sourceFeedback: null };
  const headers = {'X-WeRead-Client':'dashboard'};
  const time = value => value ? new Date(value).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
  const api = async (url, options={}) => { const response=await fetch(url,options); const data=await response.json(); if(!response.ok)throw new Error(data.error||'请求失败'); return data; };
  const cover = item => item.coverPath ? `<img loading="lazy" src="${escape(item.coverPath)}" alt="${escape(item.title)}封面"><span class="cover-placeholder" hidden>阅</span>` : '<span class="cover-placeholder">阅</span>';
  const dateValue = item => Number(item.readUpdateTime)||0;
  const isFinished = item => item.finished===true || Number(item.progress?.progress)===100;
  function wireCoverErrors(container){container?.querySelectorAll('.cover-art img, .detail-cover img').forEach(img=>{const fallback=()=>{img.hidden=true;if(img.nextElementSibling)img.nextElementSibling.hidden=false;};img.addEventListener('error',fallback,{once:true});if(img.complete&&img.naturalWidth===0)fallback();});}
  function sortedFiltered(){
    const q=$('shelf-search').value.trim().toLocaleLowerCase(), category=$('shelf-category').value, kind=$('shelf-kind').value, finished=$('shelf-finished').value;
    const rows=state.items.filter(x=> (category==='all'||x.category===category) && (kind==='all'||x.kind===kind) && (!q||`${x.title||''} ${x.author||''}`.toLocaleLowerCase().includes(q)) && (finished==='all'||(finished==='finished'?isFinished(x):(x.finished===false&&!isFinished(x)))));
    const sort=$('shelf-sort').value; rows.sort((a,b)=>sort==='title'?String(a.title).localeCompare(String(b.title),'zh-CN'):sort==='author'?String(a.author).localeCompare(String(b.author),'zh-CN'):dateValue(b)-dateValue(a)); return rows;
  }
  function card(item, recent=false){return `<button class="book-card ${recent?'recent-card':''}" data-book-id="${escape(item.id)}" aria-label="查看《${escape(item.title)}》详情"><span class="cover-art">${cover(item)}${isFinished(item)?'<span class="finished-mark">读完</span>':''}</span><span class="card-title">${escape(item.title||'未命名')}</span><span class="card-author">${escape(item.author||'作者未知')}</span>${recent?`<span class="recent-meta">${item.progress&&Number.isFinite(item.progress.progress)?`读到 ${escape(item.progress.progress)}%`:'最近读过'}</span>`:''}</button>`;}
  function render(){
    const active=document.activeElement,focusId=active?.dataset?.bookId,focusContainer=active?.closest?.('#book-wall, #recent-books')?.id,scrollY=window.scrollY;const cats=[...new Set(state.items.map(x=>x.category||'未分类'))].sort((a,b)=>a.localeCompare(b,'zh-CN')),select=$('shelf-category'),old=select.value;
    select.innerHTML='<option value="all">全部分类</option>'+cats.map(x=>`<option value="${escape(x)}">${escape(x)}</option>`).join('');if(cats.includes(old))select.value=old;else if(state.savedCategory&&cats.includes(state.savedCategory)){select.value=state.savedCategory;state.savedCategory=null;}else if(old!=='all')select.value='all';
    const rows=sortedFiltered(); $('shelf-content').hidden=!state.items.length; $('shelf-blank').hidden=!!state.items.length;
    if(!state.items.length)return;
    const recent=[...state.items].filter(x=>x.kind!=='articles'&&dateValue(x)>0).sort((a,b)=>dateValue(b)-dateValue(a)).slice(0,4);
    $('recent-books').innerHTML=recent.map(x=>card(x,true)).join('')||'<p class="recent-none">同步书架后，最近阅读会在这里出现。</p>';
    $('recent-count').textContent=recent.length?`${recent.length} 本`:'';
    $('library-count').textContent=`${rows.length} 个条目`;
    $('book-wall').innerHTML=rows.map(x=>card(x)).join(''); $('shelf-empty').hidden=!!rows.length;
    wireCoverErrors($('shelf-content'));if(focusId){const scope=focusContainer?document.getElementById(focusContainer):document;[...(scope?.querySelectorAll('[data-book-id]')||[])].find(x=>x.dataset.bookId===focusId)?.focus({preventScroll:true});}window.scrollTo({top:scrollY,behavior:'instant'});
  }
  function showShelf(data) {
    state.items = Array.isArray(data.items) ? data.items : [];
    state.detailCacheEpoch += 1;
    state.detailCache.clear();
    state.loaded = true;
    render();
    $('shelf-sync-time').textContent = data.syncedAt ? `更新于 ${time(data.syncedAt)}` : '';
    $('shelf-status').textContent = data.syncedAt
      ? `共 ${state.items.length} 个条目 · 最近同步 ${time(data.syncedAt)}`
      : '书架已就绪';
    $('shelf-status').classList.remove('error');
  }
  async function loadShelf(){try{showShelf(await api('/api/shelf'));}catch(e){$('shelf-status').textContent=e.message+'；可点击同步重试。';$('shelf-status').classList.add('error');}}
  async function syncShelf(){if(state.syncing)return state.syncing;const button=$('shelf-sync');button.disabled=true;$('shelf-status').textContent='正在同步书架…';state.syncing=api('/api/shelf/sync',{method:'POST',headers}).then(async data=>{showShelf(data);const recent=[...state.items].filter(x=>x.kind==='book'&&x.bookId&&dateValue(x)>0).sort((a,b)=>dateValue(b)-dateValue(a)).slice(0,4);await Promise.allSettled(recent.map(async item=>{const fresh=await api(`/api/book/sync?id=${encodeURIComponent(item.id)}&part=progress`,{method:'POST',headers});if(fresh.progress)item.progress=fresh.progress;}));render();}).catch(e=>{$('shelf-status').textContent=e.message+(state.items.length?' · 已保留上次书架':'');$('shelf-status').classList.add('error');}).finally(()=>{button.disabled=false;state.syncing=null;});return state.syncing;}
  function detailMarkup(item, data) {
    const info = data.info || {};
    const notes = data.notes;
    const intro = info.intro || (data.loading ? '正在读取简介…' : '暂无简介');
    let sections = '';

    if (item.kind === 'articles') {
      sections += `<section class="entry-note"><h3>收藏入口</h3><p>文章收藏已计入书架。此入口不代表文章正文或阅读进度，当前服务暂不读取文章内容。</p><small>${escape(item.category || '未分类')}</small></section>`;
    } else if (item.kind === 'album') {
      sections += `<section class="entry-note"><h3>有声书</h3><p>书架显示已知有声书元信息；当前不提供有声书章节进度与完读状态判断。</p><small>${escape(item.category || '未分类')}</small></section>`;
    } else {
      sections += `<section class="intro-section"><h3>简介</h3><p id="intro-copy" class="intro-copy ${state.introExpanded ? '' : 'is-collapsed'} ${!info.intro && data.loading ? 'loading-intro' : ''}">${escape(intro)}</p><button id="intro-toggle" class="text-button intro-toggle" type="button" aria-controls="intro-copy" aria-expanded="${state.introExpanded}" hidden>${state.introExpanded ? '收起' : '查看更多'}</button></section>`;
      const rating = Number(info.newRating);
      const ratingText = Number.isFinite(rating) && rating > 0
        ? `${(rating / 10).toFixed(1)}%`
        : data.loading ? '读取中…' : '暂无';
      const reviews = Number.isFinite(rating) && rating > 0 && info.newRatingCount != null
        ? `${escape(info.newRatingCount)} 人评价`
        : '';
      const noteValue = key => notes && notes[key] != null
        ? escape(notes[key])
        : data.loading ? '读取中…' : '未同步';
      sections += `<section class="detail-stats" aria-label="推荐值与笔记统计"><div class="stat-cell rating-cell"><span class="stat-label">推荐值</span><strong>${ratingText}</strong><small>${reviews}</small></div><div class="stat-cell"><span class="stat-label">想法/点评</span><strong>${noteValue('reviewCount')}</strong></div><div class="stat-cell"><span class="stat-label">书签</span><strong>${noteValue('bookmarkCount')}</strong></div><div class="stat-cell"><span class="stat-label">划线</span><strong>${noteValue('noteCount')}</strong></div><small class="notes-total">合计 ${noteValue('total')}</small></section>`;
    }

    if (data.errors?.length) {
      sections += `<p class="detail-error">${data.errors.map(escape).join(' · ')} <button class="text-button" id="detail-retry">重试</button></p>`;
    }
    const link = info.readerLink || info.deepLink || item.readerLink || item.deepLink;
    sections += '<div class="detail-actions">';
    if (item.kind === 'book') {
      sections += `<button class="button notes-sync" id="notes-sync" ${state.notesSyncing ? 'disabled' : ''}>${state.notesSyncing ? '同步笔记中…' : '同步笔记与划线'}</button>`;
    }
    if (link && (/^https:\/\//i.test(link) || /^weread:\/\//i.test(link))) {
      sections += `<a class="reader-link" href="${escape(link)}" target="_blank" rel="noopener">继续阅读 ↗</a>`;
    }
    sections += '</div>';
    return sections;
  }

  function animate(element, frames, duration, key, delay = 0) {
    state[key]?.cancel?.();
    state[key] = null;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      frames = frames.map(frame => ({ opacity: frame.opacity }));
      duration = 80;
      delay = 0;
    }
    if (typeof element.animate === 'function') {
      const animation = element.animate(frames, {
        duration,
        delay,
        easing: 'ease-in-out',
        fill: 'both'
      });
      state[key] = animation;
      const finished = animation.finished.catch(() => {});
      finished.finally(() => {
        if (state[key] === animation) {
          state[key] = null;
          animation.cancel();
        }
      });
      return finished;
    }
    let timer;
    let resolveDone;
    const fallback = {
      cancel() {
        clearTimeout(timer);
        resolveDone?.();
        if (state[key] === fallback) state[key] = null;
      }
    };
    state[key] = fallback;
    return new Promise(resolve => {
      resolveDone = resolve;
      timer = setTimeout(() => {
        if (state[key] === fallback) state[key] = null;
        resolve();
      }, duration + delay);
    });
  }

  const openFrames = [
    { opacity: 0, transform: 'scale(.985)' },
    { opacity: 1, transform: 'scale(1)' }
  ];
  const closeFrames = [
    { opacity: 1, transform: 'scale(1)' },
    { opacity: 0, transform: 'scale(.995)' }
  ];

  function mergeDetail(previous, next) {
    return {
      ...previous,
      ...next,
      info: next.info || previous.info,
      progress: next.progress || previous.progress,
      notes: next.notes || previous.notes,
      errors: [...(next.errors || [])]
    };
  }

  function renderDetail(item, data) {
    const body = $('detail-body');
    const scrollTop = body.scrollTop;
    const restoreToggleFocus = document.activeElement?.id === 'intro-toggle';
    body.innerHTML = detailMarkup(item, data);
    renderIdentity(item, data);
    body.scrollTop = scrollTop;
    refreshIntroMeasurement();
    if (restoreToggleFocus) {
      const toggle = $('intro-toggle');
      if (toggle && !toggle.hidden) toggle.focus({ preventScroll: true });
      else $('book-dialog').querySelector('.detail-frame').focus({ preventScroll: true });
    }
  }

  function renderIdentity(item, data) {
    const info = data.info || {};
    const progress = data.progress || item.progress;
    $('detail-title').textContent = item.title || '未命名';
    $('detail-title').title = item.title || '未命名';
    $('detail-author').textContent = item.author || '作者未知';
    $('detail-author').title = item.author || '作者未知';
    $('detail-kind').textContent = ({ book: '电子书', album: '有声书', articles: '文章收藏' })[item.kind] || '书籍';
    const publisher = [info.publisher, info.publishTime].filter(Boolean).join(' · ');
    $('detail-publisher').textContent = publisher || (data.loading ? '出版信息读取中…' : '暂无出版信息');
    $('detail-publisher').title = publisher;
    $('detail-progress').textContent = progress && Number.isFinite(progress.progress)
      ? `阅读进度 · 已读 ${progress.progress}%`
      : item.finished === true ? '阅读进度 · 已读完'
        : data.loading ? '阅读进度 · 正在读取…' : '阅读进度暂不可用';
  }

  function refreshIntroMeasurement() {
    if (!$('book-dialog').open) return;
    const copy = $('intro-copy');
    const button = $('intro-toggle');
    if (!copy || !button) return;
    const lineHeight = Number.parseFloat(getComputedStyle(copy).lineHeight);
    const collapsedHeight = Number.isFinite(lineHeight) ? lineHeight * 4 : copy.clientHeight;
    const overflowing = state.introExpanded
      ? copy.scrollHeight > collapsedHeight + 1
      : copy.scrollHeight > copy.clientHeight + 1;
    if (!overflowing) state.introExpanded = false;
    copy.classList.toggle('is-collapsed', !state.introExpanded);
    button.hidden = !overflowing;
    button.setAttribute('aria-expanded', String(state.introExpanded && overflowing));
    button.textContent = state.introExpanded && overflowing ? '收起' : '查看更多';
  }

  function scheduleIntroMeasurement() {
    cancelAnimationFrame(state.introMeasureFrame);
    state.introMeasureFrame = requestAnimationFrame(refreshIntroMeasurement);
  }

  function toggleIntro() {
    const copy = $('intro-copy');
    const button = $('intro-toggle');
    const body = $('detail-body');
    if (!copy || !button || button.hidden) return;
    state.introExpanded = !state.introExpanded;
    copy.classList.toggle('is-collapsed', !state.introExpanded);
    button.setAttribute('aria-expanded', String(state.introExpanded));
    button.textContent = state.introExpanded ? '收起' : '查看更多';
    button.focus({ preventScroll: true });
    if (!state.introExpanded) {
      button.scrollIntoView?.({ block: 'nearest', behavior: 'instant' });
      body.scrollTop = Math.max(0, Math.min(body.scrollTop, body.scrollHeight - body.clientHeight));
    }
  }

  async function openDetail(item, opener) {
    const dialog = $('book-dialog');
    const frame = dialog.querySelector('.detail-frame');
    const reopening = dialog.open && !!state.closeAnimation;
    if (dialog.open && state.active?.id === item.id && !reopening) {
      refreshDetail(item);
      return;
    }

    state.closeAnimation?.cancel();
    state.closeAnimation = null;
    state.openAnimation?.cancel();
    state.openAnimation = null;
    state.secondaryAnimation?.cancel();
    state.secondaryAnimation = null;
    state.sourceFeedback?.cancel();
    state.sourceFeedback = null;
    state.introExpanded = false;
    state.active = item;
    state.opener = opener;
    state.openerContainerId = opener?.closest('#book-wall')?.id ||
      opener?.closest('#recent-books')?.id || null;
    if (!dialog.open) state.openScrollY = window.scrollY;

    const token = ++state.detailToken;
    const cacheEpoch = state.detailCacheEpoch;
    const cached = state.detailCache.get(item.id);
    $('detail-cover-wrap').innerHTML = `<div class="detail-cover">${cover(item)}</div>`;
    wireCoverErrors($('detail-cover-wrap'));
    renderDetail(item, cached ? { ...cached, loading: false } : {
      info: null,
      progress: item.progress,
      notes: null,
      loading: item.kind === 'book'
    });

    if (!dialog.open) dialog.showModal();
    document.body.classList.add('dialog-open');
    refreshIntroMeasurement();
    requestAnimationFrame(() => frame.focus({ preventScroll: true }));
    if (opener) {
      animate(opener, [
        { transform: 'scale(1)' }, { transform: 'scale(.985)' }, { transform: 'scale(1)' }
      ], 90, 'sourceFeedback');
    }
    if (!reopening) {
      animate(frame, openFrames, 320, 'openAnimation', 40);
      animate(dialog.querySelector('.detail-copy'), [
        { opacity: 0 }, { opacity: 1 }
      ], 200, 'secondaryAnimation', 100);
    }
    animate(dialog.querySelector('.dialog-backdrop'), [
      { opacity: 0 }, { opacity: 1 }
    ], reopening ? 100 : 220, 'backdropAnimation');

    if (item.kind !== 'book') return;
    try {
      const response = await api(`/api/book?id=${encodeURIComponent(item.id)}`);
      if (token !== state.detailToken) return;
      const current = mergeDetail(cached || {}, response);
      if (cacheEpoch === state.detailCacheEpoch) state.detailCache.set(item.id, current);
      const stale = part => {
        const stamp = response[`${part}SyncedAt`];
        return !stamp || Date.now() - new Date(stamp).getTime() >
          (part === 'info' ? 900000 : 300000);
      };
      const needsSync = !response.info || !response.progress || response.errors?.length ||
        stale('info') || stale('progress');
      renderDetail(item, { ...current, loading: needsSync });
      if (needsSync) {
        const fresh = await api(`/api/book/sync?id=${encodeURIComponent(item.id)}&part=all`, {
          method: 'POST', headers
        });
        if (token !== state.detailToken) return;
        const merged = mergeDetail(current, fresh);
        if (cacheEpoch === state.detailCacheEpoch) state.detailCache.set(item.id, merged);
        renderDetail(item, { ...merged, loading: false });
      }
    } catch (error) {
      if (token === state.detailToken) {
        renderDetail(item, { ...(state.detailCache.get(item.id) || {}), loading: false });
        $('detail-body').insertAdjacentHTML('beforeend',
          `<p class="detail-error">${escape(error.message)} <button class="text-button" id="detail-retry">重试</button></p>`);
      }
    }
  }

  async function refreshDetail(item) {
    const token = ++state.detailToken;
    const cacheEpoch = state.detailCacheEpoch;
    const previous = state.detailCache.get(item.id) || {};
    renderDetail(item, { ...previous, loading: true });
    try {
      const response = await api(`/api/book?id=${encodeURIComponent(item.id)}`);
      if (token !== state.detailToken) return;
      const current = mergeDetail(previous, response);
      if (cacheEpoch === state.detailCacheEpoch) state.detailCache.set(item.id, current);
      renderDetail(item, { ...current, loading: true });
      const fresh = await api(`/api/book/sync?id=${encodeURIComponent(item.id)}&part=all&force=1`, {
        method: 'POST', headers
      });
      if (token !== state.detailToken) return;
      const merged = mergeDetail(current, fresh);
      if (cacheEpoch === state.detailCacheEpoch) state.detailCache.set(item.id, merged);
      renderDetail(item, { ...merged, loading: false });
    } catch (error) {
      if (token === state.detailToken) {
        renderDetail(item, {
          ...(state.detailCache.get(item.id) || previous),
          loading: false
        });
        $('detail-body').insertAdjacentHTML('beforeend',
          `<p class="detail-error">${escape(error.message)} <button class="text-button" id="detail-retry">重试</button></p>`);
      }
    }
  }

  function closeDetail() {
    const dialog = $('book-dialog');
    if (!dialog.open || state.closeAnimation) return;
    state.openAnimation?.cancel?.();
    state.openAnimation = null;
    state.secondaryAnimation?.cancel?.();
    state.secondaryAnimation = null;
    state.sourceFeedback?.cancel?.();
    state.sourceFeedback = null;
    const frame = dialog.querySelector('.detail-frame');
    const token = ++state.detailToken;
    let focusTarget = state.opener?.isConnected ? state.opener : null;
    if (!focusTarget && state.openerContainerId) {
      focusTarget = [...document.querySelectorAll(`#${state.openerContainerId} [data-book-id]`)]
        .find(node => node.dataset.bookId === state.active?.id) || null;
    }
    if (!focusTarget) {
      focusTarget = [...document.querySelectorAll('[data-book-id]')]
        .find(node => node.dataset.bookId === state.active?.id) || $('view-shelf');
    }
    const finish = () => {
      if (token !== state.detailToken) return;
      dialog.close();
      document.body.classList.remove('dialog-open');
      focusTarget.focus({ preventScroll: true });
      window.scrollTo({ top: state.openScrollY, behavior: 'instant' });
      state.closeAnimation = null;
    };
    animate(frame, closeFrames, 180, 'closeAnimation').then(finish);
    animate(dialog.querySelector('.dialog-backdrop'), [
      { opacity: 1 }, { opacity: 0 }
    ], 180, 'backdropAnimation');
  }
  async function syncNotes() {
    if (state.notesSyncing) return;
    state.notesSyncing = true;
    const token = state.detailToken;
    const cacheEpoch = state.detailCacheEpoch;
    const button = $('notes-sync');
    if (button) {
      button.disabled = true;
      button.textContent = '同步笔记中…';
    }
    try {
      await api('/api/notes/sync', { method: 'POST', headers });
      if (state.active && token === state.detailToken) {
        const item = state.active;
        const response = await api(`/api/book?id=${encodeURIComponent(item.id)}`);
        if (token === state.detailToken) {
          const merged = mergeDetail(state.detailCache.get(item.id) || {}, response);
          if (cacheEpoch === state.detailCacheEpoch) state.detailCache.set(item.id, merged);
          renderDetail(item, { ...merged, loading: false });
        }
      }
    } catch (error) {
      if (token === state.detailToken) {
        $('detail-body').insertAdjacentHTML('beforeend',
          `<p class="detail-error">${escape(error.message)}</p>`);
      }
    } finally {
      state.notesSyncing = false;
      const currentButton = $('notes-sync');
      if (currentButton) {
        currentButton.disabled = false;
        currentButton.textContent = '同步笔记与划线';
      }
    }
  }
  function init(){
    $('sync').hidden=true;$('updated').hidden=true;
    if (typeof ResizeObserver === 'function') {
      state.introObserver = new ResizeObserver(entries => {
        const width = entries[0]?.contentRect?.width || $('detail-body').clientWidth;
        if (Math.abs(width - state.lastIntroWidth) < 1) return;
        state.lastIntroWidth = width;
        scheduleIntroMeasurement();
      });
      state.introObserver.observe($('detail-body'));
    }
    window.addEventListener?.('resize', scheduleIntroMeasurement);
    document.fonts?.ready?.then(scheduleIntroMeasurement);
    $('view-shelf').addEventListener('click',()=>{$('shelf-view').hidden=false;$('stats-view').hidden=true;$('sync').hidden=true;$('updated').hidden=true;$('view-shelf').classList.add('active');$('view-stats').classList.remove('active');$('view-shelf').setAttribute('aria-pressed','true');$('view-stats').setAttribute('aria-pressed','false');});
    $('view-stats').addEventListener('click',()=>{$('shelf-view').hidden=true;$('stats-view').hidden=false;$('sync').hidden=false;$('updated').hidden=false;$('view-stats').classList.add('active');$('view-shelf').classList.remove('active');$('view-stats').setAttribute('aria-pressed','true');$('view-shelf').setAttribute('aria-pressed','false');});
    const preferences=['shelf-sort','shelf-category','shelf-kind','shelf-finished'];try{preferences.forEach(id=>{const value=localStorage.getItem(id);if(value){if(id==='shelf-category')state.savedCategory=value;else if([...$(id).options].some(o=>o.value===value))$(id).value=value;}});}catch{}
    const persist=()=>{try{preferences.forEach(id=>localStorage.setItem(id,$(id).value));}catch{}};
    ['shelf-search',...preferences].forEach(id=>$(id).addEventListener(id==='shelf-search'?'input':'change',()=>{render();persist();}));
    $('shelf-reset').addEventListener('click',resetFilters);$('shelf-empty-reset').addEventListener('click',resetFilters);function resetFilters(){$('shelf-search').value='';$('shelf-sort').value='recent';$('shelf-category').value='all';$('shelf-kind').value='all';$('shelf-finished').value='all';render();try{preferences.forEach(id=>localStorage.removeItem(id));}catch{}}
    $('shelf-sync').addEventListener('click',syncShelf);$('shelf-empty-sync').addEventListener('click',syncShelf);
    document.addEventListener('click',event=>{const card=event.target.closest('[data-book-id]');if(card){const item=state.items.find(x=>x.id===card.dataset.bookId);if(item)openDetail(item,card);return;}if(event.target.closest('#intro-toggle'))toggleIntro();if(event.target.closest('#notes-sync'))syncNotes();if(event.target.closest('#detail-retry')&&state.active)refreshDetail(state.active);});
    $('detail-close').addEventListener('click',closeDetail);$('book-dialog').addEventListener('click',e=>{if(e.target.hasAttribute('data-close'))closeDetail();});$('book-dialog').addEventListener('cancel',e=>{e.preventDefault();closeDetail();});
    loadShelf().finally(()=>syncShelf());
  }
  init();
})();
