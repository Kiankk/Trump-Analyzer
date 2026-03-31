/**
 * ═══════════════════════════════════════════════════════════════
 * SQUAWK BOX — Client-Side Application
 * WebSocket real-time headline feed with audio squawk
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
    }
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
    }, 400);
});


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
            // Batch of recent headlines on connect
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

        case 'pong':
            break;

        default:
            console.log('[WS] Unknown message type:', msg.type);
    }
}


// ═══════════════════════════════════════════════════════════════
//  HEADLINE RENDERING
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
    // Update stats
    state.headlineCount++;
    dom.headlineCount.textContent = `${state.headlineCount} headlines`;

    if (state.stats[data.source] !== undefined) {
        state.stats[data.source]++;
    }
    updateStats();

    // Check filters
    const visible = state.filters.sources.has(data.source) &&
                    state.filters.categories.has(data.category);

    // Create element
    const el = document.createElement('div');
    el.className = `headline priority-${data.priority || 0}`;
    el.dataset.source = data.source;
    el.dataset.category = data.category;
    el.dataset.id = data.id;

    if (!visible) {
        el.style.display = 'none';
    }

    if (isNew) {
        el.classList.add('headline-flash');
    }

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

    // Audio click handler (if audio_url was already generated, e.g. historical load)
    const audioBtn = el.querySelector('.hl-audio');
    if (audioBtn) {
        audioBtn.addEventListener('click', () => {
            playAudio(audioBtn.dataset.audio, audioBtn);
        });
    }

    // Insert at top of feed
    dom.feed.prepend(el);

    // Limit DOM size — remove oldest beyond 300
    while (dom.feed.children.length > 300) {
        dom.feed.removeChild(dom.feed.lastChild);
    }

    // The text arrived! Play instant alert beep before TTS is even ready.
    if (isNew && visible && state.audioEnabled && data.priority > 0) {
        playAlertBeep(data.priority);
    }

    // If historical load already has audio
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

    // Enqueue the voice generation
    if (state.audioEnabled && el.style.display !== 'none') {
        enqueueAudio(url);
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
        // High priority: Sharp descending alert
        osc.type = 'square';
        osc.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
        osc.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.15);
        gainNode.gain.setValueAtTime(0.15, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.15);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.15);
    } else {
        // Normal priority: Short ping
        osc.type = 'sine';
        osc.frequency.setValueAtTime(660, audioCtx.currentTime); // E5
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
        const type = chip.dataset.filterType;   // 'source' or 'category'
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

// Audio toggle
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
        // Clear audio queue
        state.audioQueue = [];
    }
});

// Clear feed
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
//  UTILITIES
// ═══════════════════════════════════════════════════════════════

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
