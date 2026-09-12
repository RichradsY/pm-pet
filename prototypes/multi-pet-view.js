(function () {
  'use strict';
  const root = document.getElementById('pm-pet-multi');
  const $ = selector => root.querySelector(selector);
  const scene = $('.mp-scene'), panel = $('.mp-panel'), roster = $('.mp-roster');
  const feedback = $('.mp-feedback'), demoSelect = $('.mp-demo-select');
  const storageKey = 'pm-pet-five-design-v1';
  const samples = [
    { id: 'signup', title: 'Signup flow', project: 'Workshop', labels: ['Agree the scope', 'Design the form', 'Connect the signup form', 'Handle full capacity', 'Verify the signup flow'] },
    { id: 'pricing', title: 'Pricing page', project: 'Workshop', labels: ['Agree the pricing story', 'Design plan comparison', 'Build the pricing cards', 'Connect the checkout link', 'Check every plan'] },
    { id: 'research', title: 'User research', project: 'Research', labels: ['Choose the audience', 'Plan the interviews', 'Organize the findings', 'Review the evidence', 'Agree the next experiment'] },
    { id: 'portfolio', title: 'Portfolio', project: 'Personal', labels: ['Select the work', 'Design the story', 'Build the case studies', 'Connect the contact form', 'Check mobile layouts'] },
    { id: 'onboarding', title: 'Onboarding', project: 'Workshop', labels: ['Define the first success', 'Sketch the welcome flow', 'Build the first task', 'Add empty states', 'Check the full journey'] },
    { id: 'notes', title: 'Meeting notes', project: 'Personal', labels: ['Define the summary', 'Choose the note format', 'Build the capture flow', 'Connect action items', 'Verify the handoff'] }
  ].map((sample, index) => ({ ...sample, steps: sample.labels.map((label, n) => ({ id: sample.id + '-' + n, label, done: n < (index === 2 ? 1 : 2) })) }));
  let saved = null, storageAvailable = true;
  try { saved = JSON.parse(localStorage.getItem(storageKey)); } catch (_) { storageAvailable = false; }
  if (!saved || saved.version !== 1 || !Array.isArray(saved.pets)) saved = null;
  const store = PMPetModel.createStore({ saved, sampleConversations: samples });
  if (!saved) samples.slice(0, 5).forEach(sample => store.enable(sample.id));
  store.setQuota({ windows: { week: { remainingPercent: 82, windowDurationMins: 10080 } }, observedAt: 'Sample data' });
  const design = { language: saved && saved.ui && saved.ui.language === 'zh' ? 'zh' : 'en', quotaProfile: 'weekly' };
  const words = {
    en: { manage:'Manage pets', managerNote:'Up to 5 conversation pets. Account usage is shared.', arrange:'Arrange pets', desktop:'Your desktop', example:'Design preview · Sample conversations & usage', empty:'No pets enabled. Open Manage pets to bring one back.', roadmap:'View roadmap', decision:'Your decision', answer:'Answer in Codex ↗', settings:'Pet settings', showUsage:'Show account usage here', size:'Size', open:'Open in Codex ↗', disable:'Disable pet', enable:'Enable pet', usage:'Usage', try:'Try', advance:'Advance step', needs:'Needs you', received:'Answer received', chicks:'Subagents', help:'Drag an owl · Click for progress · Double-click to return', shared:'Shared account', sample:'Sample', weekly:'Weekly left', five:'5h left', unavailable:'Usage unavailable', allHidden:'Quota polling off · no visible usage', visibleSchedule:'Shared refresh: every 60s while quota is shown', capacity:'All 5 pet slots are in use. Disable one conversation pet before enabling another.', returned:'Preview only — return to Codex:', enabled:'Pet enabled:', disabled:'Pet disabled:', answered:'Demo answer received. This conversation can continue.', pending:'Waiting for a decision', done:'Ready to review', noLive:'Sample state only; no live agent was paused.', storage:'Preferences last for this preview only; browser storage is unavailable.', hideUsage:'Hide account usage', hidePanel:'Hide progress', phase:{building:'Building',planning:'Planning',checking:'Checking',waiting:'Needs your decision',idle:'Idle',complete:'Complete'} },
    zh: { manage:'管理 Pet', managerNote:'最多 5 只对话 Pet。额度是账户共享数据。', arrange:'整理位置', desktop:'你的桌面', example:'设计预览 · 示例对话与额度', empty:'还没有开启 Pet。可在“管理 Pet”中重新开启。', roadmap:'查看路线图', decision:'需要你决定', answer:'回到 Codex 回答 ↗', settings:'Pet 设置', showUsage:'在这里显示账户额度', size:'大小', open:'打开 Codex 对话 ↗', disable:'停用 Pet', enable:'启用 Pet', usage:'额度', try:'演示', advance:'推进一步', needs:'需要你', received:'已收到回答', chicks:'子 Agent', help:'拖动猫头鹰 · 单击看进度 · 双击回到对话', shared:'账户共享', sample:'示例', weekly:'本周剩余', five:'5h 剩余', unavailable:'额度暂不可用', allHidden:'没有显示额度 · 停止轮询', visibleSchedule:'显示额度时共享刷新：每 60 秒', capacity:'5 个 Pet 名额已用完。请先停用一只，再启用其他对话。', returned:'仅作预览 — 回到 Codex：', enabled:'已启用 Pet：', disabled:'已停用 Pet：', answered:'已收到演示回答，此对话可以继续。', pending:'等待你的决定', done:'可以查看成果了', noLive:'仅演示状态，没有暂停真实 Agent。', storage:'浏览器储存不可用，设置仅在本次预览中保留。', hideUsage:'隐藏账户额度', hidePanel:'隐藏进度框', phase:{building:'构建中',planning:'规划中',checking:'验证中',waiting:'等待你决定',idle:'空闲',complete:'已完成'} }
  };
  const t = () => words[design.language];
  const units = new Map(), ui = new Map();
  let openId = store.list({enabledOnly:true}).find(pet => pet.panelOpen)?.id || null;
  let demoId = store.list({enabledOnly:true})[0]?.id || samples[0].id;
  let rendering = false;
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');

  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify({ ...store.toJSON(), ui: { language: design.language } })); }
    catch (_) { storageAvailable = false; }
  }
  function announce(message) { feedback.textContent = message; }
  function el(tag, className, text) {
    const node = document.createElement(tag); if (className) node.className = className;
    if (text !== undefined) node.textContent = text; return node;
  }
  function runtime(id) {
    if (!ui.has(id)) ui.set(id, { unread:false, magic:null, click:null, children:[], timers:[], suppressedUntil:0 });
    return ui.get(id);
  }
  function error(result) {
    if (result.ok) return false;
    $('.mp-error').textContent = result.error === 'capacity' ? t().capacity : result.error;
    $('.mp-error').hidden = false; return true;
  }
  function clearError() { $('.mp-error').hidden = true; }
  function toggleEnabled(id) {
    clearError(); const pet = store.get(id);
    if (pet.enabled) {
      store.disable(id); store.setPanelOpen(id,false); stopAnimations(id); if (openId === id) openId = null;
      announce(t().disabled + ' ' + pet.title);
    } else {
      if (error(store.enable(id))) return;
      announce(t().enabled + ' ' + pet.title);
    }
    render(); save();
    if (!pet.enabled) units.get(id)?.querySelector('.pp-pet').focus({preventScroll:true});
  }
  function showPanel(id, toggle = true) {
    const next = toggle && openId === id ? null : id;
    store.list().forEach(pet => store.setPanelOpen(pet.id, pet.id === next));
    openId = next;
    if (next) { runtime(next).unread = false; demoId = next; }
    $('.pp-road').open = false; $('.pp-settings').open = false;
    render(); save();
    if(next) $('.pp-close').focus({preventScroll:true});
    else if(id) units.get(id)?.querySelector('.pp-pet').focus({preventScroll:true});
  }
  function returnToChat(id) { announce(t().returned + ' ' + store.get(id).title + ' · ' + store.get(id).project); }
  function setQuota(id, visible) { store.setQuotaVisible(id, visible); render(); save(); }

  function createUnit(pet) {
    const unit = el('div', 'mp-pet-unit'); unit.dataset.petId = pet.id;
    unit.append($('.mp-owl-template').content.cloneNode(true));
    const name = el('button', 'mp-name'); name.type = 'button';
    name.append(el('span', 'mp-letter', String.fromCharCode(65 + samples.findIndex(s => s.id === pet.id))), el('span', 'mp-name-text', pet.title));
    const quota = el('div', 'mp-quota'); quota.setAttribute('aria-label', 'Shared account usage');
    const signal = el('button', 'mp-signal'); signal.type = 'button'; signal.hidden = true;
    const dot = el('span', 'mp-dot'); dot.hidden = true; dot.setAttribute('aria-hidden', 'true');
    unit.append(name, quota, signal, dot); scene.append(unit); units.set(pet.id, unit);
    name.addEventListener('click', () => showPanel(pet.id));
    signal.addEventListener('click', () => showPanel(pet.id, false));
    const owl = unit.querySelector('.pp-pet');
    owl.removeAttribute('aria-label');
    owl.addEventListener('click', event => {
      const rt = runtime(pet.id); if (Date.now() < rt.suppressedUntil) return;
      clearTimeout(rt.click);
      if (event.detail === 0) { showPanel(pet.id); return; }
      if (event.detail === 1) rt.click = setTimeout(() => showPanel(pet.id), 240);
    });
    owl.addEventListener('dblclick', () => { clearTimeout(runtime(pet.id).click); returnToChat(pet.id); });
    let drag = null;
    owl.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      drag = { x:event.clientX, y:event.clientY, left:parseFloat(unit.style.left), top:parseFloat(unit.style.top), moved:false };
      owl.setPointerCapture(event.pointerId);
    });
    owl.addEventListener('pointermove', event => {
      if (!drag) return;
      const dx = event.clientX-drag.x, dy = event.clientY-drag.y;
      if (!drag.moved && Math.hypot(dx,dy)<5) return;
      drag.moved = true; owl.classList.add('pp-dragging');
      store.setPosition(pet.id, {x:drag.left+dx,y:drag.top+dy}); place();
    });
    function endDrag(event) {
      if (!drag) return;
      if (drag.moved) { runtime(pet.id).suppressedUntil = Date.now()+400; clearTimeout(runtime(pet.id).click); store.setPosition(pet.id,{x:parseFloat(unit.style.left),y:parseFloat(unit.style.top)}); save(); }
      drag = null; owl.classList.remove('pp-dragging');
      if (owl.hasPointerCapture(event.pointerId)) owl.releasePointerCapture(event.pointerId);
    }
    owl.addEventListener('pointerup', endDrag); owl.addEventListener('pointercancel', endDrag);
    return unit;
  }
  function renderQuota(pet, unit) {
    const quota = unit.querySelector('.mp-quota'); quota.hidden = !pet.quotaVisible;
    quota.replaceChildren(); if (!pet.quotaVisible) return;
    const row = el('div', 'pp-usage-row');
    const windows = store.getQuota().windows;
    for (const key of ['five','week']) {
      if (!windows[key]) continue;
      const percent = Math.round(windows[key].remainingPercent);
      const pill = el('span','pp-usage-pill'); pill.dataset.window = key;
      pill.dataset.tone = percent<=20 ? 'low' : percent<70 ? 'mid' : 'high';
      pill.append(el('span','',t()[key==='five'?'five':'weekly']),el('strong','',percent+'%')); row.append(pill);
    }
    if (!row.children.length) row.append(el('span','pp-unavailable',t().unavailable));
    const caption = el('span','mp-quota-caption',t().shared+' · ');
    const hide = el('button','pp-window-hide','×'); hide.type='button'; hide.setAttribute('aria-label',t().hideUsage+' — '+pet.title);
    hide.addEventListener('click', () => setQuota(pet.id, false)); caption.append(hide);
    quota.append(row,caption);
  }
  function activity(pet) {
    if (pet.phase === 'waiting') return 'attention';
    if (runtime(pet.id).magic) return 'magic';
    return pet.phase === 'building' ? 'reading' : pet.phase;
  }
  function renderPanel() {
    const pet = openId && store.get(openId);
    panel.hidden = !pet || !pet.enabled; if (panel.hidden) return;
    panel.dataset.theme = pet.theme; panel.dataset.waiting = String(pet.phase==='waiting');
    panel.setAttribute('aria-label',pet.title+' — '+t().roadmap);
    $('.mp-panel-name').textContent = pet.title; $('.mp-status').textContent = pet.project+' · '+t().phase[pet.phase];
    const current = pet.steps.find(step=>!step.done), progress = store.progress(pet.id);
    $('.pp-title').textContent = pet.question ? t().pending : current ? current.label : t().done;
    $('.mp-count').textContent = design.language==='zh' ? progress.done+' / '+progress.total+' 项完成' : progress.done+' of '+progress.total+' steps done';
    $('.mp-percent').textContent = progress.percent+'%';
    $('.pp-progress-fill').style.width = progress.percent+'%';
    $('.pp-progress-track').setAttribute('aria-valuenow',String(progress.percent));
    const list=$('.pp-road ol'); list.replaceChildren();
    pet.steps.forEach(step=>{
      const li=el('li','pp-step'); li.dataset.status=step.done?'done':current&&step.id===current.id?(pet.question?'blocked':'current'):'pending';
      li.append(el('span','pp-step-mark',step.done?'✓':li.dataset.status==='blocked'?'!':li.dataset.status==='current'?'●':'○'),el('span','',step.label)); list.append(li);
    });
    $('.pp-question').hidden=!pet.question; $('.pp-question p').textContent=pet.question ? pet.question.text : '';
    $('.mp-quota-toggle').checked=pet.quotaVisible; $('.mp-size').value=pet.size; $('.mp-scale output').textContent=pet.size+'%';
    $('.pp-close').setAttribute('aria-label',t().hidePanel);
  }
  function renderRoster() {
    const focus=document.activeElement, focusRow=focus?.closest('.mp-roster-row');
    const focusId=focusRow?.dataset.rosterId, focusKind=focus?.tagName;
    roster.replaceChildren();
    store.list().forEach(pet=>{
      const row=el('div','mp-roster-row'); row.dataset.rosterId=pet.id; row.dataset.theme=pet.theme;
      const name=el('span','mp-roster-name'); name.append(el('i','mp-swatch'),el('span','mp-roster-title',pet.title));
      const label=el('label','mp-switch'); const input=el('input'); input.type='checkbox'; input.checked=pet.quotaVisible; input.disabled=!pet.enabled;
      input.setAttribute('aria-label',t().showUsage+' — '+pet.title); input.addEventListener('change',()=>setQuota(pet.id,input.checked));
      label.append(input,el('span','',t().usage));
      const button=el('button','mp-button',pet.enabled?t().disable:t().enable); button.type='button';
      button.setAttribute('aria-label',(pet.enabled?t().disable:t().enable)+' — '+pet.title);
      button.addEventListener('click',()=>toggleEnabled(pet.id)); row.append(name,label,button); roster.append(row);
    });
    const interval=store.pollIntervalMs(); $('.mp-schedule').textContent=interval===null?t().allHidden:t().visibleSchedule;
    $('.mp-schedule').style.fontSize='12px';
    if(focusId){
      const row=[...roster.children].find(node=>node.dataset.rosterId===focusId);
      const target=row?.querySelector(focusKind==='INPUT'?'input':'button');
      if(target&&!target.disabled)target.focus({preventScroll:true});
    }
  }
  function render() {
    if (rendering) return; rendering=true;
    root.querySelectorAll('[data-i18n]').forEach(node=>node.textContent=t()[node.dataset.i18n]);
    const enabled=store.list({enabledOnly:true});
    $('.mp-capacity').textContent=enabled.length+' / 5'; $('.mp-empty').hidden=enabled.length>0;
    for (const [id,unit] of units) if (!enabled.some(p=>p.id===id)) { unit.remove(); units.delete(id); }
    enabled.forEach(pet=>{
      const unit=units.get(pet.id)||createUnit(pet), rt=runtime(pet.id), owl=unit.querySelector('.pp-pet');
      unit.dataset.theme=pet.theme; owl.style.transform='scale('+pet.size/100+')';
      owl.dataset.activity=activity(pet); owl.classList.toggle('pp-waiting',pet.phase==='waiting');
      owl.classList.toggle('pp-planning',pet.phase==='planning'); owl.classList.toggle('pp-checking',pet.phase==='checking');
      owl.setAttribute('aria-label',pet.title+' — '+t().phase[pet.phase]+'. '+t().help);
      owl.setAttribute('aria-expanded',String(openId===pet.id));
      unit.querySelector('.mp-name').setAttribute('aria-label',pet.title+' — '+t().roadmap);
      unit.querySelector('.mp-signal').hidden=!pet.question; unit.querySelector('.mp-signal').textContent='! '+t().needs;
      unit.querySelector('.mp-dot').hidden=!rt.unread||!!pet.question;
      renderQuota(pet,unit);
    });
    if (!enabled.some(p=>p.id===demoId)) demoId=enabled[0]?.id||samples[0].id;
    demoSelect.replaceChildren(); enabled.forEach(pet=>{ const opt=el('option','',pet.title); opt.value=pet.id; demoSelect.append(opt); }); demoSelect.value=demoId;
    const demo=store.get(demoId), available=demo&&demo.enabled;
    demoSelect.disabled=!available;
    $('.mp-advance').disabled=!available||demo.phase==='waiting'||store.progress(demoId).done===store.progress(demoId).total;
    $('.mp-ask').disabled=!available||demo.phase==='waiting'; $('.mp-resolve').hidden=!available||demo.phase!=='waiting';
    $('.mp-chicks').disabled=!available||demo.phase==='waiting';
    renderPanel(); renderRoster(); rendering=false; place();
  }
  const clamp=(v,lo,hi)=>Math.max(lo,Math.min(v,Math.max(lo,hi)));
  function place() {
    const enabled=store.list({enabledOnly:true}), width=scene.clientWidth;
    if (!width) return;
    const panelHeight=panel.hidden?0:panel.offsetHeight;
    const largest=Math.max(1,...enabled.map(pet=>pet.size/100));
    const anyChildren=[...units.values()].some(unit=>[...unit.querySelectorAll('.pp-baby')].some(baby=>!baby.hidden));
    const cellWidth=Math.max(180,largest*(92+(anyChildren?70:0))+28);
    const columns=Math.max(1,Math.min(5,Math.floor(width/cellWidth))), rows=Math.ceil(enabled.length/columns);
    const rowHeight=Math.max(220,104*largest+130), topPadding=Math.max(280,panelHeight+34);
    const baseHeight=Math.max(440,topPadding+rowHeight*rows+12);
    let height=baseHeight;
    enabled.forEach((pet,index)=>{
      const unit=units.get(pet.id); if(!unit)return;
      const row=Math.floor(index/columns), col=index%columns, inRow=Math.min(columns,enabled.length-row*columns);
      const scale=pet.size/100, center=(col+.5)*width/inRow;
      const defaultY=topPadding+row*rowHeight;
      const minY=openId===pet.id&&!panel.hidden?panelHeight+34:76;
      const childrenVisible=[...unit.querySelectorAll('.pp-baby')].some(baby=>!baby.hidden);
      const leftMargin=childrenVisible?Math.max(48,70*scale+12):48;
      const left=clamp(pet.position?pet.position.x:center-46*scale,leftMargin, width-48-92*scale);
      const top=clamp(pet.position?pet.position.y:defaultY,minY,Math.max(baseHeight-104*scale-105,minY));
      height=Math.max(height,top+104*scale+110);
      unit.style.left=left+'px'; unit.style.top=top+'px';
      const name=unit.querySelector('.mp-name'); name.style.left=46*scale+'px'; name.style.top=104*scale+'px';
      const quota=unit.querySelector('.mp-quota'); quota.style.left=46*scale+'px'; quota.style.top=(104*scale+34)+'px';
      unit.querySelector('.mp-signal').style.left=46*scale+'px';
      if(openId===pet.id&&!panel.hidden){
        const panelLeft=clamp(left+46*scale-panel.offsetWidth/2,12,width-panel.offsetWidth-12);
        panel.style.left=panelLeft+'px'; panel.style.top=(top-panelHeight-18)+'px';
        panel.style.setProperty('--pp-tail-x',clamp(left+46*scale-panelLeft,20,panel.offsetWidth-20)+'px');
      }
    });
    scene.style.height=height+'px';
  }
  function stopAnimations(id) {
    const rt=runtime(id); clearTimeout(rt.magic); clearTimeout(rt.click); rt.magic=null;
    rt.timers.forEach(timer=>clearTimeout(timer.handle)); rt.timers=[]; rt.children=[];
  }
  function scheduleChild(id,fn,delay) {
    const rt=runtime(id), timer={fn,remaining:delay,due:Date.now()+delay,handle:null};
    timer.handle=setTimeout(()=>{rt.timers=rt.timers.filter(item=>item!==timer);if(store.get(id).enabled&&root.isConnected)fn();},delay); rt.timers.push(timer);
  }
  function pauseChildren(id) {
    const rt=runtime(id); rt.timers.forEach(timer=>{clearTimeout(timer.handle);timer.remaining=Math.max(0,timer.due-Date.now());timer.handle=null;});
  }
  function resumeChildren(id) {
    const rt=runtime(id), timers=rt.timers.slice(); rt.timers=[]; timers.forEach(timer=>scheduleChild(id,timer.fn,timer.remaining));
  }
  function previewChildren(id) {
    stopAnimations(id); render(); const unit=units.get(id), babies=[...unit.querySelectorAll('.pp-baby')];
    babies.forEach((baby,index)=>{
      baby.hidden=true; baby.dataset.phase='none';
      scheduleChild(id,()=>{baby.hidden=false;baby.dataset.phase=reducedMotion.matches?'working':'hatching';place();},index*500);
      scheduleChild(id,()=>{baby.dataset.phase='working';},index*500+900);
      scheduleChild(id,()=>{baby.dataset.phase='leaving';if(reducedMotion.matches)baby.hidden=true;},3400+index*900);
      scheduleChild(id,()=>{baby.hidden=true;baby.dataset.phase='none';place();},4500+index*900);
    });
    announce(t().sample+' · '+store.get(id).title+' · '+t().chicks);
  }
  $('.mp-manager').addEventListener('toggle',()=>{$('.mp-manager-body').hidden=!$('.mp-manager').open;});
  $('.pp-close').addEventListener('click',()=>showPanel(openId));
  $('.mp-quota-toggle').addEventListener('change',event=>{if(openId)setQuota(openId,event.target.checked);});
  $('.mp-size').addEventListener('input',event=>{if(openId){store.setSize(openId,Number(event.target.value));render();save();}});
  $('.mp-disable').addEventListener('click',()=>{if(openId)toggleEnabled(openId);});
  $('.mp-open-chat').addEventListener('click',()=>{if(openId)returnToChat(openId);});
  $('.pp-return').addEventListener('click',()=>{if(openId)returnToChat(openId);});
  $('.pp-settings').addEventListener('toggle',place); $('.pp-road').addEventListener('toggle',place);
  $('.mp-arrange').addEventListener('click',()=>{store.list().forEach(pet=>store.clearPosition(pet.id));place();save();});
  demoSelect.addEventListener('change',()=>{demoId=demoSelect.value;render();});
  $('.mp-advance').addEventListener('click',()=>{
    if(!store.advance(demoId).ok)return;
    const rt=runtime(demoId); clearTimeout(rt.magic); rt.unread=openId!==demoId;
    rt.magic=setTimeout(()=>{rt.magic=null;render();},1200);
    announce(store.get(demoId).title+' · '+store.progress(demoId).percent+'%'); render();save();
  });
  $('.mp-ask').addEventListener('click',()=>{
    const question=demoId==='signup'?'When all spots are taken, close registration or open a waitlist?':'Should the first version serve individuals or teams? This changes the main flow.';
    if(!store.ask(demoId,question).ok)return;
    clearTimeout(runtime(demoId).magic);runtime(demoId).magic=null;pauseChildren(demoId);
    showPanel(demoId,false); announce(t().noLive);save();
  });
  $('.mp-resolve').addEventListener('click',()=>{
    if(store.resolve(demoId,'Example answer received in Codex').ok){resumeChildren(demoId);announce(t().answered);render();save();}
  });
  $('.mp-chicks').addEventListener('click',()=>previewChildren(demoId));
  new ResizeObserver(place).observe(scene);
  new ResizeObserver(place).observe(panel);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&openId){const previous=openId;showPanel(openId);units.get(previous)?.querySelector('.pp-pet').focus();}});
  render();save();if(!storageAvailable)announce(t().storage);
  if(globalThis.Tweak){
    const tweak=new Tweak({container:root,onChange:()=>{
      const windows={week:{remainingPercent:82,windowDurationMins:10080}};
      if(design.quotaProfile==='dual')windows.five={remainingPercent:48,windowDurationMins:300};
      if(design.quotaProfile==='unavailable')delete windows.week;
      store.setQuota({windows,observedAt:'Sample data'});render();save();
    }});
    tweak.addSelect(design,'language',{label:'Interface language',options:[{label:'English',value:'en'},{label:'简体中文',value:'zh'}]});
    tweak.addSelect(design,'quotaProfile',{label:'Account windows',options:[{label:'Weekly only',value:'weekly'},{label:'5h and weekly',value:'dual'},{label:'Unavailable',value:'unavailable'}]});
  }
})();
