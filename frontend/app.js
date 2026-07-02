/* ═══════════════════════════════════════════════════════
   app.js – Binance Leverage Bot Dashboard Logic v2
   ═══════════════════════════════════════════════════════ */

// Dynamic backend configuration
let savedAPI = localStorage.getItem('backend_api');
if (savedAPI && savedAPI.includes("onrender.com") && savedAPI.includes(":8000")) {
  localStorage.removeItem('backend_api');
  savedAPI = null;
}
const urlParams = new URLSearchParams(window.location.search);
const apiParam = urlParams.get('api');

if (apiParam) {
  savedAPI = apiParam.replace(/\/$/, "");
  localStorage.setItem('backend_api', savedAPI);
  window.history.replaceState({}, document.title, window.location.pathname);
}

const DEFAULT_PROD_API = "https://binance-leverage-bot-backend.onrender.com";

let fallbackAPI = `http://${location.hostname}:8000`;
if (location.hostname.includes("vercel.app")) {
  fallbackAPI = DEFAULT_PROD_API;
} else if (location.hostname !== "localhost" && location.hostname !== "127.0.0.1" && !location.port) {
  fallbackAPI = location.origin;
}

const API = savedAPI || fallbackAPI;
const WS_URL = API.startsWith('https') 
  ? API.replace('https://', 'wss://') + '/ws/live'
  : API.replace('http://', 'ws://') + '/ws/live';

/* ── App State ──────────────────────────────────────── */
const S = {
  mode:     'SIGNAL_ONLY',
  leverage: 50,
  chart:    { sym: 'BTCUSDT', tf: '1m' },
  analyses: {},
  signals:  [],
  filter:   'ALL',
  soundOn:  true,
};

/* ══════════════════════════════════════════════════════
   AUDIO ENGINE
══════════════════════════════════════════════════════ */
let actx = null;
const ac = () => { if (!actx) actx = new (window.AudioContext||window.webkitAudioContext)(); return actx; };

function tone(freq, dur, type='sine', vol=0.25, delay=0) {
  if (!S.soundOn) return;
  try {
    const ctx = ac(), o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.type = type; o.frequency.value = freq;
    const t = ctx.currentTime + delay;
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.start(t); o.stop(t + dur);
  } catch(e) {}
}

const SFX = {
  long()      { [523,659,784].forEach((f,i)=>tone(f,.12,'sine',.28,i*.09)); },
  short()     { [784,659,523].forEach((f,i)=>tone(f,.12,'sine',.28,i*.09)); },
  highConf()  { [523,659,784,1047].forEach((f,i)=>tone(f,.12,'square',.22,i*.07)); },
  tpHit()     { [784,1047,1319,1568].forEach((f,i)=>tone(f,.1,'sine',.28,i*.055)); },
  slHit()     { tone(200,.35,'sawtooth',.3); tone(150,.35,'sawtooth',.3,.4); },
  tradeOpen() { tone(440,.08,'square',.2); tone(550,.12,'square',.2,.08); },
  cdTick(s)   { tone(s<=3?900:660,.05,'square',.14); },
  liqWarn()   { for(let i=0;i<5;i++) tone(880,.15,'square',.4,i*.22); },
};

/* ══════════════════════════════════════════════════════
   TOAST
══════════════════════════════════════════════════════ */
const icons = { long:'🟢', short:'🔴', info:'ℹ️', warn:'⚠️', win:'🎉', loss:'💥' };

function toast(title, msg, type='info', ms=4500) {
  const wrap = document.getElementById('toasts');
  const el   = document.createElement('div');
  el.className = `toast t-${type}`;
  el.innerHTML = `
    <div class="toast-ico">${icons[type]||'🔔'}</div>
    <div><div class="toast-ttl">${title}</div><div class="toast-msg">${msg}</div></div>`;
  wrap.prepend(el);
  setTimeout(()=>{ el.style.animation='toast-out .3s ease forwards'; setTimeout(()=>el.remove(),300); }, ms);
}

/* ══════════════════════════════════════════════════════
   FLASH + KONFETTI
══════════════════════════════════════════════════════ */
function flash(color) {
  const el = document.getElementById('flash');
  el.className = `flash ${color}`;
  el.style.opacity = '1';
  setTimeout(()=>el.style.opacity='0', 300);
}

function konfetti() {
  const cols = ['#10b981','#3b82f6','#f59e0b','#8b5cf6','#ef4444','#60a5fa','#34d399'];
  for(let i=0;i<70;i++) {
    const d = document.createElement('div');
    d.className = 'kf';
    d.style.cssText = `
      left:${Math.random()*100}vw; top:-12px;
      background:${cols[~~(Math.random()*cols.length)]};
      width:${7+Math.random()*7}px; height:${7+Math.random()*7}px;
      animation-duration:${1.5+Math.random()*2.5}s;
      animation-delay:${Math.random()*0.6}s;
    `;
    document.body.appendChild(d);
    setTimeout(()=>d.remove(), 5000);
  }
}

/* ══════════════════════════════════════════════════════
   FORMAT HELPERS
══════════════════════════════════════════════════════ */
const f = {
  price(v, sym) {
    if (v==null) return '–';
    const dec = sym?.includes('XRP') ? 5 : sym?.includes('ETH') ? 2 : 1;
    return '$' + Number(v).toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec});
  },
  pct(v) {
    if (v==null) return '–';
    return (v>=0?'+':'')+Number(v).toFixed(2)+'%';
  },
  fund(v) { return v==null ? '–' : (Number(v)*100).toFixed(4)+'%'; },
  t(iso)  { if(!iso) return '–'; const d=new Date(iso); return d.toLocaleTimeString('pl-PL',{hour:'2-digit',minute:'2-digit'}); },
};

const set = (id,v) => { const e=document.getElementById(id); if(e) e.textContent=v; };
const css = (id,k,v) => { const e=document.getElementById(id); if(e) e.style[k]=v; };

/* ══════════════════════════════════════════════════════
   CLOCK
══════════════════════════════════════════════════════ */
const clockEl = document.getElementById('clock');
setInterval(()=>{
  const n=new Date(); const u=new Date(n.getTime()+n.getTimezoneOffset()*60000);
  clockEl.textContent = u.toLocaleTimeString('pl-PL',{hour:'2-digit',minute:'2-digit',second:'2-digit'})+' UTC';
},1000);

/* ══════════════════════════════════════════════════════
   UPDATE ANALYSIS TILES & SCORE CARDS
══════════════════════════════════════════════════════ */
function applyAnalysis(a) {
  const sym = a.symbol;
  S.analyses[sym] = a;
  const dir   = a.direction;
  const score = a.score;
  const ind   = a.indicators || {};
  const hc    = a.confidence === 'HIGH';

  // Ticker chip
  const chip = document.getElementById(`chip-${sym}`);
  if(chip) {
    chip.textContent = hc ? `${dir} ★` : dir;
    chip.className   = `sig-chip ${dir.toLowerCase()}${hc?' hc':''}`;
  }
  set(`snum-${sym}`, score);

  // Score card
  const dirEl = document.getElementById(`scdir-${sym}`);
  if(dirEl) {
    dirEl.textContent = dir;
    dirEl.className   = `sc-dir ${dir.toLowerCase()}`;
  }
  set(`scbig-${sym}`, score);

  const bar = document.getElementById(`scbar-${sym}`);
  if(bar) {
    bar.style.width = score+'%';
    bar.className   = score>=80 ? 'sc-fill green' : dir==='SHORT' ? 'sc-fill red' : 'sc-fill blue';
  }

  set(`sctp-${sym}`,   f.price(a.tp_price, sym));
  set(`scsl-${sym}`,   f.price(a.sl_price, sym));
  set(`scrsi-${sym}`,  ind.rsi?.toFixed(1) ?? '–');
  set(`scfund-${sym}`, f.fund(a.funding_rate));
  set(`scema-${sym}`,  f.price(ind.ema_9, sym));
  set(`scatr-${sym}`,  a.atr?.toFixed(4) ?? '–');

  // Update chart indicator bar if current chart sym
  if(sym === S.chart.sym) updateIndBar(a);
}

function updateIndBar(a) {
  const ind = a.indicators || {};
  const rsi = ind.rsi ?? 50;
  set('ind-rsi', rsi.toFixed(1));
  css('ind-rsi-bar','width', rsi+'%');
  css('ind-rsi-bar','background',
    rsi>70 ? 'linear-gradient(90deg,#7f1d1d,#ef4444)' :
    rsi<30 ? 'linear-gradient(90deg,#065f46,#10b981)' :
             'linear-gradient(90deg,#1d4ed8,#60a5fa)');

  const macdH = ind.macd_hist ?? 0;
  const macdPct = Math.min(100, Math.abs(macdH)*1000+50);
  set('ind-macd', macdH.toFixed(5));
  css('ind-macd-bar','width', macdPct+'%');
  css('ind-macd-bar','background', macdH>=0
    ? 'linear-gradient(90deg,#065f46,#10b981)'
    : 'linear-gradient(90deg,#7f1d1d,#ef4444)');

  const bb = (ind.bb_pct ?? 0.5)*100;
  set('ind-bb', (bb/100).toFixed(3));
  css('ind-bb-bar','width', Math.min(100,bb)+'%');

  const volR = Math.min(200, (ind.volume_ratio ?? 1)*50);
  set('ind-vol', (ind.volume_ratio ?? 0).toFixed(2)+'x');
  css('ind-vol-bar','width', Math.min(100,volR)+'%');
}

/* ══════════════════════════════════════════════════════
   MARKET PRICES
══════════════════════════════════════════════════════ */
async function refreshPrices() {
  for(const sym of ['BTCUSDT','ETHUSDT','XRPUSDT']) {
    try {
      const d = await fetch(`${API}/api/market/${sym}`).then(r=>r.json());
      set(`price-${sym}`, f.price(d.price, sym));
      const chEl = document.getElementById(`chg-${sym}`);
      if(chEl) {
        chEl.textContent  = f.pct(d.change_24h);
        chEl.className    = `coin-chg ${d.change_24h>=0?'up':'down'}`;
      }
    } catch(e){}
  }
}

/* ══════════════════════════════════════════════════════
   STATS
══════════════════════════════════════════════════════ */
function applyStats(data) {
  const o  = data.overall  || {};
  const ps = data.per_symbol || {};

  set('wr-big',    o.winrate != null ? o.winrate+'%' : '–%');
  set('lv-wr',     o.winrate != null ? o.winrate+'%' : '–%');
  set('lv-sigs',   o.total   ?? '–');
  set('st-total',  o.total   ?? '–');
  set('st-wins',   o.wins    ?? '–');
  set('st-losses', o.losses  ?? '–');
  set('st-pf',     o.profit_factor ?? '–');
  set('st-aw',     o.avg_win_pct  != null ? '+'+o.avg_win_pct+'%' : '–');
  set('st-al',     o.avg_loss_pct != null ? '-'+o.avg_loss_pct+'%' : '–');
  set('st-rr',     o.avg_rr ?? '–');
  set('st-dd',     o.max_drawdown != null ? '-'+o.max_drawdown+'%' : '–');

  for(const sym of ['BTCUSDT','ETHUSDT','XRPUSDT']) {
    const wr = ps[sym]?.winrate ?? 0;
    set(`symwr-${sym}`, wr+'%');
    css(`symbar-${sym}`, 'width', wr+'%');
  }

  // Risk badge
  const risk = data.risk || {};
  const badge = document.getElementById('risk-badge');
  const rtxt  = document.getElementById('risk-text');
  if(badge && rtxt) {
    badge.className = `risk-badge ${risk.paused ? 'warn' : 'ok'}`;
    rtxt.textContent = risk.paused
      ? `⛔ ${risk.pause_reason}`
      : `Risk OK · ${risk.open_positions}/${risk.max_positions} pozycji`;
    badge.firstElementChild.textContent = risk.paused ? '⛔' : '✅';
  }
}

/* ══════════════════════════════════════════════════════
   POSITIONS
══════════════════════════════════════════════════════ */
function renderPositions(positions) {
  const list = document.getElementById('pos-list');
  if(!list) return;

  if(!positions.length) {
    list.innerHTML = '<div class="empty">Brak otwartych pozycji</div>';
    set('lv-pnl', '$0.00');
    set('ftr-pnl', '$0.00');
    return;
  }

  let totalPnl = 0;
  list.innerHTML = positions.map(p => {
    totalPnl += p.pnl_usdt || 0;
    const pos = p.pnl_usdt >= 0;
    return `
    <div class="pos-item ${p.direction.toLowerCase()}-p">
      <div class="pos-top">
        <span class="pos-sym">
          ${p.symbol.replace('USDT','')}
          <span class="pos-badge ${p.direction.toLowerCase()}">${p.direction} ${p.leverage}x</span>
        </span>
        <span class="pos-pnl ${pos?'pos':'neg'}">${pos?'+':''}$${(p.pnl_usdt||0).toFixed(2)}</span>
      </div>
      <div class="pos-meta">
        <span>Entry <span>${f.price(p.entry_price,p.symbol)}</span></span>
        <span>Mark  <span>${f.price(p.mark_price,p.symbol)}</span></span>
        <span>Qty   <span>${p.quantity}</span></span>
        <span>Lev   <span>${p.leverage}x</span></span>
      </div>
      <div class="pos-liq-warn">⚠️ Liq: ${f.price(p.liquidation,p.symbol)}</div>
      <button class="btn btn-red btn-xs" onclick="closeSym('${p.symbol}')">Zamknij pozycję</button>
    </div>`;
  }).join('');

  const pnlStr = (totalPnl>=0?'+':'')+'$'+totalPnl.toFixed(2);
  const pnlCol = totalPnl>=0 ? 'var(--green-400)' : 'var(--red-400)';
  set('lv-pnl', pnlStr);   css('lv-pnl','color',pnlCol);
  set('ftr-pnl', pnlStr);  css('ftr-pnl','color',pnlCol);
}

/* ══════════════════════════════════════════════════════
   SIGNALS FEED
══════════════════════════════════════════════════════ */
let allSigs = [];

function renderSigs(sigs) {
  allSigs = sigs;
  filterSigs(S.filter);
}

function filterSigs(sym) {
  S.filter = sym;
  const feed = document.getElementById('sig-feed');
  if(!feed) return;
  const list = sym==='ALL' ? allSigs : allSigs.filter(s=>s.symbol===sym);
  if(!list.length) { feed.innerHTML='<div class="empty">Brak sygnałów</div>'; return; }

  feed.innerHTML = list.slice(0,50).map(s=>`
    <div class="sig-row ${s.direction.toLowerCase()}-row">
      <span class="sig-t">${f.t(s.created_at)}</span>
      <span class="sig-s">${s.symbol.replace('USDT','')}</span>
      <span class="sig-d ${s.direction.toLowerCase()}">${s.direction}</span>
      <span class="sig-sc" style="color:${s.score>=80?'var(--green-400)':s.score>=60?'var(--gold)':'var(--text-3)'}">${s.score}</span>
      <span class="sig-e">${f.price(s.entry_price,s.symbol)}</span>
      <span class="sig-tp">${f.price(s.tp_price,s.symbol)}</span>
      <span class="sig-sl">${f.price(s.sl_price,s.symbol)}</span>
      <span class="sig-st ${s.status.toLowerCase()}">${stLabel(s)}</span>
    </div>`).join('');
}

function stLabel(s) {
  if(s.status==='WIN')     return `✅ ${s.pnl_pct>=0?'+':''}${s.pnl_pct?.toFixed(1)}%`;
  if(s.status==='LOSS')    return `❌ ${s.pnl_pct?.toFixed(1)}%`;
  if(s.status==='PENDING') return '⏳ –';
  if(s.status==='EXPIRED') return '⌛ –';
  return s.status;
}

/* ══════════════════════════════════════════════════════
   WINRATE MINI CHART (Canvas)
══════════════════════════════════════════════════════ */
function drawWrChart(signals) {
  const canvas = document.getElementById('wr-chart');
  if(!canvas) return;
  const ctx = canvas.getContext('2d');
  const W   = canvas.offsetWidth; const H = canvas.height = 160;
  canvas.width = W;
  ctx.clearRect(0,0,W,H);

  const resolved = signals.filter(s=>s.status==='WIN'||s.status==='LOSS').slice(-30);
  if(resolved.length < 2) {
    ctx.fillStyle='rgba(148,163,184,0.3)';
    ctx.font='12px Inter'; ctx.textAlign='center';
    ctx.fillText('Oczekiwanie na sygnały…', W/2, H/2);
    return;
  }

  // Cumulative winrate points
  const pts = []; let wins=0;
  resolved.forEach((s,i)=>{ if(s.status==='WIN') wins++; pts.push({x:i,y:wins/(i+1)*100}); });

  const xS = W/(pts.length-1||1), pad=20;
  const gradient = ctx.createLinearGradient(0,0,0,H);
  gradient.addColorStop(0, 'rgba(59,130,246,0.4)');
  gradient.addColorStop(1, 'rgba(59,130,246,0)');

  // Fill
  ctx.beginPath();
  ctx.moveTo(0, H-pad);
  pts.forEach((p,i)=>ctx.lineTo(i*xS, H-pad-(p.y/100)*(H-pad*2)));
  ctx.lineTo((pts.length-1)*xS, H-pad);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  // Line
  ctx.beginPath();
  pts.forEach((p,i)=>{ const x=i*xS, y=H-pad-(p.y/100)*(H-pad*2); i?ctx.lineTo(x,y):ctx.moveTo(x,y); });
  ctx.strokeStyle='#3b82f6'; ctx.lineWidth=2; ctx.stroke();

  // 50% line
  const y50 = H-pad-(0.5)*(H-pad*2);
  ctx.setLineDash([4,4]);
  ctx.beginPath(); ctx.moveTo(0,y50); ctx.lineTo(W,y50);
  ctx.strokeStyle='rgba(245,158,11,0.4)'; ctx.lineWidth=1; ctx.stroke();
  ctx.setLineDash([]);

  // Dots
  pts.forEach((p,i)=>{
    const x=i*xS, y=H-pad-(p.y/100)*(H-pad*2);
    ctx.beginPath(); ctx.arc(x,y,3,0,Math.PI*2);
    ctx.fillStyle = p.y>=50 ? '#10b981' : '#ef4444';
    ctx.fill();
  });

  // Current WR label
  const last = pts[pts.length-1].y;
  ctx.fillStyle = last>=50?'#10b981':'#ef4444';
  ctx.font='bold 14px JetBrains Mono'; ctx.textAlign='right';
  ctx.fillText(last.toFixed(1)+'%', W-4, 18);
}

/* ══════════════════════════════════════════════════════
   CANDLESTICK CHART (Lightweight Charts)
══════════════════════════════════════════════════════ */
let lwChart = null, candleSeries = null, volSeries = null;

function initChart() {
  const container = document.getElementById('chart-container');
  lwChart = LightweightCharts.createChart(container, {
    layout: { background:{color:'transparent'}, textColor:'#475569' },
    grid:   { vertLines:{color:'rgba(59,130,246,0.06)'}, horzLines:{color:'rgba(59,130,246,0.06)'} },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor:'rgba(59,130,246,0.1)' },
    timeScale: { borderColor:'rgba(59,130,246,0.1)', timeVisible:true, secondsVisible:false },
    height: 370,
  });

  candleSeries = lwChart.addCandlestickSeries({
    upColor:'#10b981', downColor:'#ef4444',
    borderUpColor:'#10b981', borderDownColor:'#ef4444',
    wickUpColor:'#10b981', wickDownColor:'#ef4444',
  });

  lwChart.subscribeCrosshairMove(p=>{
    if(!p.time || !candleSeries) return;
    const d = p.seriesData.get(candleSeries);
    if(d) {
      set('o-o', d.open);   set('o-h', d.high);
      set('o-l', d.low);    set('o-c', d.close);
      css('o-c','color', d.close>=d.open ? 'var(--green-400)' : 'var(--red-400)');
    }
  });

  loadChart();
}

async function loadChart() {
  try {
    const klines = await fetch(`${API}/api/klines/${S.chart.sym}?interval=${S.chart.tf}&limit=200`).then(r=>r.json());
    const candles = klines.map(k=>({ time:Math.floor(k.open_time/1000), open:k.open, high:k.high, low:k.low, close:k.close }));
    candleSeries?.setData(candles);
    lwChart?.timeScale().fitContent();
  } catch(e){}
}

function switchSym(sym) {
  S.chart.sym = sym;
  ['BTCUSDT','ETHUSDT','XRPUSDT'].forEach(s=>{
    document.getElementById(`ctab-${s}`)?.classList.toggle('on', s===sym);
  });
  const a = S.analyses[sym];
  if(a) updateIndBar(a);
  loadChart();
}

function switchTf(tf) {
  S.chart.tf = tf;
  ['1m','5m','15m','1h','4h'].forEach(t=>{
    document.getElementById(`tf-${t}`)?.classList.toggle('on', t===tf);
  });
  loadChart();
}

/* ══════════════════════════════════════════════════════
   WEBSOCKET
══════════════════════════════════════════════════════ */
let ws=null, wsTimer=null;

function connectWS() {
  ws = new WebSocket(WS_URL);

  ws.onopen = ()=>{
    setStatus('live','🔗 Na żywo');
    clearTimeout(wsTimer);
  };
  ws.onmessage = ev=>{ try{ handleMsg(JSON.parse(ev.data)); }catch(e){} };
  ws.onclose   = ()=>{ setStatus('err','Rozłączono – ponawiam…'); wsTimer=setTimeout(connectWS,3000); };
  ws.onerror   = ()=>setStatus('err','Błąd połączenia');
}

function handleMsg(m) {
  switch(m.type) {
    case 'CONNECTED':
      (m.analyses||[]).forEach(applyAnalysis);
      S.mode=m.mode; S.leverage=m.leverage;
      refreshModeUI(); refreshLevUI();
      set('lv-last', f.t(m.last_update));
      set('ftr-last', f.t(m.last_update));
      if (m.ml_status) applyMLStatus(m.ml_status);
      if (m.wallet_balance !== undefined) {
        applyWalletData({ balance_usdt: m.wallet_balance });
      }
      break;

    case 'WALLET_UPDATE':
      applyWalletData(m.payload);
      renderWalletHistory();
      break;

    case 'MONITORING_START': {
      const p = m.payload;
      toast(
        `🔍 Monitorowanie ${p.direction} ${p.symbol.replace('USDT','')}`,
        `Wykryto silny score ${p.score}/100. Oczekiwanie na potwierdzenie świecy 15m...`,
        'blue', 7000
      );
      break;
    }

    case 'SIGNAL_EXPIRED': {
      const p = m.payload;
      toast(
        `❌ Anulowano trend ${p.symbol.replace('USDT','')}`,
        `Brak potwierdzenia kierunku ceny w 15m. Sygnał wygasł.`,
        'gray', 5000
      );
      fetchSigs();
      break;
    }

    case 'NEW_SIGNAL': {
      const a = m.payload;
      applyAnalysis(a);
      if(a.confidence==='HIGH') SFX.highConf();
      else if(a.direction==='LONG') SFX.long();
      else SFX.short();
      flash(a.direction==='LONG'?'green':'red');
      toast(
        `🎯 ${a.direction} ${a.symbol.replace('USDT','')} [${a.score}/100]`,
        `Entry ${f.price(a.entry_price,a.symbol)} · TP ${f.price(a.tp_price,a.symbol)} · SL ${f.price(a.sl_price,a.symbol)}`,
        a.direction.toLowerCase(), 7000
      );
      fetchSigs();
      break;
    }

    case 'STATS_UPDATE':
      applyStats(m.payload);
      break;

    case 'ML_STATUS_UPDATE':
      applyMLStatus(m.payload);
      break;

    case 'COUNTDOWN':
      showCD(m);
      break;

    case 'TRADE_OPENED':
      if(m.payload.success) {
        SFX.tradeOpen();
        toast('✅ Zlecenie otwarte', `${m.payload.symbol} ${m.payload.direction} @ ${f.price(m.payload.entry_price, m.payload.symbol)}`, 'info', 6000);
        fetchPos();
      } else {
        toast('❌ Błąd zlecenia', m.payload.error||'Nieznany błąd', 'warn');
      }
      break;

    case 'TRADE_CLOSED': fetchPos(); toast('📌 Pozycja zamknięta', m.payload.symbol||'', 'info'); break;
    case 'ALL_CLOSED':   fetchPos(); toast('⛔ Wszystkie pozycje zamknięte','','warn'); break;

    case 'SETTINGS_CHANGED':
      S.mode=m.mode; S.leverage=m.leverage;
      refreshModeUI(); refreshLevUI();
      break;
  }
}

function setStatus(cls, txt) {
  document.getElementById('sdot').className = `status-dot ${cls}`;
  document.getElementById('stext').textContent = txt;
}

/* ══════════════════════════════════════════════════════
   COUNTDOWN
══════════════════════════════════════════════════════ */
function showCD(data) {
  const ov = document.getElementById('cd-ov');
  set('cd-dir', data.signal.direction);
  document.getElementById('cd-dir').className = `cd-chip ${data.signal.direction}`;
  set('cd-sym', data.symbol);
  set('cd-num', data.seconds);
  ov.classList.remove('hidden');
  SFX.cdTick(data.seconds);
  if(data.seconds<=0) ov.classList.add('hidden');
}

document.getElementById('cd-cancel').onclick = async()=>{
  document.getElementById('cd-ov').classList.add('hidden');
  const sym = document.getElementById('cd-sym').textContent;
  await fetch(`${API}/api/trade/cancel_countdown`,{
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbol:sym})
  });
  toast('Zlecenie anulowane', sym, 'warn');
};

/* ══════════════════════════════════════════════════════
   CONFIRM MODAL
══════════════════════════════════════════════════════ */
let _confirmCb = null;
function confirm2(icon, title, body, cb, btnLabel='Potwierdź', btnCls='btn-red-solid') {
  set('modal-icon', icon); set('modal-ttl', title); set('modal-body', body);
  const yBtn = document.getElementById('modal-yes');
  yBtn.className = `btn ${btnCls}`;
  yBtn.textContent = btnLabel;
  document.getElementById('modal-ov').classList.remove('hidden');
  _confirmCb = cb;
}
document.getElementById('modal-yes').onclick = async()=>{
  document.getElementById('modal-ov').classList.add('hidden');
  if(_confirmCb) await _confirmCb(); _confirmCb=null;
};
document.getElementById('modal-no').onclick = ()=>{
  document.getElementById('modal-ov').classList.add('hidden'); _confirmCb=null;
};

/* ══════════════════════════════════════════════════════
   SETTINGS – Swing Trade Edition
══════════════════════════════════════════════════════ */
function refreshModeUI() {
  const isAnalyze = S.mode === 'ANALYZE';
  const isTrade   = S.mode === 'ANALYZE_AND_TRADE';
  const btnA = document.getElementById('btn-analyze');
  const btnT = document.getElementById('btn-trade');
  if (btnA) btnA.className = `toggle-btn${isAnalyze ? ' active-signal' : ''}`;
  if (btnT) btnT.className = `toggle-btn${isTrade   ? ' active-auto'   : ''}`;
  set('ftr-mode', isAnalyze ? '🔍 Tylko Analiza' : '🔍💰 Analizuj + Obstawiaj');

  // Swing status bar - mode display
  const modeEl = document.getElementById('mode-display');
  if (modeEl) {
    modeEl.textContent = isAnalyze ? '🔍 Tylko Analiza' : '🔍💰 Obstawianie Włączone';
    modeEl.style.color = isTrade ? 'var(--green-400)' : 'var(--text-1)';
  }

  // Badge w navbarze
  const badge = document.getElementById('daily-trades-badge');
  if (badge) badge.style.display = isTrade ? 'flex' : 'none';
}

function refreshLevUI() {
  const colors = {10:'sel-blue', 25:'sel-green', 50:'sel-blue', 100:'sel-red'};
  [10,25,50,100].forEach(l=>{
    const btn = document.getElementById(`lev${l}`);
    if(!btn) return;
    btn.className = `lev-btn${l===100?' danger':''}${S.leverage===l?' '+colors[l]:''}`;
  });
  set('ftr-lev', S.leverage+'x');
}

async function fetchDailyTrades() {
  try {
    const r = await fetch(`${API}/api/daily_trades`).then(r => r.json());
    S.dailyTrades = r.count;
    S.dailyLimit  = r.limit;
    updateDailyTradesUI(r.count, r.limit);
  } catch (e) {}
}

function updateDailyTradesUI(count, limit) {
  // Navbar badge
  const cnt = document.getElementById('daily-trades-count');
  const lim = document.getElementById('daily-trades-limit');
  if (cnt) cnt.textContent = count;
  if (lim) lim.textContent = limit;

  // Status bar
  const sbC = document.getElementById('sb-daily-count');
  const sbL = document.getElementById('sb-daily-limit');
  if (sbC) {
    sbC.textContent = count;
    sbC.style.color = count >= limit ? 'var(--red-400)' : 'var(--green-400)';
  }
  if (sbL) sbL.textContent = limit;

  // Wallet panel
  const wC = document.getElementById('wallet-daily-count');
  if (wC) wC.textContent = count;
  const bar = document.getElementById('daily-progress-bar');
  if (bar) bar.style.width = `${Math.min(100, (count / limit) * 100)}%`;
}

function updatePositionDisplay(val) {
  val = parseFloat(val);
  const posEl = document.getElementById('pos-val-display');
  if (posEl) posEl.textContent = `$${val} USDT`;

  // Przelicz TP/SL preview (10x dźwignia)
  const tpUSDT = (val * 2.5).toFixed(0);  // +250% na pozycji
  const slUSDT = (val * 0.8).toFixed(0);  // -80% na pozycji
  const tpEl = document.getElementById('tp-preview');
  const slEl = document.getElementById('sl-preview');
  if (tpEl) tpEl.textContent = `+$${tpUSDT} (+250%)`;
  if (slEl) slEl.textContent = `-$${slUSDT} (-80%)`;

  // Status bar
  const sbPos = document.getElementById('sb-position');
  if (sbPos) sbPos.textContent = `$${val} USDT`;
}

async function savePositionSize(val) {
  val = parseFloat(val);
  try {
    await fetch(`${API}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ position_usdt: val })
    });
    S.positionUsdt = val;
    updatePositionDisplay(val);
    toast('💰 Pozycja', `Ustawiono $${val} USDT`, 'blue', 2000);
  } catch (e) {}
}

async function setMode(mode) {
  try {
    const res = await fetch(`${API}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    }).then(r => r.json());
    S.mode = res.mode || mode;
    refreshModeUI();
    const label = mode === 'ANALYZE' ? '🔍 Tylko Analiza aktywna' : '🔍💰 Tryb obstawiania włączony';
    toast('Tryb zmieniony', label, mode === 'ANALYZE' ? 'info' : 'green', 3000);
    if (mode === 'ANALYZE_AND_TRADE') fetchDailyTrades();
  } catch (e) {
    toast('Błąd', 'Nie udało się zmienić trybu', 'warn');
  }
}

function confirmAutoTrade() {
  confirm2('🔍💰', 'Włączyć Obstawianie?',
    'Bot będzie automatycznie zapisywać transakcje (2-3 dziennie) przy wykryciu sygnału.\n\nPozycje $30–$100 z celem TP +250% i SL -80% na pozycję.\n\nDzienne limity są aktywne – max 3 trade/dzień.',
    () => setMode('ANALYZE_AND_TRADE'), 'Włącz', 'btn-green'
  );
}

async function setLev(lev) {
  const apply = async()=>{
    const res = await fetch(`${API}/api/settings`,{
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({leverage:lev})
    }).then(r=>r.json());
    S.leverage = res.leverage; refreshLevUI();
    toast('Dźwignia', `Ustawiono ${lev}x`, 'info', 2000);
  };
  if(lev>=100) {
    confirm2('⚠️',`Dźwignia ${lev}x`,
      `EKSTREMALNIE WYSOKIE RYZYKO!\nRuch ceny o 1% = likwidacja całego kapitału.\n\nCzy na pewno chcesz ustawić ${lev}x?`,
      apply, `Tak, ${lev}x`, 'btn-red-solid'
    );
  } else { await apply(); }
}

/* ══════════════════════════════════════════════════════
   TRADE ACTIONS
══════════════════════════════════════════════════════ */
function manualTrade(sym, dir) {
  const a = S.analyses[sym];
  confirm2(
    dir==='LONG'?'🟢':'🔴',
    `Otwórz ${dir} ${sym.replace('USDT','')}?`,
    `Entry: ${f.price(a?.entry_price,sym)}\nTP:    ${f.price(a?.tp_price,sym)}\nSL:    ${f.price(a?.sl_price,sym)}\nDźwignia: ${S.leverage}x`,
    async()=>{
      const r = await fetch(`${API}/api/trade`,{
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({symbol:sym, direction:dir, leverage:S.leverage})
      }).then(r=>r.json());
      if(r.success) { SFX.tradeOpen(); toast('✅ Złożono','Zlecenie otwarte','info'); fetchPos(); }
      else toast('❌ Błąd', r.error||'', 'warn');
    },
    `▲ ${dir}`, dir==='LONG'?'btn-green':'btn-red-solid'
  );
}

async function closeSym(sym) {
  confirm2('📌','Zamknąć pozycję?',`${sym.replace('USDT','')} – zlecenie MARKET natychmiast.`,
    async()=>{
      await fetch(`${API}/api/trade/close`,{
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbol:sym})
      });
      fetchPos();
    }, 'Zamknij', 'btn-red-solid'
  );
}

function confirmCloseAll() {
  confirm2('⛔','Zamknąć WSZYSTKIE?','Wszystkie otwarte pozycje zostaną zamknięte natychmiast zleceniem MARKET.',
    async()=>{ await fetch(`${API}/api/trade/close_all`,{method:'POST'}); fetchPos(); },
    'Zamknij wszystko', 'btn-red-solid'
  );
}

async function triggerNow() {
  await fetch(`${API}/api/analyze_now`,{method:'POST'});
  toast('🔄 Analiza','Uruchomiono natychmiast…','info',2000);
}

/* ══════════════════════════════════════════════════════
   API FETCHES
══════════════════════════════════════════════════════ */
async function fetchSigs() {
  try {
    const d = await fetch(`${API}/api/signals?limit=50`).then(r=>r.json());
    renderSigs(d); drawWrChart(d);
    renderWalletHistory();
  } catch(e){}
}

async function fetchPos() {
  try { renderPositions(await fetch(`${API}/api/positions`).then(r=>r.json())); }
  catch(e){}
}

async function fetchStats() {
  try { applyStats(await fetch(`${API}/api/stats`).then(r=>r.json())); }
  catch(e){}
}

async function fetchBal() {
  try {
    const d = await fetch(`${API}/api/balance`).then(r=>r.json());
    const u = d.find?.(b=>b.asset==='USDT');
    if(u) {
      const v = '$'+Number(u.availableBalance||u.balance||0).toFixed(2);
      set('lv-balance', v); set('ftr-bal', v);
    }
  } catch(e){}
}

/* ══════════════════════════════════════════════════════
   INIT
══════════════════════════════════════════════════════ */
async function init() {
  initChart();
  connectWS();

  // Pobierz ustawienia z backendu (tryb, pozycja)
  try {
    const settings = await fetch(`${API}/api/settings`).then(r => r.json());
    S.mode         = settings.mode         || 'ANALYZE';
    S.positionUsdt = settings.position_usdt || 50;
    S.leverage     = settings.leverage     || 10;
    // Inicjalizuj slider pozycji
    const slider = document.getElementById('position-slider');
    if (slider) { slider.value = S.positionUsdt; updatePositionDisplay(S.positionUsdt); }
    // Status bar
    const sbLev = document.getElementById('sb-leverage');
    if (sbLev) sbLev.textContent = `${S.leverage}x`;
    const tpPct = settings.swing_tp_pct  || 25;
    const slPct = settings.swing_sl_pct  || 8;
    const sbTp = document.getElementById('sb-tp');
    const sbSl = document.getElementById('sb-sl');
    if (sbTp) sbTp.textContent = `+${tpPct * S.leverage}%`;
    if (sbSl) sbSl.textContent = `-${slPct * S.leverage}%`;
    // Limit dzienny
    const sbDL = document.getElementById('sb-daily-limit');
    if (sbDL) sbDL.textContent = settings.max_daily_trades || 3;
  } catch (e) { S.mode = 'ANALYZE'; }

  refreshModeUI();
  refreshLevUI();
  await fetchDailyTrades();

  // Zmiana adresu API po kliknięciu w status pill
  const pill = document.querySelector('.status-pill');
  if (pill) {
    pill.style.cursor = 'pointer';
    pill.title = 'Kliknij, aby zmienić adres API backendu';
    pill.onclick = () => {
      const newApi = prompt('Wpisz nowy adres URL swojego backendu Render (np. https://xxx.onrender.com):', API);
      if (newApi !== null) {
        const val = newApi.trim().replace(/\/$/, "");
        if (val) {
          localStorage.setItem('backend_api', val);
        } else {
          localStorage.removeItem('backend_api');
        }
        window.location.reload();
      }
    };
  }

  await Promise.allSettled([fetchSigs(), fetchStats(), fetchBal(), fetchPos(), refreshPrices(), fetchMLStatus()]);

  // Polling intervals
  setInterval(()=>Promise.allSettled([fetchPos(), fetchStats()]), 30_000);
  setInterval(refreshPrices, 15_000);
  setInterval(fetchSigs,     30_000);
  setInterval(fetchBal,      60_000);
  setInterval(loadChart,     60_000);
  setInterval(fetchDailyTrades, 300_000); // Co 5 minut odśwież dzienny licznik
}


/* ══════════════════════════════════════════════════════
   VIEW SWITCHER & ML VIEW LOGIC
══════════════════════════════════════════════════════ */
function switchView(view) {
  document.getElementById('view-dashboard').classList.toggle('hidden', view !== 'dashboard');
  document.getElementById('view-ml').classList.toggle('hidden', view !== 'ml');
  document.getElementById('view-wallet').classList.toggle('hidden', view !== 'wallet');
  
  document.getElementById('nav-dashboard').classList.toggle('active-signal', view === 'dashboard');
  document.getElementById('nav-ml').classList.toggle('active-signal', view === 'ml');
  document.getElementById('nav-wallet').classList.toggle('active-signal', view === 'wallet');
  
  if (view === 'ml') {
    fetchMLStatus();
  } else if (view === 'wallet') {
    fetchWalletData();
  }
}

async function fetchWalletData() {
  try {
    const data = await fetch(`${API}/api/wallet`).then(r => r.json());
    applyWalletData(data);
    renderWalletHistory();
  } catch (e) {}
}

function applyWalletData(data) {
  if (!data) return;
  const bal = Number(data.balance_usdt || 1000).toFixed(2);
  set('wallet-balance-val', '$' + bal);
  set('ftr-bal', '$' + bal);
}

async function quickDeposit(amount) {
  try {
    const res = await fetch(`${API}/api/wallet/deposit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount: amount })
    }).then(r => r.json());
    if (res.status === 'success') {
      applyWalletData(res);
      renderWalletHistory();
    }
  } catch (e) {}
}

async function manualDeposit() {
  const input = document.getElementById('deposit-amount-input');
  if (!input) return;
  const amount = parseFloat(input.value);
  if (!amount || amount <= 0) {
    alert('Podaj poprawną kwotę większą od 0.');
    return;
  }
  try {
    const res = await fetch(`${API}/api/wallet/deposit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount: amount })
    }).then(r => r.json());
    if (res.status === 'success') {
      applyWalletData(res);
      renderWalletHistory();
      input.value = '';
    }
  } catch (e) {}
}

async function resetWallet() {
  if (!confirm('Czy na pewno chcesz zresetować saldo do 1 000 USDT?')) return;
  try {
    const res = await fetch(`${API}/api/wallet/reset`, {
      method: 'POST',
    }).then(r => r.json());
    if (res.status === 'reset') {
      applyWalletData(res);
      renderWalletHistory();
      toast('🔄 Portfel zresetowany', 'Saldo ustawione na 1 000 USDT', 'blue', 3000);
    }
  } catch (e) {}
}

function renderWalletHistory() {
  const feed = document.getElementById('wallet-history-feed');
  if (!feed) return;
  
  // Pobierz skończone sygnały z globalnej tablicy allSigs
  const closedSignals = (typeof allSigs !== 'undefined' ? allSigs : []).filter(s => s.status === 'WIN' || s.status === 'LOSS');
  
  if (closedSignals.length === 0) {
    feed.innerHTML = '<div class="empty">Brak historii transakcji...</div>';
    return;
  }
  
  // Posortuj od najnowszych
  closedSignals.sort((a,b) => new Date(b.resolved_at || b.created_at) - new Date(a.resolved_at || a.created_at));
  
  feed.innerHTML = closedSignals.map(s => {
    // 100 USDT position size, calculate PnL in USDT
    const pnlUsdt = 100 * ((s.pnl_pct || 0) / 100);
    const sign = pnlUsdt >= 0 ? '+' : '';
    const col = pnlUsdt >= 0 ? 'var(--green-400)' : 'var(--red-400)';
    const bgCol = pnlUsdt >= 0 ? 'rgba(0,192,115,0.06)' : 'rgba(255,101,101,0.06)';
    const borderCol = pnlUsdt >= 0 ? 'rgba(0,192,115,0.12)' : 'rgba(255,101,101,0.12)';
    
    return `
      <div style="background: ${bgCol}; border: 1px solid ${borderCol}; border-radius: 8px; padding: 0.85rem; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div style="font-weight: 700; font-size: 0.8rem; color: var(--text-1); display: flex; align-items: center; gap: 6px;">
            <span style="color: ${col}">${s.direction}</span> ${s.symbol.replace('USDT','')}
            <span style="font-size: 0.65rem; background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px; color: var(--text-3); font-weight: normal;">${s.leverage}x</span>
          </div>
          <div style="font-size: 0.65rem; color: var(--text-3); margin-top: 4px;">
            Wejście: ${s.entry_price.toFixed(2)} · Wyjście: ${(s.result_price || s.entry_price).toFixed(2)}
          </div>
        </div>
        <div style="text-align: right;">
          <div style="font-family: var(--mono); font-weight: 800; font-size: 0.95rem; color: ${col}">${sign}${pnlUsdt.toFixed(2)} USDT</div>
          <div style="font-size: 0.6rem; color: var(--text-3); margin-top: 2px;">${sign}${s.pnl_pct.toFixed(2)}% P&L</div>
        </div>
      </div>
    `;
  }).join('');
}

async function fetchMLStatus() {
  try {
    const res = await fetch(`${API}/api/ml/status`).then(r => r.json());
    applyMLStatus(res);
  } catch (e) {}
}

function applyMLStatus(ml) {
  if (!ml) return;
  set('ml-accuracy-val', (ml.accuracy || 50.0).toFixed(1) + '%');
  
  // Update footer info (since we display overall WR)
  set('lv-wr', (ml.accuracy || 50.0).toFixed(1) + '%');

  // 1. Render weights list
  const list = document.getElementById('ml-weights-list');
  if (list) {
    const w = ml.weights || {};
    const keys = {
      rsi: { name: 'RSI (Momentum)', col: '#3b82f6' },
      macd: { name: 'MACD (Trend Strength)', col: '#10b981' },
      bb: { name: 'Bollinger Bands (Volatility)', col: '#f59e0b' },
      vol: { name: 'Volume Ratio (Volume)', col: '#60a5fa' },
      funding: { name: 'Funding Rate (Sentiment)', col: '#ef4444' },
    };
    list.innerHTML = Object.keys(w).map(k => `
      <div class="sym-row" style="background: rgba(0,0,0,0.15)">
        <div class="sym-dot" style="background: ${keys[k]?.col || 'var(--text-3)'}"></div>
        <div class="sym-lbl">${keys[k]?.name || k.toUpperCase()}</div>
        <div class="sym-track">
          <div class="sym-fill" style="width: ${(w[k]/30)*100}%; background: ${keys[k]?.col || 'var(--blue-400)'}"></div>
        </div>
        <div class="sym-wr" style="font-family: var(--mono); color: var(--text-2); min-width: 45px; text-align: right;">${w[k]} pkt</div>
      </div>
    `).join('');
  }
  
  // 2. Draw weights chart (Canvas)
  drawWeightsChart(ml.weights);
  
  // 3. Draw accuracy history (Canvas)
  drawAccuracyChart(ml.history);
  
  // 4. Render logs
  const logsFeed = document.getElementById('ml-logs-feed');
  if (logsFeed) {
    const logs = ml.logs || [];
    if (!logs.length) {
      logsFeed.innerHTML = '<div class="empty">Model nie rozpoczął jeszcze uczenia...</div>';
    } else {
      logsFeed.innerHTML = logs.map(l => {
        let col = 'var(--text-2)';
        if (l.includes('Zwiększono')) col = 'var(--green-400)';
        if (l.includes('Zmniejszono')) col = 'var(--red-400)';
        return `<div style="padding: 0.55rem 0.75rem; background: rgba(0,0,0,0.15); border-radius: var(--r-sm); border: 1px solid var(--border); line-height: 1.4; color: ${col}; margin-bottom: 2px;">
          ${l}
        </div>`;
      }).join('');
    }
  }
}

function drawWeightsChart(weights) {
  const canvas = document.getElementById('ml-weights-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth; const H = canvas.height = 200;
  canvas.width = W;
  ctx.clearRect(0, 0, W, H);
  
  if (!weights) return;
  const keys = Object.keys(weights);
  const vals = Object.values(weights);
  
  const barW = Math.min(45, W / keys.length - 20);
  const padX = (W - (barW + 20) * keys.length) / 2 + 10;
  const padY = 25;
  
  const maxVal = Math.max(...vals, 1);
  
  keys.forEach((k, i) => {
    const v = weights[k];
    const barH = (v / maxVal) * (H - padY * 2);
    const x = padX + i * (barW + 20);
    const y = H - padY - barH;
    
    // Draw bar
    const grad = ctx.createLinearGradient(0, y, 0, H - padY);
    const color = k==='rsi'?'#3b82f6':k==='macd'?'#10b981':k==='bb'?'#f59e0b':k==='vol'?'#60a5fa':'#ef4444';
    grad.addColorStop(0, color);
    grad.addColorStop(1, 'rgba(0,0,0,0.3)');
    
    ctx.fillStyle = grad;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, barW, barH, 4);
    else ctx.rect(x, y, barW, barH);
    ctx.fill();
    
    // Draw value text
    ctx.fillStyle = '#f0f4ff';
    ctx.font = 'bold 10px JetBrains Mono'; ctx.textAlign = 'center';
    ctx.fillText(v + 'p', x + barW / 2, y - 6);
    
    // Draw label text
    ctx.fillStyle = '#94a3b8';
    ctx.font = '9px Inter';
    ctx.fillText(k.toUpperCase(), x + barW / 2, H - 8);
  });
}

function drawAccuracyChart(history) {
  const canvas = document.getElementById('ml-accuracy-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth; const H = canvas.height = 180;
  canvas.width = W;
  ctx.clearRect(0, 0, W, H);
  
  const pts = history || [0.5];
  if (pts.length < 2) {
    // Draw flat line at 50%
    ctx.strokeStyle = 'rgba(59,130,246,0.2)';
    ctx.setLineDash([4,4]);
    ctx.beginPath(); ctx.moveTo(0, H/2); ctx.lineTo(W, H/2); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(148,163,184,0.4)';
    ctx.font = '11px Inter'; ctx.textAlign = 'center';
    ctx.fillText('Epoka 1: 50.0% (Oczekiwanie na kolejne epoki uczenia)', W/2, H/2 - 10);
    return;
  }
  
  const xS = W / (pts.length - 1);
  const pad = 20;
  
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, 'rgba(16,185,129,0.25)');
  grad.addColorStop(1, 'rgba(16,185,129,0)');
  
  // Fill
  ctx.beginPath();
  ctx.moveTo(0, H - pad);
  pts.forEach((p, i) => ctx.lineTo(i * xS, H - pad - p * (H - pad * 2)));
  ctx.lineTo((pts.length - 1) * xS, H - pad);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();
  
  // Line
  ctx.beginPath();
  pts.forEach((p, i) => {
    const x = i * xS;
    const y = H - pad - p * (H - pad * 2);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = '#10b981'; ctx.lineWidth = 2; ctx.stroke();
  
  // Target line (50% random benchmark)
  ctx.setLineDash([3,3]);
  ctx.beginPath();
  ctx.moveTo(0, H - pad - 0.5 * (H - pad * 2));
  ctx.lineTo(W, H - pad - 0.5 * (H - pad * 2));
  ctx.strokeStyle = 'rgba(244,63,94,0.3)';
  ctx.stroke();
  ctx.setLineDash([]);
  
  // Dots
  pts.forEach((p, i) => {
    const x = i * xS;
    const y = H - pad - p * (H - pad * 2);
    ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fillStyle = p >= 0.5 ? '#10b981' : '#ef4444';
    ctx.fill();
  });
}

async function retrainMLNow() {
  toast('🧠 ML Uczenie', 'Rozpoczynam ręczne uczenie modelu...', 'info', 2000);
  try {
    const res = await fetch(`${API}/api/ml/train`, { method: 'POST' }).then(r => r.json());
    if (res.success) {
      SFX.tpHit();
      toast('🎉 Sukces uczenia', `Model uaktualniony! Dokładność: ${(res.accuracy*100).toFixed(1)}%`, 'win');
      fetchMLStatus();
    } else {
      toast('⚠️ Brak danych', res.reason || 'Błąd uczenia', 'warn');
    }
  } catch (e) {
    toast('❌ Błąd', 'Nie można połączyć się z silnikiem ML bota', 'warn');
  }
}

document.addEventListener('DOMContentLoaded', init);
