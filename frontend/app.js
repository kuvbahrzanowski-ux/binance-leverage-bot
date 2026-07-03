/* ══════════════════════════════════════════════════════
   LEVERAGEBOT 100X - CORE ENGINE SCRIPT
   Complete Fresh Javascript Implementation
   ══════════════════════════════════════════════════════ */

const API = window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1')
  ? 'http://localhost:8000'
  : 'https://binance-leverage-bot-backend.onrender.com'; // Fallback na produkcyjny URL API

const WS_URL = API.replace(/^http/, 'ws') + '/ws';

// Global state
const S = {
  symbol: 'BTCUSDT',
  tf: '15m',
  balance: 1000.0,
  signals: [],
  mode: 'ANALYZE', // ANALYZE | ANALYZE_AND_TRADE
  leverage: 100,
  dailyTrades: 0,
  dailyLimit: 15,
  ml: {
    accuracy: 75.0,
    history: [50, 60, 68, 75],
    logs: ["Inicjalizacja modelu regresji logistycznej..."]
  }
};

let tvWidget = null;
let ws = null;
let wsTimer = null;

// Audio alerts helper
const SFX = {
  win: () => { try { document.getElementById('sfx-win').play(); } catch(e){} },
  loss: () => { try { document.getElementById('sfx-loss').play(); } catch(e){} },
  new: () => { try { document.getElementById('sfx-new').play(); } catch(e){} }
};

// Start
document.addEventListener('DOMContentLoaded', () => {
  initChart();
  connectWS();
  fetchInitData();
});

/* ════════════════ TRADINGVIEW WIDGET ════════════════ */
function initChart() {
  if (typeof TradingView === 'undefined' || !TradingView.widget) {
    // Wait for TradingView script to load
    setTimeout(initChart, 100);
    return;
  }
  
  const container = document.getElementById('chart-container');
  if (!container) return;

  container.innerHTML = '';

  // Map interval to TradingView syntax
  let interval = "15";
  if (S.tf === '15m') interval = "15";
  else if (S.tf === '1h') interval = "60";
  else if (S.tf === '4h') interval = "240";

  const tvSymbol = `BINANCE:${S.symbol}`;

  try {
    tvWidget = new TradingView.widget({
      "autosize": true,
      "symbol": tvSymbol,
      "interval": interval,
      "timezone": "Etc/UTC",
      "theme": "dark",
      "style": "1", // Candlesticks
      "locale": "pl",
      "toolbar_bg": "#0a0e1c",
      "enable_publishing": false,
      "hide_side_toolbar": false, // Pokaż przybory do rysowania (pozycja długa/krótka)
      "allow_symbol_change": false,
      "container_id": "chart-container",
      "studies": [
        "RSI@tv-basicstudies",
        "MASimple@tv-basicstudies"
      ],
      "loading_screen": { "backgroundColor": "#05070f" }
    });
  } catch (e) {
    console.error("Błąd ładowania TradingView widget:", e);
  }
}

function switchSymbol(sym) {
  S.symbol = sym;
  ['BTCUSDT', 'ETHUSDT', 'XRPUSDT'].forEach(s => {
    const btn = document.getElementById(`sym-${s}`);
    if (btn) btn.classList.toggle('active', s === sym);
  });
  initChart();
}

function switchTimeframe(tf) {
  S.tf = tf;
  ['15m', '1h', '4h'].forEach(t => {
    const btn = document.getElementById(`tf-${t}`);
    if (btn) btn.classList.toggle('active', t === tf);
  });
  initChart();
}

/* ════════════════ WEBSOCKETS ════════════════ */
function connectWS() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setStatus(true);
    clearTimeout(wsTimer);
  };

  ws.onclose = () => {
    setStatus(false);
    // Próbuj połączyć ponownie co 5 sekund
    wsTimer = setTimeout(connectWS, 5000);
  };

  ws.onerror = () => {
    setStatus(false);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleWSMessage(msg);
    } catch (e) {
      console.warn("Niewłaściwa wiadomość WS:", e);
    }
  };
}

function setStatus(isOnline) {
  const pill = document.getElementById('connection-status');
  if (!pill) return;
  pill.className = `status-pill ${isOnline ? 'live' : ''}`;
  pill.querySelector('.status-text').textContent = isOnline ? 'NA ŻYWO' : 'ROZŁĄCZONY';
}

function handleWSMessage(msg) {
  if (msg.type === 'NEW_SIGNAL') {
    SFX.new();
    toast('📡 NOWY SYGNAŁ', `${msg.payload.direction} dla ${msg.payload.symbol} (Score: ${msg.payload.score})`);
    
    // Dodaj sygnał na początek
    S.signals.unshift(msg.payload);
    renderSignalsFeed();
    renderTradesTable();
  } 
  else if (msg.type === 'SIGNAL_RESOLVED') {
    // Ktoś wygrał lub przegrał
    if (msg.payload.status === 'WIN') SFX.win();
    else if (msg.payload.status === 'LOSS') SFX.loss();
    
    toast(
      msg.payload.status === 'WIN' ? '🎉 WYGRANA' : '❌ PRZEGRANA', 
      `${msg.payload.symbol} zamknął się na ${msg.payload.status === 'WIN' ? 'Take Profit' : 'Stop Loss'}`
    );

    // Zaktualizuj status sygnału w tablicy
    const target = S.signals.find(s => s.id === msg.payload.signal_id);
    if (target) {
      target.status = msg.payload.status;
      target.pnl_pct = msg.payload.pnl_pct;
      target.result_price = msg.payload.result_price;
    }
    
    fetchInitData(); // odśwież portfel i wagi
  }
  else if (msg.type === 'SETTINGS_UPDATE') {
    S.mode = msg.payload.trading_mode || msg.payload.mode;
    syncToggleUI();
  }
}

/* ════════════════ REST API FETCHES ════════════════ */
async function fetchInitData() {
  try {
    // 1. Ustawienia
    const settings = await fetch(`${API}/api/settings`).then(r => r.json());
    S.mode = settings.mode || 'ANALYZE';
    S.leverage = settings.leverage || 100;
    S.dailyLimit = settings.max_daily_trades || 15;
    syncToggleUI();

    // 2. Portfel
    const wallet = await fetch(`${API}/api/wallet`).then(r => r.json());
    S.balance = wallet.availableBalance || wallet.balance || 1000.0;

    // 3. Statystyki dzienne (liczba tradów)
    const dt = await fetch(`${API}/api/daily_trades`).then(r => r.json());
    S.dailyTrades = dt.count;
    document.getElementById('metrics-daily-trades').textContent = `${S.dailyTrades} / ${S.dailyLimit}`;

    // 4. Sygnały i trady
    const signals = await fetch(`${API}/api/signals?limit=100`).then(r => r.json());
    S.signals = signals;
    renderSignalsFeed();
    renderTradesTable();

    // 5. ML Brain Status
    const ml = await fetch(`${API}/api/ml/status`).then(r => r.json());
    S.ml.accuracy = ml.accuracy || 75.0;
    S.ml.history = ml.history || [50, 60, 68, 75];
    S.ml.logs = ml.logs || ["Uczenie regresji logistycznej z sukcesem."];
    updateMLUI();

  } catch (e) {
    console.warn("Błąd pobierania danych init:", e);
  }
}

/* ════════════════ ACTIONS ════════════════ */
async function toggleSignals(checkbox) {
  const newMode = checkbox.checked ? 'ANALYZE_AND_TRADE' : 'ANALYZE';
  try {
    const res = await fetch(`${API}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: newMode })
    }).then(r => r.json());

    if (res.status === 'ok') {
      S.mode = res.mode || newMode;
      syncToggleUI();
      toast('Tryb bota zmieniony', `Sygnały zostały ${checkbox.checked ? 'WŁĄCZONE' : 'WYŁĄCZONE'}`);
    }
  } catch (e) {
    checkbox.checked = !checkbox.checked; // Przywróć przy błędzie
    toast('⚠️ Błąd zapisu', 'Nie udało się połączyć z API.');
  }
}

function syncToggleUI() {
  const isTrade = S.mode === 'ANALYZE_AND_TRADE';
  const toggle = document.getElementById('signals-toggle');
  if (toggle) toggle.checked = isTrade;

  const label = document.getElementById('signals-toggle-label');
  if (label) {
    label.textContent = isTrade ? 'WŁĄCZONE' : 'WYŁĄCZONE';
    label.className = `toggle-status-label ${isTrade ? 'status-enabled' : 'status-disabled'}`;
  }
}

/* ════════════════ RENDERING ════════════════ */
function renderSignalsFeed() {
  const feed = document.getElementById('signals-feed');
  if (!feed) return;

  // Filtrujemy tylko PENDING / MONITORING jako aktywne feed
  const activeSigs = S.signals.filter(s => s.status === 'PENDING' || s.status === 'MONITORING');

  if (activeSigs.length === 0) {
    feed.innerHTML = '<div class="feed-empty">Brak aktywnych sygnałów. Trwa analiza rynku...</div>';
    return;
  }

  feed.innerHTML = activeSigs.slice(0, 10).map(s => {
    const timeStr = new Date(s.created_at).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
    const isLong = s.direction === 'LONG';
    const rowClass = isLong ? 'long-row' : 'short-row';

    return `
      <div class="signal-row ${rowClass}">
        <div class="sig-meta-header">
          <span class="sig-asset-badge">${s.symbol}</span>
          <span class="sig-direction-badge ${s.direction.toLowerCase()}">${s.direction}</span>
        </div>
        <div class="sig-stats-grid">
          <div class="sig-stat-cell">
            <span class="sig-stat-label">Wejście</span>
            <span class="sig-stat-val">${priceFormat(s.entry_price, s.symbol)}</span>
          </div>
          <div class="sig-stat-cell">
            <span class="sig-stat-label">Take Profit</span>
            <span class="sig-stat-val profit-color">${priceFormat(s.tp_price, s.symbol)}</span>
          </div>
          <div class="sig-stat-cell">
            <span class="sig-stat-label">Stop Loss</span>
            <span class="sig-stat-val loss-color">${priceFormat(s.sl_price, s.symbol)}</span>
          </div>
        </div>
        <div style="font-size: 0.6rem; color: var(--text-muted); text-align: right; margin-top: 4px;">
          Score: ${s.score}/100 · ${timeStr}
        </div>
      </div>
    `;
  }).join('');
}

function renderTradesTable() {
  const body = document.getElementById('trades-table-body');
  const badge = document.getElementById('table-summary-badge');
  if (!body) return;

  // Pokazujemy całą historię
  if (S.signals.length === 0) {
    body.innerHTML = `
      <tr>
        <td colspan="8" class="table-empty-row">Brak historii transakcji...</td>
      </tr>
    `;
    return;
  }

  // Posortuj od najnowszych
  const sorted = [...S.signals].sort((a,b) => new Date(b.created_at) - new Date(a.created_at));

  body.innerHTML = sorted.map(s => {
    const timeStr = new Date(s.created_at).toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' }) + ' ' + new Date(s.created_at).toLocaleDateString('pl-PL', { month: '2-digit', day: '2-digit' });
    const isLong = s.direction === 'LONG';
    const dirColor = isLong ? 'var(--green)' : 'var(--red)';
    const positionUsdt = 50.0; // kwota zlecenia

    let pnlText = '–';
    let pnlColor = 'var(--text-secondary)';
    let statusBadge = '';
    let closePrice = '–';

    if (s.status === 'WIN') {
      const pnl = positionUsdt * ((s.pnl_pct || 250.0) / 100);
      pnlText = `+${pnl.toFixed(2)} USDT (+${(s.pnl_pct || 250.0).toFixed(0)}%)`;
      pnlColor = 'var(--green)';
      statusBadge = '<span style="background:rgba(16, 185, 129, 0.12); color:var(--green); font-size:0.68rem; padding:3px 8px; border-radius:4px; font-weight:700;">🟢 ZYSK (WIN)</span>';
      closePrice = priceFormat(s.result_price || s.tp_price, s.symbol);
    } else if (s.status === 'LOSS') {
      const pnl = positionUsdt * ((s.pnl_pct || -80.0) / 100);
      pnlText = `${pnl.toFixed(2)} USDT (${(s.pnl_pct || -80.0).toFixed(0)}%)`;
      pnlColor = 'var(--red)';
      statusBadge = '<span style="background:rgba(239, 68, 68, 0.12); color:var(--red); font-size:0.68rem; padding:3px 8px; border-radius:4px; font-weight:700;">🔴 STRATA (LOSS)</span>';
      closePrice = priceFormat(s.result_price || s.sl_price, s.symbol);
    } else if (s.status === 'PENDING') {
      statusBadge = '<span style="background:rgba(245, 158, 11, 0.12); color:var(--gold); font-size:0.68rem; padding:3px 8px; border-radius:4px; font-weight:700;">⏳ AKTYWNA</span>';
    } else {
      statusBadge = '<span style="background:rgba(59, 130, 246, 0.12); color:var(--accent); font-size:0.68rem; padding:3px 8px; border-radius:4px; font-weight:700;">🔍 ANALIZA</span>';
    }

    return `
      <tr>
        <td style="font-family: var(--mono); color: var(--text-muted);">${timeStr}</td>
        <td style="font-weight: 700;">${s.symbol}</td>
        <td class="txt-center" style="font-weight: 700; color: ${dirColor};">${s.direction}</td>
        <td class="txt-center" style="font-family: var(--mono); color: var(--text-secondary);">${s.leverage || 100}x</td>
        <td class="txt-right" style="font-family: var(--mono); font-weight: 600;">${priceFormat(s.entry_price, s.symbol)}</td>
        <td class="txt-right" style="font-family: var(--mono); font-weight: 600; color: var(--text-secondary);">${closePrice}</td>
        <td class="txt-right" style="font-family: var(--mono); font-weight: 700; color: ${pnlColor}">${pnlText}</td>
        <td class="txt-center">${statusBadge}</td>
      </tr>
    `;
  }).join('');

  // Update summary badge
  if (badge) {
    const closed = S.signals.filter(s => s.status === 'WIN' || s.status === 'LOSS');
    const wins = closed.filter(s => s.status === 'WIN').length;
    const losses = closed.filter(s => s.status === 'LOSS').length;
    const total = wins + losses;
    const wr = total > 0 ? ((wins / total) * 100).toFixed(0) : 0;
    badge.innerHTML = `WYGRANE: <span class="profit-color">${wins}</span> | PRZEGRANE: <span class="loss-color">${losses}</span> | SKUTECZNOŚĆ: <span class="accent-color">${wr}%</span>`;
  }
}

function updateMLUI() {
  // Update circle text
  const accuracyText = document.getElementById('ml-accuracy-display');
  if (accuracyText) accuracyText.textContent = S.ml.accuracy.toFixed(1) + '%';

  // Update circle fill stroke
  const circleFill = document.getElementById('ml-accuracy-circle-fill');
  if (circleFill) {
    const offset = (S.ml.accuracy / 100) * 100;
    circleFill.setAttribute('stroke-dasharray', `${offset}, 100`);
  }

  // Render logs
  const logsList = document.getElementById('ml-logs-list');
  if (logsList) {
    logsList.innerHTML = S.ml.logs.map(log => `<div class="ml-log-item">${log}</div>`).join('');
  }

  // Draw chart
  drawMLChart();
}

function drawMLChart() {
  const canvas = document.getElementById('ml-accuracy-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.offsetWidth;
  const h = 90;
  canvas.width = w;
  canvas.height = h;

  ctx.clearRect(0, 0, w, h);

  const pts = S.ml.history || [50];
  if (pts.length < 2) return;

  const xStep = w / (pts.length - 1);
  const pad = 10;

  // Background Gradient
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, 'rgba(37, 99, 235, 0.15)');
  grad.addColorStop(1, 'rgba(37, 99, 235, 0)');

  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.moveTo(0, h - pad);
  pts.forEach((p, i) => {
    // Normalizuj p (zwykle od 50 do 100)
    const norm = (p - 40) / 60; // 40-100%
    ctx.lineTo(i * xStep, h - pad - norm * (h - pad * 2));
  });
  ctx.lineTo((pts.length - 1) * xStep, h - pad);
  ctx.closePath();
  ctx.fill();

  // Line Chart
  ctx.beginPath();
  pts.forEach((p, i) => {
    const norm = (p - 40) / 60;
    const x = i * xStep;
    const y = h - pad - norm * (h - pad * 2);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#2563eb';
  ctx.lineWidth = 2.5;
  ctx.stroke();

  // Dots
  pts.forEach((p, i) => {
    const norm = (p - 40) / 60;
    const x = i * xStep;
    const y = h - pad - norm * (h - pad * 2);
    ctx.beginPath();
    ctx.arc(x, y, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = '#2563eb';
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;
    ctx.stroke();
  });
}

/* ════════════════ TOAST NOTIFICATION ════════════════ */
function toast(title, msg) {
  // Remove existing toast
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const element = document.createElement('div');
  element.className = 'toast';
  element.innerHTML = `
    <strong style="color:var(--accent); font-family:'Outfit';">${title}</strong>
    <span style="color:var(--text-secondary); font-size:0.72rem;">${msg}</span>
  `;
  document.body.appendChild(element);

  setTimeout(() => {
    element.style.opacity = '0';
    element.style.transition = 'opacity 0.5s';
    setTimeout(() => element.remove(), 500);
  }, 4000);
}

/* ════════════════ UTILS ════════════════ */
function priceFormat(price, symbol) {
  if (price === undefined || price === null) return '–';
  if (symbol && symbol.includes('XRP')) return Number(price).toFixed(5);
  return Number(price).toFixed(2);
}
