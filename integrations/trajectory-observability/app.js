const state = {data:null, mode:'replay', filter:'all', showPaths:true, playing:false, progress:1000, speed:1, currentMs:0, startMs:0, endMs:0, lastFrame:0};
let liveTimer = null;
let playbackFrame = null;
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));

async function loadData(mode = state.mode) {
  try {
    const response = await fetch(`/api/trajectory/${mode === 'live' ? 'live' : 'demo'}`, {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    setData(await response.json(), {jumpToEnd:mode === 'live'});
  } catch (error) {
    setConnection('error', `连接失败 · ${error.message}`);
  }
}

function setData(data, options = {}) {
  state.data = data;
  const times = Object.values(data.routes || {}).flat().map(pointTime).filter(Number.isFinite);
  const now = Date.now();
  state.startMs = Number(data.meta?.start_time) || (times.length ? Math.min(...times) : now);
  state.endMs = Number(data.meta?.end_time) || (times.length ? Math.max(...times) : state.startMs);
  if (state.endMs < state.startMs) [state.startMs, state.endMs] = [state.endMs, state.startMs];
  if (options.jumpToEnd) state.progress = 1000;
  state.currentMs = progressToTime(state.progress);
  render();
}

function render() {
  if (!state.data) return;
  const meta = state.data.meta || {};
  $('mapName').textContent = state.data.map?.name || 'RMF map';
  $('currentTime').textContent = formatClock(state.currentMs);
  $('endTime').textContent = formatClock(state.endMs);
  $('mapState').textContent = state.mode === 'live' ? `${meta.connected ? '实时状态' : '等待实时数据'} · ${formatAge(meta.age_ms)}` : `回放时间 · ${formatClock(state.currentMs)}`;
  $('timelineInput').value = Math.round(state.progress);
  renderConnection();
  renderMetrics();
  renderRobots();
  renderEvents();
  renderTasks();
  drawMap();
}

function renderConnection() {
  const meta = state.data.meta || {};
  if (state.mode !== 'live') return setConnection('demo', meta.source === 'import' ? '已载入历史数据' : '演示数据 · 时间戳回放');
  if (meta.connected) return setConnection('connected', `实时已连接 · ${meta.source || 'RMF adapter'}`);
  if (meta.source === 'demo-fallback') return setConnection('waiting', '等待首次 RMF 数据推送');
  setConnection('waiting', meta.message || '实时数据已延迟');
}

function setConnection(kind, label) {
  document.body.dataset.connection = kind;
  $('connectionLabel').textContent = label;
  $('integrationText').textContent = label;
}

function renderMetrics() {
  const meta = state.data.meta || {};
  const total = state.data.robots.length;
  const online = Number.isFinite(Number(meta.online_robots)) ? Number(meta.online_robots) : total;
  $('onlineCount').textContent = `${online} / ${total}`;
  $('onlineSummary').textContent = online === total ? '全部设备可见' : `${total - online} 台离线`;
  $('onlineSummary').className = online === total ? 'positive' : 'warning';
  $('taskCount').textContent = meta.running_tasks ?? 0;
  $('taskSummary').textContent = `窗口内共 ${meta.tasks ?? state.data.tasks.length} 个任务`;
  $('averageDelay').textContent = formatDuration(meta.average_delay_seconds || 0);
  $('delaySummary').textContent = '按任务样本动态计算';
  $('replanCount').textContent = meta.replans ?? 0;
  $('replanSummary').textContent = '按事件类型动态统计';
}

function renderRobots() {
  const robots = state.data.robots || [];
  document.querySelectorAll('.filter').forEach((button) => {
    const key = button.dataset.filter;
    button.querySelector('b').textContent = robots.filter((robot) => key === 'all' || robot.fleet === key || robot.status === key).length;
  });
  const visible = robots.filter((robot) => state.filter === 'all' || robot.fleet === state.filter || robot.status === state.filter);
  $('robotList').innerHTML = visible.map((robot) => `<div class="robot-row"><span class="robot-icon" style="background:${safeColor(robot.color)}">${escapeHtml(robot.name.slice(0, 2))}</span><div class="robot-info"><strong><i class="status-dot ${safeClass(robot.status)}"></i>${escapeHtml(robot.name)}</strong><small>${escapeHtml(robot.task)}</small></div><span class="robot-battery">${escapeHtml(robot.battery)}%</span></div>`).join('') || '<p class="empty">没有匹配的机器人</p>';
}

function renderEvents() {
  const events = (state.data.events || []).filter((event) => !event.timestamp || Number(event.timestamp) <= state.currentMs || state.mode === 'live').sort((a,b) => Number(b.timestamp || 0) - Number(a.timestamp || 0)).slice(0, 5);
  $('eventList').innerHTML = events.map((event) => `<div class="event-row ${safeClass(event.tone)}"><time>${escapeHtml(event.time || formatClock(event.timestamp))}</time><div><strong>${escapeHtml(event.type || '事件')} · ${escapeHtml(event.robot || 'RMF')}</strong><p>${escapeHtml(event.detail || '')}</p></div></div>`).join('') || '<p class="empty">当前时间前没有任务事件</p>';
}

function renderTasks() {
  const labels = {done:'已完成', running:'执行中', queued:'待开始', failed:'失败'};
  const tasks = state.data.tasks || [];
  $('taskTableBody').innerHTML = tasks.map((task) => `<tr><td><strong>${escapeHtml(task.id || '--')}</strong><span>${escapeHtml(task.name || 'RMF 任务')}</span></td><td>${escapeHtml(task.robot || '--')}</td><td>${escapeHtml(task.route || '--')}</td><td>${formatDuration(task.duration_seconds || 0)}</td><td><em class="status-chip ${safeClass(task.status)}">${escapeHtml(labels[task.status] || task.status || '未知')}</em></td></tr>`).join('') || '<tr><td colspan="5">当前数据没有任务明细</td></tr>';
}

function drawMap() {
  if (!state.data) return;
  const canvas = $('mapCanvas');
  const box = canvas.getBoundingClientRect();
  if (!box.width || !box.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(box.width * ratio);
  canvas.height = Math.round(box.height * ratio);
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  const sx = box.width / (Number(state.data.map?.width) || 100);
  const sy = box.height / (Number(state.data.map?.height) || 64);
  const point = (value) => [pointX(value) * sx, pointY(value) * sy];
  ctx.clearRect(0, 0, box.width, box.height);
  (state.data.zones || []).forEach((zone) => {
    const [x,y] = point(zone);
    ctx.fillStyle = {dock:'#d9ebe4',lift:'#dce8f8',charge:'#f8e9cc',people:'#f5dddd'}[zone.class] || '#e6ecea';
    ctx.fillRect(x,y,Number(zone.w)*sx,Number(zone.h)*sy);
    ctx.strokeStyle = '#bfd1cc'; ctx.strokeRect(x,y,Number(zone.w)*sx,Number(zone.h)*sy);
    ctx.fillStyle = '#60736e'; ctx.font = '10px sans-serif'; ctx.fillText(zone.name || '',x+7,y+16);
  });
  Object.entries(state.data.routes || {}).forEach(([id,route]) => {
    if (!state.showPaths || route.length < 2) return;
    const robot = state.data.robots.find((item) => item.id === id);
    ctx.beginPath();
    route.forEach((value,index) => { const [x,y] = point(value); index ? ctx.lineTo(x,y) : ctx.moveTo(x,y); });
    ctx.strokeStyle = `${safeColor(robot?.color)}88`; ctx.lineWidth = 2; ctx.setLineDash([5,4]); ctx.stroke(); ctx.setLineDash([]);
  });
  state.data.robots.forEach((robot,index) => {
    const position = positionAt(state.data.routes?.[robot.id] || [], state.currentMs);
    if (!position) return;
    const [x,y] = point(position);
    ctx.beginPath(); ctx.arc(x,y,9,0,Math.PI*2); ctx.fillStyle='#fff'; ctx.fill();
    ctx.lineWidth=3; ctx.strokeStyle=safeColor(robot.color); ctx.stroke();
    ctx.fillStyle=safeColor(robot.color); ctx.font='700 9px sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillText(String(index+1),x,y);
  });
}

function positionAt(route, timestamp) {
  if (!route.length) return null;
  if (timestamp <= pointTime(route[0])) return route[0];
  if (timestamp >= pointTime(route[route.length-1])) return route[route.length-1];
  let low=0, high=route.length-1;
  while (low+1 < high) { const middle=Math.floor((low+high)/2); if (pointTime(route[middle]) <= timestamp) low=middle; else high=middle; }
  const before=route[low], after=route[high], span=pointTime(after)-pointTime(before);
  const amount=span > 0 ? (timestamp-pointTime(before))/span : 0;
  return {x:pointX(before)+(pointX(after)-pointX(before))*amount, y:pointY(before)+(pointY(after)-pointY(before))*amount};
}

function pointX(point) { return Number(Array.isArray(point) ? point[0] : point.x) || 0; }
function pointY(point) { return Number(Array.isArray(point) ? point[1] : point.y) || 0; }
function pointTime(point) { return Number(Array.isArray(point) ? point[2] : point.t); }
function progressToTime(progress) { return state.startMs + (state.endMs-state.startMs)*(Number(progress)/1000); }
function formatClock(value) { return Number.isFinite(Number(value)) ? new Date(Number(value)).toISOString().slice(11,19) : '--:--:--'; }
function formatDuration(value) { const seconds=Math.max(0,Math.round(Number(value)||0)); return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`; }
function formatAge(value) { if (!Number.isFinite(Number(value))) return '等待首帧'; const seconds=Math.max(0,Math.round(Number(value)/1000)); return seconds < 2 ? '刚刚更新' : `${seconds} 秒前更新`; }
function safeClass(value) { return /^[a-z0-9_-]+$/i.test(String(value || '')) ? String(value) : ''; }
function safeColor(value) { return /^#[0-9a-f]{6}$/i.test(String(value || '')) ? String(value) : '#64748b'; }

function togglePlay() {
  state.playing=!state.playing; $('playButton').textContent=state.playing?'Ⅱ':'▶'; state.lastFrame=performance.now();
  if (state.playing) playbackFrame=requestAnimationFrame(tick); else cancelAnimationFrame(playbackFrame);
}
function tick(now) {
  if (!state.playing) return;
  const duration=Math.max(1,state.endMs-state.startMs), elapsed=Math.min(100,now-state.lastFrame); state.lastFrame=now;
  state.currentMs += elapsed*state.speed; if (state.currentMs >= state.endMs) state.currentMs=state.startMs;
  state.progress=((state.currentMs-state.startMs)/duration)*1000; render(); playbackFrame=requestAnimationFrame(tick);
}
function selectMode(mode) {
  state.mode=mode; state.playing=false; $('playButton').textContent='▶'; cancelAnimationFrame(playbackFrame);
  document.body.classList.toggle('live-mode',mode==='live');
  document.querySelectorAll('.mode-switch button').forEach((button) => button.classList.toggle('active',button.dataset.mode===mode));
  clearInterval(liveTimer); liveTimer=mode==='live'?setInterval(()=>loadData('live'),5000):null;
}

$('playButton').addEventListener('click',togglePlay);
$('timelineInput').addEventListener('input',(event)=>{state.progress=Number(event.target.value);state.currentMs=progressToTime(state.progress);render();});
$('togglePaths').addEventListener('click',()=>{state.showPaths=!state.showPaths;$('togglePaths').classList.toggle('active',state.showPaths);drawMap();});
$('fitButton').addEventListener('click',()=>{state.progress=1000;state.currentMs=state.endMs;render();});
$('speedButton').addEventListener('click',()=>{state.speed=state.speed===1?2:state.speed===2?0.5:1;$('speedButton').textContent=`${state.speed}×`;});
$('refreshButton').addEventListener('click',()=>loadData());
document.querySelectorAll('.mode-switch button').forEach((button)=>button.addEventListener('click',()=>{selectMode(button.dataset.mode);loadData(button.dataset.mode);}));
document.querySelectorAll('.filter').forEach((button)=>button.addEventListener('click',()=>{document.querySelectorAll('.filter').forEach((item)=>item.classList.remove('active'));button.classList.add('active');state.filter=button.dataset.filter;renderRobots();}));
$('importButton').addEventListener('click',()=>$('fileInput').click());
$('fileInput').addEventListener('change',async(event)=>{
  const file=event.target.files[0]; if (!file) return;
  try { const payload=JSON.parse(await file.text()); const response=await fetch('/api/trajectory/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const data=await response.json(); if(!response.ok)throw new Error(data.error||'数据格式不受支持'); selectMode('replay');state.progress=0;setData(data);setConnection('demo',`已导入 · ${file.name}`); }
  catch(error){window.alert(`导入失败：${error.message}`);} event.target.value='';
});
$('exportButton').addEventListener('click',()=>{
  if(!state.data)return; const meta=state.data.meta||{}; const text=`RMF 轨迹摘要\n地图：${state.data.map.name}\n机器人：${state.data.robots.length}\n执行中任务：${meta.running_tasks||0}\n平均时延：${formatDuration(meta.average_delay_seconds)}\n数据源：${meta.source||'unknown'}\n当前时间：${formatClock(state.currentMs)}`;
  const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([text],{type:'text/plain'}));link.download='rmf-trajectory-summary.txt';link.click();URL.revokeObjectURL(link.href);
});
$('copyContract').addEventListener('click',async()=>{const contract='POST /api/trajectory/live -> schema v1; GET /api/trajectory/live -> { map, robots, routes, zones, events, tasks, meta }';try{await navigator.clipboard.writeText(contract);$('integrationText').textContent='接口契约已复制';}catch{$('integrationText').textContent=contract;}});
window.addEventListener('resize',drawMap);
loadData();
