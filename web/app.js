'use strict';
const $ = id => document.getElementById(id);
let snapshot;
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const hours = seconds => (seconds / 3600).toFixed(1);
const duration = seconds => seconds === null ? '无明细' : seconds < 60 ? `${Math.round(seconds)} 秒` : `${Math.floor(seconds/3600) ? Math.floor(seconds/3600)+' 小时 ' : ''}${Math.floor(seconds%3600/60)} 分钟`;
const parseDay = value => new Date(value + 'T00:00:00Z');
const iso = date => date.toISOString().slice(0,10);
const sum = (rows, field) => rows.reduce((total,row) => total + row[field],0);
const selectedMonths = () => snapshot.months.slice(-Number($('range').value));
const svg = (width,height,content,label) => `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(label)}">${content}</svg><p class="chart-tooltip" aria-live="polite"></p>`;
function axis(w,h,max,labels=4){
  let content='';
  for(let i=0;i<=labels;i++){
    const y=18+(h-52)*(1-i/labels);
    content+=`<line class="grid" x1="36" x2="${w-12}" y1="${y}" y2="${y}"/><text x="26" y="${y+4}" text-anchor="end">${(max*i/labels).toFixed(max<4?1:0)}</text>`;
  }
  return content;
}
function wireChart(container){
  container.querySelectorAll('[data-detail]').forEach(mark=>{
    const show=()=>{container.querySelector('.chart-tooltip').textContent=mark.dataset.detail;};
    mark.addEventListener('mouseenter',show);mark.addEventListener('focus',show);
  });
}
function renderWeekly(days){
  const weeks=new Map();
  for(const day of days){
    const date=parseDay(day.date);date.setUTCDate(date.getUTCDate()-(date.getUTCDay()+6)%7);
    const key=iso(date);
    if(!weeks.has(key))weeks.set(key,{key,seconds:0,known:0,count:0,active:0});
    const week=weeks.get(key);week.count++;
    if(day.seconds!==null){week.seconds+=day.seconds;week.known++;week.active+=Number(day.seconds>=60);}
  }
  const rows=[...weeks.values()],w=Math.max(460,rows.length*18,$('weekly').clientWidth),h=235,max=Math.ceil(Math.max(1,...rows.map(r=>r.seconds/3600))*1.18);
  const slot=(w-52)/rows.length,barWidth=Math.min(42,slot*.58);
  let content=axis(w,h,max);
  rows.forEach((row,i)=>{
    const x=42+i*slot+slot/2,barHeight=(h-52)*(row.seconds/3600/max),y=h-34-barHeight;
    const partial=row.count<7||row.known<row.count;
    const detail=`${row.key} 起：${row.known?duration(row.seconds):'无明细'}；${row.active} 个有效阅读日${partial?'（范围内部分周 / 明细不完整）':''}`;
    content+=`<rect tabindex="0" data-detail="${escape(detail)}" role="img" aria-label="${escape(detail)}" class="bar ${partial?'partial':i===rows.length-1?'current':''}" x="${x-barWidth/2}" y="${y}" width="${barWidth}" height="${Math.max(1,barHeight)}" rx="4"><title>${escape(detail)}</title></rect>`;
    if(rows.length<=15)content+=`<text class="value" x="${x}" y="${y-8}" text-anchor="middle">${row.known?hours(row.seconds):'—'}</text>`;
    if(i%Math.max(1,Math.ceil(rows.length/12))===0)content+=`<text x="${x}" y="${h-10}" text-anchor="middle">${row.key.slice(5).replace('-','/')}</text>`;
  });
  $('weekly').innerHTML=svg(w,h,content,'按周汇总的阅读与收听时长，单位小时');$('weekly').querySelector('svg').style.minWidth=`${Math.max(460,rows.length*18)}px`;wireChart($('weekly'));
  $('weekly-note').textContent='周一为一周起点；浅色柱表示范围边界、不完整周或缺少日明细，不能直接与完整周比较。悬停或用 Tab 查看时长与阅读天数。';
}
function renderCalendar(months){
  $('calendar').innerHTML=months.map(month=>{
    const first=parseDay(month.month+'-01'),padding=(first.getUTCDay()+6)%7;
    const year=first.getUTCFullYear(),m=first.getUTCMonth();
    const count=new Date(Date.UTC(year,m+1,0)).getUTCDate();
    let cells='<span></span>'.repeat(padding);
    for(let day=1;day<=count;day++){
      const row=month.days[day-1];
      if(!row){cells+=`<span class="day future" aria-label="尚未发生">${day}</span>`;continue;}
      const s=row.seconds,level=s===null?'missing':s===0?'level0':s<900?'level1':s<2700?'level2':s<5400?'level3':'level4';
      const label=`${row.date} · ${duration(s)}${s!==null&&s>0&&s<60?'（不足 1 分钟，不计有效阅读日）':''}`;
      cells+=`<button class="day ${level}" data-day="${escape(label)}" title="${escape(label)}" aria-label="${escape(label)}">${day}</button>`;
    }
    return `<div class="calendar-month"><h3>${year} 年 ${m+1} 月</h3><div class="weekday">${['一','二','三','四','五','六','日'].map(d=>`<span>${d}</span>`).join('')}</div><div class="days">${cells}</div></div>`;
  }).join('');
  $('calendar').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{
    $('calendar').querySelector('.selected')?.classList.remove('selected');button.classList.add('selected');$('day-detail').textContent=button.dataset.day;
  }));
  $('calendar-subtitle').textContent='按天累计，不拆分碎片阅读。有效阅读日：单日满 1 分钟。';
}
function renderMonth(){
  const month=snapshot.months.find(m=>m.month===$('month').value);
  if(!month)return;
  const w=495,h=220;let running=0;
  if(!month.dailyComplete){
    $('cumulative').innerHTML='<div class="no-chart">日明细不完整，暂不绘制累计曲线。</div>';
    $('cumulative-note').textContent='月总时长仍采用接口返回的总量；缺失日期不会被当作零。';
  }else{
    const rows=month.days.map(d=>({...d,cumulative:running+=d.seconds})),max=Math.max(1,running/3600)*1.15;
    const x=i=>40+i*(w-57)/Math.max(1,rows.length-1),y=v=>h-34-(h-52)*v/3600/max;
    const points=rows.map((r,i)=>`${x(i)},${y(r.cumulative)}`).join(' ');
    let content=axis(w,h,max)+`<polygon class="area" points="40,${h-34} ${points} ${x(rows.length-1)},${h-34}"/><polyline class="line" points="${points}"/>`;
    rows.forEach((r,i)=>{
      const detail=`${r.date} · 当天 ${duration(r.seconds)} · 累计 ${duration(r.cumulative)}`;
      content+=`<circle cx="${x(i)}" cy="${y(r.cumulative)}" r="5" fill="#407a59" fill-opacity="${i===rows.length-1?1:0}" tabindex="0" data-detail="${escape(detail)}" aria-label="${escape(detail)}"><title>${escape(detail)}</title></circle>`;
      if(i===0||i===rows.length-1||(i+1)%7===0)content+=`<text x="${x(i)}" y="${h-10}" text-anchor="middle">${i+1}日</text>`;
    });
    $('cumulative').innerHTML=svg(w,h,content,'所选月份逐日累计阅读与收听时长');wireChart($('cumulative'));
    $('cumulative-note').textContent=`${month.month} · 截至 ${month.days.at(-1).date}，累计 ${duration(running)}。${!month.reconciled?'日明细合计与接口月总量不一致；此图仅表示日明细累积。':''}`;
  }
  const books=month.books.slice(0,5),maxBook=Math.max(1,...books.map(b=>b.seconds));
  $('books').innerHTML=books.length?books.map((book,i)=>`<div class="book"><span class="book-index">0${i+1}</span><div class="book-body"><div class="book-title" title="${escape(book.title)}">${escape(book.title)}</div><p class="book-meta" title="${escape(book.author)}">${escape(book.author)}</p><div class="book-track"><div class="book-fill" style="width:${100*book.seconds/maxBook}%"></div></div></div><span class="book-time">${escape(duration(book.seconds))}</span></div>`).join(''):'<div class="no-chart">该月暂无可展示的阅读内容排行。</div>';
}
function render(){
  const months=selectedMonths(),days=months.flatMap(m=>m.days),total=sum(months,'totalSeconds'),active=sum(months,'readDays');
  $('content').hidden=!months.length;$('empty').hidden=!!months.length;
  $('mode').textContent=snapshot.demo?'演示数据':'本地记录';
  if(!months.length)return;
  const first=days[0]?.date,last=days.at(-1)?.date;
  const warnings=months.filter(m=>!m.reconciled).length;
  $('status').className='';$('status').textContent=`${first} — ${last} · ${snapshot.demo?'虚构演示记录':'微信读书记录'}${warnings?' · 部分月份日明细缺失或与月总量不一致，请查看数据口径。':''}`;
  const cards=[['累计阅读',hours(total),'小时','包含阅读与收听'],['有效阅读',active,'天',`观察范围 ${days.length} 个自然日`],['自然日均',Math.round(total/Math.max(1,days.length)/60),'分钟','总时长 ÷ 已过去的自然日'],['有效日均',active?Math.round(total/active/60):'—','分钟','总时长 ÷ 有效阅读天数']];
  $('metrics').innerHTML=cards.map(([label,value,unit,note])=>`<div class="metric"><p class="metric-label">${label}</p><p class="metric-value">${value}<small>${unit}</small></p><p class="metric-note">${note}</p></div>`).join('');
  renderWeekly(days);renderCalendar(months);
  const selected=$('month').value;
  $('month').innerHTML=[...months].reverse().map(m=>`<option value="${m.month}">${m.month.replace('-',' 年 ')} 月</option>`).join('');
  if(months.some(m=>m.month===selected))$('month').value=selected;
  renderMonth();
  $('updated').textContent=`上次同步 ${snapshot.syncedAt.slice(0,16).replace('T',' ')} · UTC+8`;
  $('source').innerHTML=`<p>来源：${snapshot.demo?'本地生成的虚构演示记录':'微信读书 Agent API /readdata/detail，monthly 模式'}。所有日期按 Asia/Shanghai（UTC+8），原始时长单位为秒。</p><ul><li>顶部总时长为各月 totalReadTime 之和，包含阅读与收听；有效天数为 readDays 之和（单日满 60 秒）。</li><li>周趋势、每日热力图与累计曲线来自 readTimes。缺失日期保留为空；明细不完整时周柱仅展示已知部分，月累计曲线不绘制。</li><li>自然日均分母包含未阅读日，并截至数据最后一天；有效日均为总时长除以有效阅读天数，不是单次阅读时长。</li><li>“近 N 个月”包含当月，首月从 1 日开始；本月数据截至同步日。月度明细面板的选择不改变上方观察范围。</li><li>日明细与月总量核对：${warnings?`${warnings} 个月未完全对齐`:'当前范围全部对齐'}。同步失败时保留上次完整快照。</li></ul>`;
}
async function load(sync=false){
  $('sync').disabled=true;
  if(sync){$('status').className='';$('status').textContent='正在同步最近 12 个月，通常需要几秒钟；旧数据会保留到同步成功。';}
  try{
    const response=await fetch(sync?'/api/sync':'/api/dashboard',sync?{method:'POST',headers:{'X-WeRead-Client':'dashboard'}}:{});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'读取失败');snapshot=data;render();
    if(!data.months.length)$('status').textContent='尚未同步个人阅读记录。';
  }catch(error){$('status').textContent=error.message+' 已保留上次显示的数据。';$('status').className='error';}
  finally{$('sync').disabled=false;}
}
$('sync').addEventListener('click',()=>load(true));$('range').addEventListener('change',()=>snapshot?.months.length&&render());$('month').addEventListener('change',renderMonth);
$('export').addEventListener('click',()=>{
  const data={...snapshot,months:selectedMonths()},url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download=`weread-${data.months[0].month}-${data.months.at(-1).month}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
load();
