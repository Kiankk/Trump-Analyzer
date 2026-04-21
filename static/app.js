/**
 * ═══════════════════════════════════════════════════════════════
 * SQUAWK BOX v2.0 — Client-Side Application
 * WebSocket real-time headline feed + LLM trading dashboard
 * ═══════════════════════════════════════════════════════════════
 */

// ─── State ──────────────────────────────────────────────────────
const state = {
    ws: null,
    audioEnabled: true,
    audioQueue: [],
    isPlaying: false,
    headlineCount: 0,
    reconnectDelay: 1000,
    maxReconnectDelay: 30000,
    filters: {
        sources: new Set(['FIN_JUICE', 'WEB/RSS', 'TELEGRAM', 'SEC_EDGAR']),
        categories: new Set(['FED_SPEAK', 'MACRO_DATA', 'TRUMP_POLICY', 'GEO_RISK', 'COMMODITIES', 'MARKET_FLOW', 'EARNINGS', 'SEC_FILING', 'BREAKING'])
    },
    stats: {
        'FIN_JUICE': 0,
        'WEB/RSS': 0,
        'TELEGRAM': 0,
        'SEC_EDGAR': 0
    },
    // Trading state
    currentView: 'news',
    tradingEnabled: false,
    signalCount: 0,
};

// ─── DOM References ─────────────────────────────────────────────
const dom = {
    gate:          document.getElementById('audio-gate'),
    gateBtn:       document.getElementById('gate-btn'),
    app:           document.getElementById('app'),
    connStatus:    document.getElementById('conn-status'),
    connText:      document.querySelector('.conn-text'),
    clock:         document.getElementById('clock'),
    headlineCount: document.getElementById('headline-count'),
    feed:          document.getElementById('feed'),
    emptyState:    document.getElementById('empty-state'),
    audioToggle:   document.getElementById('audio-toggle'),
    clearBtn:      document.getElementById('clear-btn'),
    // Stats
    statFinjuice:  document.getElementById('stat-finjuice'),
    statRss:       document.getElementById('stat-rss'),
    statTelegram:  document.getElementById('stat-telegram'),
    statSec:       document.getElementById('stat-sec'),
    // Views
    newsView:      document.getElementById('news-view'),
    tradingView:   document.getElementById('trading-view'),
    viewNewsBtn:   document.getElementById('view-news-btn'),
    viewTradingBtn: document.getElementById('view-trading-btn'),
    // Trading
    tradingToggleBtn: document.getElementById('trading-toggle-btn'),
    tradingToggleLabel: document.getElementById('trading-toggle-label'),
    tcMode:        document.getElementById('tc-mode'),
    tcLlm:         document.getElementById('tc-llm'),
    tcLlmText:     document.getElementById('tc-llm-text'),
    closeAllBtn:   document.getElementById('close-all-btn'),
    // P&L
    pnlEquity:     document.getElementById('pnl-equity'),
    pnlRealized:   document.getElementById('pnl-realized'),
    pnlUnrealized: document.getElementById('pnl-unrealized'),
    pnlTotal:      document.getElementById('pnl-total'),
    pnlWinrate:    document.getElementById('pnl-winrate'),
    pnlTrades:     document.getElementById('pnl-trades'),
    // Panels
    positionsContainer: document.getElementById('positions-container'),
    signalsContainer: document.getElementById('signals-container'),
    historyContainer: document.getElementById('history-container'),
    posCount:      document.getElementById('pos-count'),
    signalCountEl: document.getElementById('signal-count'),
    historyCount:  document.getElementById('history-count'),
};


// ═══════════════════════════════════════════════════════════════
//  AUDIO GATE
// ═══════════════════════════════════════════════════════════════

dom.gateBtn.addEventListener('click', () => {
    dom.gate.style.opacity = '0';
    dom.gate.style.transition = 'opacity 0.4s ease';
    setTimeout(() => {
        dom.gate.classList.add('hidden');
        dom.app.classList.remove('hidden');
        connectWebSocket();
        startClock();
        fetchTradingStatus();
    }, 400);
});


// ═══════════════════════════════════════════════════════════════
//  VIEW SWITCHING
// ═══════════════════════════════════════════════════════════════

dom.viewNewsBtn.addEventListener('click', () => switchView('news'));
dom.viewTradingBtn.addEventListener('click', () => switchView('trading'));

function switchView(view) {
    state.currentView = view;

    if (view === 'news') {
        dom.newsView.classList.remove('hidden');
        dom.tradingView.classList.add('hidden');
        dom.viewNewsBtn.classList.add('view-active');
        dom.viewTradingBtn.classList.remove('view-active');
    } else {
        dom.newsView.classList.add('hidden');
        dom.tradingView.classList.remove('hidden');
        dom.viewNewsBtn.classList.remove('view-active');
        dom.viewTradingBtn.classList.add('view-active');
        fetchTradingStatus();
        if (typeof fetchPerformanceData === "function") {
            fetchPerformanceData();
        }
    }
}


// ═══════════════════════════════════════════════════════════════
//  WEBSOCKET CONNECTION
// ═══════════════════════════════════════════════════════════════

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        setConnectionStatus(true);
        state.reconnectDelay = 1000;
        console.log('[WS] Connected');
    };

    state.ws.onclose = () => {
        setConnectionStatus(false);
        console.log(`[WS] Disconnected. Reconnecting in ${state.reconnectDelay}ms...`);
        setTimeout(connectWebSocket, state.reconnectDelay);
        state.reconnectDelay = Math.min(state.reconnectDelay * 2, state.maxReconnectDelay);
    };

    state.ws.onerror = (err) => {
        console.error('[WS] Error:', err);
    };

    state.ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleMessage(msg);
        } catch (e) {
            console.error('[WS] Parse error:', e);
        }
    };

    // Keep-alive ping
    setInterval(() => {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
            state.ws.send('ping');
        }
    }, 30000);
}

function setConnectionStatus(connected) {
    const el = dom.connStatus;
    if (connected) {
        el.className = 'conn-badge connected';
        dom.connText.textContent = 'LIVE';
    } else {
        el.className = 'conn-badge disconnected';
        dom.connText.textContent = 'OFFLINE';
    }
}


// ═══════════════════════════════════════════════════════════════
//  MESSAGE HANDLER
// ═══════════════════════════════════════════════════════════════

function handleMessage(msg) {
    switch (msg.type) {
        case 'init':
            if (msg.headlines && msg.headlines.length > 0) {
                dom.emptyState?.remove();
                msg.headlines.reverse().forEach(h => addHeadline(h, false));
            }
            break;

        case 'headline':
            dom.emptyState?.remove();
            addHeadline(msg.data, true);
            break;

        case 'stats':
            if (msg.data) updateStatsFromServer(msg.data);
            break;

        case 'audio_ready':
            attachAudioToHeadline(msg.id, msg.audio_url);
            break;

        // ─── Trading Events ─────────────────────────────────
        case 'trading_status':
            updateTradingStatus(msg.data);
            break;

        case 'trade_signal':
            addSignalCard(msg.data);
            break;

        case 'trade_executed':
            handleTradeExecuted(msg.data);
            break;

        case 'trade_closed':
            handleTradeClosed(msg.data);
            break;

        case 'position_update':
            updatePositions(msg.data);
            break;

        case 'trading_toggle':
            updateTradingToggle(msg.data.enabled);
            break;

        case 'pong':
            break;

        default:
            console.log('[WS] Unknown message type:', msg.type);
    }
}


// ═══════════════════════════════════════════════════════════════
//  HEADLINE RENDERING (unchanged logic)
// ═══════════════════════════════════════════════════════════════

function getSourceClass(source) {
    const map = {
        'FIN_JUICE': 'source-finjuice',
        'WEB/RSS':   'source-rss',
        'TELEGRAM':  'source-telegram',
        'SEC_EDGAR': 'source-sec'
    };
    return map[source] || 'source-rss';
}

function getSentimentIcon(sentiment) {
    const map = {
        'BULLISH':  '▲',
        'BEARISH':  '▼',
        'NEUTRAL':  '●'
    };
    return map[sentiment] || '●';
}

function addHeadline(data, isNew) {
    state.headlineCount++;
    dom.headlineCount.textContent = `${state.headlineCount} headlines`;

    if (state.stats[data.source] !== undefined) {
        state.stats[data.source]++;
    }
    updateStats();

    const visible = state.filters.sources.has(data.source) &&
                    state.filters.categories.has(data.category);

    const el = document.createElement('div');
    el.className = `headline priority-${data.priority || 0}`;
    el.dataset.source = data.source;
    el.dataset.category = data.category;
    el.dataset.id = data.id;

    if (!visible) el.style.display = 'none';
    if (isNew) el.classList.add('headline-flash');

    const titleContent = data.url
        ? `<a href="${escapeHtml(data.url)}" target="_blank" rel="noopener">${escapeHtml(data.title)}</a>`
        : escapeHtml(data.title);

    el.innerHTML = `
        <span class="hl-time">${escapeHtml(data.timestamp)}</span>
        <span class="hl-source ${getSourceClass(data.source)}">${escapeHtml(data.source)}</span>
        <span class="hl-category cat-${data.category}">${escapeHtml(data.category)}</span>
        <span class="hl-sentiment sent-${data.sentiment}">${getSentimentIcon(data.sentiment)}</span>
        <span class="hl-title">${titleContent}</span>
        ${data.audio_url ? `<span class="hl-audio" data-audio="${escapeHtml(data.audio_url)}" title="Play audio">🔊</span>` : ''}
    `;

    const audioBtn = el.querySelector('.hl-audio');
    if (audioBtn) {
        audioBtn.addEventListener('click', () => {
            playAudio(audioBtn.dataset.audio, audioBtn);
        });
    }

    dom.feed.prepend(el);

    while (dom.feed.children.length > 300) {
        dom.feed.removeChild(dom.feed.lastChild);
    }

    if (isNew && visible && state.audioEnabled && data.priority > 0) {
        playAlertBeep(data.priority);
    }

    if (isNew && data.audio_url && state.audioEnabled && visible) {
        enqueueAudio(data.audio_url);
    }
}

function attachAudioToHeadline(id, url) {
    const el = document.querySelector(`.headline[data-id="${id}"]`);
    if (!el) return;
    if (el.querySelector('.hl-audio')) return;

    const audioBtn = document.createElement('span');
    audioBtn.className = 'hl-audio';
    audioBtn.dataset.audio = url;
    audioBtn.title = 'Play audio';
    audioBtn.textContent = '🔊';
    
    audioBtn.addEventListener('click', () => {
        playAudio(url, audioBtn);
    });
    
    el.appendChild(audioBtn);

    if (state.audioEnabled && el.style.display !== 'none') {
        enqueueAudio(url);
    }
}


// ═══════════════════════════════════════════════════════════════
//  TRADING — Signal Cards
// ═══════════════════════════════════════════════════════════════

function addSignalCard(data) {
    state.signalCount++;
    dom.signalCountEl.textContent = state.signalCount;

    // Remove empty state
    const empty = dom.signalsContainer.querySelector('.empty-panel');
    if (empty) empty.remove();

    const dirClass = data.direction === 'LONG' ? 'long' :
                     data.direction === 'SHORT' ? 'short' : 'no-trade';

    const confClass = data.confidence >= 0.85 ? 'high' :
                      data.confidence >= 0.70 ? 'medium' : 'low';

    const urgClass = data.urgency === 'IMMEDIATE' ? 'immediate' : '';

    const timeStr = data.timestamp ? new Date(data.timestamp).toLocaleTimeString('en-US', { hour12: false }) : '';

    const el = document.createElement('div');
    el.className = `signal-card signal-${dirClass}`;

    el.innerHTML = `
        <div class="signal-top">
            <span class="signal-dir ${dirClass}">${escapeHtml(data.direction)}</span>
            <span class="signal-inst">${escapeHtml(data.instrument)}</span>
            <span class="signal-conf ${confClass}">${(data.confidence * 100).toFixed(0)}%</span>
            <span class="signal-urgency ${urgClass}">${escapeHtml(data.urgency)}</span>
            ${data.is_tradeable ? '<span style="color:var(--bullish);font-size:10px">⚡ TRADEABLE</span>' : ''}
            <span class="signal-time">${timeStr}</span>
        </div>
        <div class="signal-reasoning">${escapeHtml(data.reasoning)}</div>
        <div class="signal-headline-ref">📰 ${escapeHtml(data.headline || '')}</div>
    `;

    dom.signalsContainer.prepend(el);

    // Limit signal cards
    while (dom.signalsContainer.children.length > 50) {
        dom.signalsContainer.removeChild(dom.signalsContainer.lastChild);
    }

    // Play alert for tradeable signals
    if (data.is_tradeable && state.audioEnabled) {
        playTradeBeep();
    }
}

function playTradeBeep() {
    if (!state.audioEnabled) return;
    if (audioCtx.state === 'suspended') audioCtx.resume();
    
    const osc = audioCtx.createOscillator();
    const gainNode = audioCtx.createGain();
    osc.connect(gainNode);
    gainNode.connect(audioCtx.destination);
    
    // Double beep for trade signals
    osc.type = 'sine';
    osc.frequency.setValueAtTime(1047, audioCtx.currentTime); // C6
    osc.frequency.setValueAtTime(1319, audioCtx.currentTime + 0.08); // E6
    gainNode.gain.setValueAtTime(0.12, audioCtx.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.2);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.2);
}


// ═══════════════════════════════════════════════════════════════
//  TRADING — Position Management
// ═══════════════════════════════════════════════════════════════

function handleTradeExecuted(data) {
    if (data.action === 'OPEN' && data.position) {
        renderPosition(data.position);
    }
}

function handleTradeClosed(data) {
    // Remove position card
    const posCard = document.querySelector(`.position-card[data-id="${data.position_id}"]`);
    if (posCard) {
        posCard.classList.add(data.pnl >= 0 ? 'trade-flash-win' : 'trade-flash-loss');
        setTimeout(() => posCard.remove(), 1000);
    }

    // Update P&L
    updatePnlValue(dom.pnlEquity, data.equity, false);
    updatePnlValue(dom.pnlRealized, data.pnl, true);

    // Add to history
    addHistoryRow(data);

    // Update position count
    const posCards = dom.positionsContainer.querySelectorAll('.position-card');
    dom.posCount.textContent = Math.max(0, posCards.length - 1); // -1 for the one being removed
}

function renderPosition(pos) {
    // Remove empty state
    const empty = dom.positionsContainer.querySelector('.empty-panel');
    if (empty) empty.remove();

    const el = document.createElement('div');
    el.className = 'position-card';
    el.dataset.id = pos.id;

    const pnlClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';
    const pnlStr = formatPnl(pos.unrealized_pnl);

    el.innerHTML = `
        <span class="pos-direction ${pos.direction.toLowerCase()}">${pos.direction}</span>
        <span class="pos-instrument">${escapeHtml(pos.instrument)}</span>
        <div class="pos-info">
            <span class="pos-prices">Entry: $${pos.entry_price.toLocaleString(undefined, {minimumFractionDigits:2})} | SL: $${pos.stop_loss.toLocaleString()} | TP: $${pos.take_profit.toLocaleString()}</span>
            <span class="pos-headline">${escapeHtml(pos.headline_text || '')}</span>
        </div>
        <span class="pos-pnl ${pnlClass}">${pnlStr}</span>
        <button class="pos-close-btn" onclick="closePosition('${pos.id}')">CLOSE</button>
    `;

    dom.positionsContainer.prepend(el);
    dom.posCount.textContent = dom.positionsContainer.querySelectorAll('.position-card').length;
}

function updatePositions(data) {
    if (!data || !data.positions) return;

    // Update P&L strip
    updatePnlValue(dom.pnlEquity, data.equity, false);
    updatePnlValue(dom.pnlUnrealized, data.unrealized_pnl, true);
    const totalPnl = (data.equity - 10000); // Assuming 10k starting
    updatePnlValue(dom.pnlTotal, totalPnl, true);

    // Update each position's P&L
    data.positions.forEach(pos => {
        const card = document.querySelector(`.position-card[data-id="${pos.id}"]`);
        if (card) {
            const pnlEl = card.querySelector('.pos-pnl');
            if (pnlEl) {
                const pnlClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';
                pnlEl.className = `pos-pnl ${pnlClass}`;
                pnlEl.textContent = formatPnl(pos.unrealized_pnl);
            }
        }
    });
}

function addHistoryRow(data) {
    const empty = dom.historyContainer.querySelector('.empty-panel');
    if (empty) empty.remove();

    const pnlClass = data.pnl >= 0 ? 'positive' : 'negative';
    const el = document.createElement('div');
    el.className = `history-row ${data.pnl >= 0 ? 'trade-flash-win' : 'trade-flash-loss'}`;

    el.innerHTML = `
        <span class="hist-time">${new Date().toLocaleTimeString('en-US', { hour12: false })}</span>
        <span class="hist-dir ${data.direction?.toLowerCase() || ''}">${data.direction || ''}</span>
        <span class="hist-inst">${escapeHtml(data.instrument || '')}</span>
        <span class="hist-prices">Entry: $${(data.entry_price || 0).toLocaleString(undefined, {minimumFractionDigits:2})} → Exit: $${(data.exit_price || 0).toLocaleString(undefined, {minimumFractionDigits:2})}</span>
        <span class="hist-pnl ${pnlClass}">${formatPnl(data.pnl)}</span>
        <span class="hist-reason">${escapeHtml(data.reason || '')}</span>
    `;

    dom.historyContainer.prepend(el);
    const count = dom.historyContainer.querySelectorAll('.history-row').length;
    dom.historyCount.textContent = count;
}


// ═══════════════════════════════════════════════════════════════
//  TRADING — Controls
// ═══════════════════════════════════════════════════════════════

dom.tradingToggleBtn.addEventListener('click', async () => {
    try {
        const resp = await fetch('/api/trading/toggle', { method: 'POST' });
        const data = await resp.json();
        updateTradingToggle(data.trading_enabled);
    } catch (e) {
        console.error('Toggle trading failed:', e);
    }
});

dom.closeAllBtn.addEventListener('click', async () => {
    if (!confirm('⚠️ Close ALL open positions?')) return;
    try {
        const resp = await fetch('/api/trading/close-all', { method: 'POST' });
        const data = await resp.json();
        console.log('Close all result:', data);
    } catch (e) {
        console.error('Close all failed:', e);
    }
});

async function closePosition(posId) {
    try {
        const resp = await fetch(`/api/trading/close/${posId}`, { method: 'POST' });
        const data = await resp.json();
        console.log('Close position result:', data);
    } catch (e) {
        console.error('Close position failed:', e);
    }
}

function updateTradingToggle(enabled) {
    state.tradingEnabled = enabled;
    const btn = dom.tradingToggleBtn;
    const label = dom.tradingToggleLabel;

    if (enabled) {
        btn.classList.remove('trading-off');
        btn.classList.add('trading-on');
        label.textContent = 'AUTO-TRADE ON';
    } else {
        btn.classList.remove('trading-on');
        btn.classList.add('trading-off');
        label.textContent = 'AUTO-TRADE OFF';
    }
}

function updateTradingStatus(data) {
    if (!data) return;

    updateTradingToggle(data.enabled);

    if (data.mode) {
        dom.tcMode.textContent = data.mode === 'PAPER' ? '📝 PAPER MODE' : '🔴 LIVE MODE';
    }

    if (data.executor) {
        updatePnlValue(dom.pnlEquity, data.executor.equity, false);
        updatePnlValue(dom.pnlRealized, data.executor.realized_pnl, true);
        updatePnlValue(dom.pnlUnrealized, data.executor.unrealized_pnl, true);
        updatePnlValue(dom.pnlTotal, data.executor.total_pnl, true);

        // Render existing positions
        if (data.executor.positions) {
            data.executor.positions.forEach(pos => renderPosition(pos));
        }
    }
}

async function fetchTradingStatus() {
    try {
        const resp = await fetch('/api/trading/status');
        const data = await resp.json();

        updateTradingToggle(data.trading_enabled);
        
        if (data.mode) {
            dom.tcMode.textContent = data.mode === 'PAPER' ? '📝 PAPER MODE' : '🔴 LIVE MODE';
        }

        // LLM status
        const llmDot = dom.tcLlm.querySelector('.llm-dot');
        if (data.llm_healthy) {
            llmDot.className = 'llm-dot online';
            dom.tcLlmText.textContent = 'LLM ONLINE';
        } else {
            llmDot.className = 'llm-dot offline';
            dom.tcLlmText.textContent = 'LLM OFFLINE';
        }

        if (data.executor) {
            updatePnlValue(dom.pnlEquity, data.executor.equity, false);
            updatePnlValue(dom.pnlRealized, data.executor.realized_pnl, true);
            updatePnlValue(dom.pnlUnrealized, data.executor.unrealized_pnl, true);
            updatePnlValue(dom.pnlTotal, data.executor.total_pnl, true);
        }

        if (data.signal_manager) {
            dom.pnlTrades.textContent = data.signal_manager.daily_trade_count || 0;
        }

    } catch (e) {
        console.error('Fetch trading status failed:', e);
    }
}

// Auto-refresh trading status every 10s when on trading view
setInterval(() => {
    if (state.currentView === 'trading') {
        fetchTradingStatus();
        fetchPerformanceData();
    }
}, 10000);


// ═══════════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════════

function formatPnl(value) {
    if (value === undefined || value === null) return '$0.00';
    const prefix = value >= 0 ? '+$' : '-$';
    return `${prefix}${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function updatePnlValue(el, value, colorize) {
    if (!el) return;
    if (colorize) {
        el.className = `pnl-value ${value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral'}`;
    }
    if (typeof value === 'number') {
        el.textContent = colorize ? formatPnl(value) : `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
}


// ═══════════════════════════════════════════════════════════════
//  AUDIO ENGINE
// ═══════════════════════════════════════════════════════════════

const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function playAlertBeep(priority) {
    if (!state.audioEnabled) return;
    if (audioCtx.state === 'suspended') audioCtx.resume();
    
    const osc = audioCtx.createOscillator();
    const gainNode = audioCtx.createGain();
    
    osc.connect(gainNode);
    gainNode.connect(audioCtx.destination);
    
    if (priority >= 2) {
        osc.type = 'square';
        osc.frequency.setValueAtTime(880, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.15);
        gainNode.gain.setValueAtTime(0.15, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.15);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.15);
    } else {
        osc.type = 'sine';
        osc.frequency.setValueAtTime(660, audioCtx.currentTime);
        gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.1);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.1);
    }
}

function enqueueAudio(url) {
    state.audioQueue.push(url);
    if (!state.isPlaying) {
        playNextInQueue();
    }
}

function playNextInQueue() {
    if (state.audioQueue.length === 0) {
        state.isPlaying = false;
        return;
    }

    state.isPlaying = true;
    const url = state.audioQueue.shift();
    playAudio(url);
}

function playAudio(url, btn) {
    const audio = new Audio(url);

    if (btn) {
        btn.classList.add('playing');
    }

    audio.onended = () => {
        if (btn) btn.classList.remove('playing');
        playNextInQueue();
    };

    audio.onerror = () => {
        console.warn('[Audio] Playback failed:', url);
        if (btn) btn.classList.remove('playing');
        playNextInQueue();
    };

    audio.play().catch(err => {
        console.warn('[Audio] Play blocked:', err.message);
        if (btn) btn.classList.remove('playing');
        playNextInQueue();
    });
}


// ═══════════════════════════════════════════════════════════════
//  FILTER SYSTEM
// ═══════════════════════════════════════════════════════════════

document.querySelectorAll('.filter-chip').forEach(chip => {
    chip.addEventListener('click', () => {
        const type = chip.dataset.filterType;
        const value = chip.dataset.value;
        const filterSet = type === 'source' ? state.filters.sources : state.filters.categories;

        if (chip.classList.contains('active')) {
            chip.classList.remove('active');
            filterSet.delete(value);
        } else {
            chip.classList.add('active');
            filterSet.add(value);
        }

        applyFilters();
    });
});

function applyFilters() {
    document.querySelectorAll('.headline').forEach(el => {
        const source = el.dataset.source;
        const category = el.dataset.category;
        const visible = state.filters.sources.has(source) &&
                        state.filters.categories.has(category);
        el.style.display = visible ? '' : 'none';
    });
}


// ═══════════════════════════════════════════════════════════════
//  CONTROLS
// ═══════════════════════════════════════════════════════════════

dom.audioToggle.addEventListener('click', () => {
    state.audioEnabled = !state.audioEnabled;
    const btn = dom.audioToggle;
    const label = btn.querySelector('.btn-label');

    if (state.audioEnabled) {
        btn.classList.remove('audio-off');
        btn.classList.add('audio-on');
        label.textContent = '🔊 SQUAWK';
    } else {
        btn.classList.remove('audio-on');
        btn.classList.add('audio-off');
        label.textContent = '🔇 MUTED';
        state.audioQueue = [];
    }
});

dom.clearBtn.addEventListener('click', () => {
    dom.feed.innerHTML = '';
    state.headlineCount = 0;
    dom.headlineCount.textContent = '0 headlines';
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'm' || e.key === 'M') {
        dom.audioToggle.click();
    }
    if (e.key === 't' || e.key === 'T') {
        switchView(state.currentView === 'news' ? 'trading' : 'news');
    }
});


// ═══════════════════════════════════════════════════════════════
//  STATS
// ═══════════════════════════════════════════════════════════════

function updateStats() {
    dom.statFinjuice.textContent = state.stats['FIN_JUICE'] || 0;
    dom.statRss.textContent      = state.stats['WEB/RSS'] || 0;
    dom.statTelegram.textContent  = state.stats['TELEGRAM'] || 0;
    dom.statSec.textContent       = state.stats['SEC_EDGAR'] || 0;
}

function updateStatsFromServer(data) {
    if (data.by_source) {
        Object.assign(state.stats, data.by_source);
        updateStats();
    }
    if (data.total) {
        state.headlineCount = data.total;
        dom.headlineCount.textContent = `${data.total} headlines`;
    }
}


// ═══════════════════════════════════════════════════════════════
//  CLOCK
// ═══════════════════════════════════════════════════════════════

function startClock() {
    function tick() {
        const now = new Date();
        dom.clock.textContent = now.toLocaleTimeString('en-US', { hour12: false });
    }
    tick();
    setInterval(tick, 1000);
}


// ═══════════════════════════════════════════════════════════════
//  CHARTING & PERFORMANCE
// ═══════════════════════════════════════════════════════════════

let equityChartInstance = null;

async function fetchPerformanceData() {
    try {
        const resp = await fetch('/api/trading/performance');
        const data = await resp.json();
        
        if (data.equity_history && data.equity_history.length > 0) {
            updateEquityChart(data.equity_history);
        }
    } catch (e) {
        console.error('Failed to fetch performance data:', e);
    }
}

function updateEquityChart(historyData) {
    const ctx = document.getElementById('equityChart');
    if (!ctx) return;

    // Sort ascending by time
    const sorted = [...historyData].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    
    const labels = sorted.map(row => {
        const d = new Date(row.timestamp + 'Z');
        return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
    });
    const dataPoints = sorted.map(row => row.equity);

    const isProfitable = dataPoints[dataPoints.length - 1] >= dataPoints[0];
    const lineColor = isProfitable ? '#10b981' : '#ef4444'; 
    const bgColor = isProfitable ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)';

    if (equityChartInstance) {
        equityChartInstance.data.labels = labels;
        equityChartInstance.data.datasets[0].data = dataPoints;
        equityChartInstance.data.datasets[0].borderColor = lineColor;
        equityChartInstance.data.datasets[0].backgroundColor = bgColor;
        equityChartInstance.update('none'); // Update without animation for smooth streaming
    } else {
        equityChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Equity ($)',
                    data: dataPoints,
                    borderColor: lineColor,
                    backgroundColor: bgColor,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    pointHoverRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: {
                    intersect: false,
                    mode: 'index',
                },
                scales: {
                    x: {
                        grid: { display: false, drawBorder: false },
                        ticks: { color: '#888', maxTicksLimit: 6 }
                    },
                    y: {
                        grid: { color: '#2a2a2a' },
                        ticks: {
                            color: '#888',
                            callback: function(value) {
                                return '$' + value.toLocaleString();
                            }
                        }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        theme: 'dark',
                        backgroundColor: 'rgba(0,0,0,0.8)',
                        callbacks: {
                            label: function(context) {
                                return '$' + context.parsed.y.toLocaleString(undefined, {minimumFractionDigits: 2});
                            }
                        }
                    }
                }
            }
        });
    }
}


// ═══════════════════════════════════════════════════════════════
//  UTILITIES
// ═══════════════════════════════════════════════════════════════

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
