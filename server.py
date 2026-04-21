# server.py
"""
Financial Squawk Box — FastAPI Backend
Real-time financial news aggregation, AI filtering, TTS audio squawk,
and LLM-powered automated trading engine.
"""

import asyncio
import json
import os
import logging
from datetime import datetime
from collections import deque
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

from ingestion import Headline, headline_queue, trading_queue, fast_rss_ingester, slow_rss_ingester, sec_edgar_ingester
from filters import analyze_headline
from tts_engine import synthesize_headline
from llm_engine import get_llm_engine
from signal_manager import get_signal_manager
from executor import create_executor, execution_loop, price_monitor_loop
from database import get_db
import trading_config as cfg

load_dotenv()

# ═══════════════════════════════════════════════════════════════
#  Logging
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s │ %(name)-24s │ %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("squawkbox")

# ═══════════════════════════════════════════════════════════════
#  FastAPI App
# ═══════════════════════════════════════════════════════════════

app = FastAPI(title="Squawk Box", version="2.0.0")

# ─── State ──────────────────────────────────────────────────────
recent_headlines: deque = deque(maxlen=200)
connected_clients: Set[WebSocket] = set()
stats = {
    "total": 0,
    "by_source": {},
    "by_category": {},
    "boot_time": None
}

# Trading engine globals (initialized at startup)
_executor = None
_signal_manager = None

# ─── Static Files ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
AUDIO_DIR = os.path.join(STATIC_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ═══════════════════════════════════════════════════════════════
#  HTTP Routes — Original
# ═══════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    """Serve the main dashboard."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/headlines")
async def get_headlines():
    """Return recent headlines buffer."""
    return JSONResponse(list(recent_headlines))


@app.get("/api/stats")
async def get_stats():
    """Return pipeline statistics."""
    return JSONResponse(stats)


@app.get("/api/prices")
async def get_prices():
    """Return live prices for all tracked instruments."""
    from price_feed import get_price_feed
    feed = await get_price_feed()
    return JSONResponse(feed.get_status())


# ═══════════════════════════════════════════════════════════════
#  HTTP Routes — Trading
# ═══════════════════════════════════════════════════════════════

@app.get("/api/trading/status")
async def trading_status():
    """Return full trading engine status."""
    global _executor, _signal_manager
    llm = await get_llm_engine()
    db = await get_db()

    return JSONResponse({
        "trading_enabled": _signal_manager.trading_enabled if _signal_manager else False,
        "mode": "PAPER" if cfg.PAPER_MODE else "LIVE",
        "executor": _executor.get_status() if _executor else {},
        "signal_manager": _signal_manager.stats if _signal_manager else {},
        "llm_engine": llm.stats if llm else {},
        "llm_healthy": llm.is_healthy if llm else False,
    })


@app.get("/api/trading/positions")
async def get_positions():
    """Return current open positions."""
    global _executor
    if not _executor:
        return JSONResponse([])
    return JSONResponse(_executor.get_open_positions())


@app.get("/api/trading/trades")
async def get_trades():
    """Return trade history."""
    db = await get_db()
    trades = await db.get_trade_history(100)
    return JSONResponse(trades)


@app.get("/api/trading/signals")
async def get_signals():
    """Return recent LLM signals."""
    db = await get_db()
    signals = await db.get_recent_signals(50)
    return JSONResponse(signals)


@app.get("/api/trading/performance")
async def get_performance():
    """Return trading performance statistics."""
    db = await get_db()
    perf = await db.get_performance_stats()
    equity_history = await db.get_equity_history(200)
    sentiment = await db.get_sentiment_distribution(100)
    return JSONResponse({
        "performance": perf,
        "equity_history": equity_history,
        "sentiment_distribution": sentiment,
    })


@app.post("/api/trading/toggle")
async def toggle_trading():
    """Enable/disable auto-trading."""
    global _signal_manager
    if _signal_manager:
        _signal_manager.trading_enabled = not _signal_manager.trading_enabled
        status = "ENABLED" if _signal_manager.trading_enabled else "DISABLED"
        logger.info(f"🔄 Trading {status} via API")

        await broadcast_trading_event("trading_toggle", {
            "enabled": _signal_manager.trading_enabled
        })

        return JSONResponse({"trading_enabled": _signal_manager.trading_enabled})
    return JSONResponse({"error": "Signal manager not initialized"}, status_code=500)


@app.post("/api/trading/close-all")
async def close_all_positions():
    """Emergency close all positions."""
    global _executor
    if _executor:
        total_pnl = await _executor.close_all("API_CLOSE_ALL")
        return JSONResponse({"closed": True, "total_pnl": round(total_pnl, 2)})
    return JSONResponse({"error": "Executor not initialized"}, status_code=500)


@app.post("/api/trading/close/{position_id}")
async def close_position(position_id: str):
    """Close a specific position."""
    global _executor
    if _executor:
        pnl = await _executor.close_position(position_id, "API_MANUAL_CLOSE")
        if pnl is not None:
            return JSONResponse({"closed": True, "pnl": round(pnl, 2)})
        return JSONResponse({"error": "Position not found"}, status_code=404)
    return JSONResponse({"error": "Executor not initialized"}, status_code=500)


# ═══════════════════════════════════════════════════════════════
#  WebSocket
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Real-time headline and trading data streaming to browser clients."""
    await ws.accept()
    connected_clients.add(ws)
    logger.info(f"Client connected ({len(connected_clients)} total)")

    try:
        # Send recent headlines on connect (newest first)
        init_batch = list(recent_headlines)[:50]
        if init_batch:
            await ws.send_json({"type": "init", "headlines": init_batch})

        # Send stats
        await ws.send_json({"type": "stats", "data": stats})

        # Send current trading status
        if _executor and _signal_manager:
            await ws.send_json({
                "type": "trading_status",
                "data": {
                    "enabled": _signal_manager.trading_enabled,
                    "mode": "PAPER" if cfg.PAPER_MODE else "LIVE",
                    "executor": _executor.get_status(),
                }
            })

        # Keep-alive loop
        while True:
            data = await ws.receive_text()
            # Handle client messages (e.g., ping)
            if data == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        connected_clients.discard(ws)
        logger.info(f"Client disconnected ({len(connected_clients)} total)")


async def broadcast_headline(headline_dict: dict):
    """Push a headline to all connected WebSocket clients."""
    if not connected_clients:
        return

    message = json.dumps({"type": "headline", "data": headline_dict})
    dead = set()

    for ws in connected_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)

    connected_clients.difference_update(dead)


async def broadcast_trading_event(event_type: str, data: dict):
    """Push a trading event to all connected WebSocket clients."""
    if not connected_clients:
        return

    message = json.dumps({"type": event_type, "data": data})
    dead = set()

    for ws in connected_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)

    connected_clients.difference_update(dead)


# ═══════════════════════════════════════════════════════════════
#  Dispatcher — Central Processing Pipeline (Original - Headlines)
# ═══════════════════════════════════════════════════════════════

async def dispatcher():
    """
    Reads from the headline queue, generates TTS audio,
    broadcasts to clients, and updates stats.
    """
    logger.info("Dispatcher online — processing headline queue")

    while True:
        try:
            headline: Headline = await headline_queue.get()
            h_dict = headline.to_dict()

            # ─── Store & Stats ──────────────────────────────────
            recent_headlines.appendleft(h_dict)
            stats["total"] += 1
            stats["by_source"][headline.source] = stats["by_source"].get(headline.source, 0) + 1
            stats["by_category"][headline.category] = stats["by_category"].get(headline.category, 0) + 1

            # ─── 1. Instant Text Broadcast ──────────────────────
            # Push to UI immediately with zero latency
            await broadcast_headline(h_dict)
            logger.info(
                f"▶ [{headline.source}] {headline.category} "
                f"({headline.sentiment}) → {len(connected_clients)} clients"
            )

            # ─── 2. Async TTS Generation ────────────────────────
            # Generate audio in background without blocking the UI
            async def _generate_and_push_audio(hd):
                try:
                    audio_file = await synthesize_headline(hd['title'])
                    audio_url = f"/static/audio/{audio_file}"
                    hd['audio_url'] = audio_url
                    
                    # Push 'audio_ready' event to clients
                    if connected_clients:
                        msg = json.dumps({"type": "audio_ready", "id": hd['id'], "audio_url": audio_url})
                        for ws in list(connected_clients):
                            try:
                                await ws.send_text(msg)
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"TTS skipped for {hd['id']}: {e}")

            asyncio.create_task(_generate_and_push_audio(h_dict))

        except Exception as e:
            logger.error(f"Dispatcher error: {e}")
            await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════
#  Trading Dispatcher — LLM Analysis Pipeline
# ═══════════════════════════════════════════════════════════════

async def trading_dispatcher():
    """
    Reads from the trading queue, sends qualifying headlines
    to DeepSeek R1 14B for analysis, and routes signals through
    the risk manager to the executor.
    """
    logger.info("Trading Dispatcher online — LLM analysis pipeline ready")

    llm_engine = await get_llm_engine()
    signal_mgr = get_signal_manager()

    while True:
        try:
            headline: Headline = await trading_queue.get()

            # Only analyze headlines with sufficient priority
            if headline.priority < cfg.MIN_PRIORITY_FOR_TRADING:
                continue

            # Skip if trading is disabled
            if not signal_mgr.trading_enabled:
                continue

            # Send to LLM for analysis (runs in background to not block queue)
            async def _analyze_and_signal(hl):
                try:
                    llm_signal = await llm_engine.analyze_headline(
                        headline_text=hl.title,
                        headline_id=hl.id,
                        source=hl.source,
                        category=hl.category,
                        sentiment=hl.sentiment,
                        priority=hl.priority
                    )

                    if llm_signal:
                        # Broadcast signal to UI regardless of trading decision
                        await broadcast_trading_event("trade_signal", {
                            "direction": llm_signal.direction,
                            "instrument": llm_signal.instrument,
                            "confidence": llm_signal.confidence,
                            "urgency": llm_signal.urgency,
                            "magnitude": llm_signal.magnitude,
                            "reasoning": llm_signal.reasoning,
                            "headline": llm_signal.headline_text[:120],
                            "is_tradeable": llm_signal.is_tradeable,
                            "timestamp": llm_signal.timestamp,
                        })

                        # Route through signal manager (risk checks)
                        if llm_signal.is_tradeable:
                            await signal_mgr.process_signal(llm_signal)

                except Exception as e:
                    logger.error(f"Trading analysis error: {e}")

            asyncio.create_task(_analyze_and_signal(headline))

        except Exception as e:
            logger.error(f"Trading dispatcher error: {e}")
            await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════
#  Trade Event Callback (Executor → WebSocket)
# ═══════════════════════════════════════════════════════════════

async def _trade_event_callback(event_type: str, data: dict):
    """Called by the executor when trades open/close/update."""
    await broadcast_trading_event(event_type, data)


# ═══════════════════════════════════════════════════════════════
#  Startup — Launch All Engines
# ═══════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    global _executor, _signal_manager

    stats["boot_time"] = datetime.now().isoformat()

    logger.info("═" * 60)
    logger.info("  ⚡ SQUAWK BOX v2.0 — News Engine + LLM Trading")
    logger.info("  Real-time aggregation • DeepSeek R1 AI • Auto-Trading")
    logger.info("═" * 60)

    # ─── Initialize Database ─────────────────────────────────
    db = await get_db()
    logger.info("✓ Database connected")

    # ─── Initialize Trading Engine ───────────────────────────
    _signal_manager = get_signal_manager()
    _executor = create_executor()
    _executor.on_trade_event(_trade_event_callback)

    mode = "📝 PAPER" if cfg.PAPER_MODE else "🔴 LIVE"
    logger.info(f"✓ Trading Engine: {mode} mode | Max positions: {cfg.MAX_OPEN_POSITIONS}")

    # ─── Initialize LLM Engine ───────────────────────────────
    llm = await get_llm_engine()
    llm_status = "✓ CONNECTED" if llm.is_healthy else "⚠ UNAVAILABLE (will retry)"
    logger.info(f"✓ LLM Engine ({cfg.OLLAMA_MODEL}): {llm_status}")

    # ─── Launch Core Tasks ───────────────────────────────────
    asyncio.create_task(dispatcher())                              # Headlines → UI
    asyncio.create_task(fast_rss_ingester(headline_queue, analyze_headline))   # Fast APIs (3s)
    asyncio.create_task(slow_rss_ingester(headline_queue, analyze_headline))   # Bulk RSS (30s)
    asyncio.create_task(sec_edgar_ingester(headline_queue, analyze_headline))  # SEC EDGAR

    # ─── Initialize Live Price Feed ──────────────────────────
    from price_feed import get_price_feed
    price_feed = await get_price_feed()
    asyncio.create_task(price_feed.run_refresh_loop())             # Background price refresh
    logger.info(f"✓ Live Price Feed: {price_feed.get_status()['live_count']}/{price_feed.get_status()['total_instruments']} instruments online")

    # ─── Launch Trading Tasks ────────────────────────────────
    asyncio.create_task(trading_dispatcher())                      # Headlines → LLM → Signals
    asyncio.create_task(execution_loop(_executor))                 # Signals → Trades
    asyncio.create_task(price_monitor_loop(_executor))             # SL/TP monitoring

    # ─── Optional: Telegram ──────────────────────────────────
    api_id = os.getenv('TG_API_ID')
    api_hash = os.getenv('TG_API_HASH')
    if api_id and api_hash:
        try:
            from ingestion import telegram_ingester
            asyncio.create_task(
                telegram_ingester(headline_queue, analyze_headline, int(api_id), api_hash)
            )
            logger.info("✓ Telegram Ingester: ENABLED")
        except Exception as e:
            logger.warning(f"  Telegram Ingester: DISABLED ({e})")
    else:
        logger.info("  Telegram Ingester: DISABLED (no credentials)")

    logger.info("─" * 60)
    logger.info("  Dashboard:     http://localhost:8000")
    logger.info("  Trading API:   http://localhost:8000/api/trading/status")
    logger.info(f"  Auto-Trading:  {'ENABLED' if cfg.TRADING_ENABLED else 'DISABLED'}")
    logger.info("─" * 60)


# ═══════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
