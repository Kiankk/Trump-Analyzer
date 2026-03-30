# server.py
"""
Financial Squawk Box — FastAPI Backend
Real-time financial news aggregation, AI filtering, and TTS audio squawk.
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

from ingestion import Headline, headline_queue, rss_ingester, sec_edgar_ingester
from filters import analyze_headline
from tts_engine import synthesize_headline

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

app = FastAPI(title="Squawk Box", version="1.0.0")

# ─── State ──────────────────────────────────────────────────────
recent_headlines: deque = deque(maxlen=200)
connected_clients: Set[WebSocket] = set()
stats = {
    "total": 0,
    "by_source": {},
    "by_category": {},
    "boot_time": None
}

# ─── Static Files ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
AUDIO_DIR = os.path.join(STATIC_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ═══════════════════════════════════════════════════════════════
#  HTTP Routes
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


# ═══════════════════════════════════════════════════════════════
#  WebSocket
# ═══════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Real-time headline streaming to browser clients."""
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


# ═══════════════════════════════════════════════════════════════
#  Dispatcher — Central Processing Pipeline
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

            # ─── TTS Generation ─────────────────────────────────
            try:
                audio_file = await synthesize_headline(headline.title)
                h_dict['audio_url'] = f"/static/audio/{audio_file}"
            except Exception as e:
                logger.warning(f"TTS skipped: {e}")
                h_dict['audio_url'] = None

            # ─── Store ──────────────────────────────────────────
            recent_headlines.appendleft(h_dict)

            # ─── Stats ──────────────────────────────────────────
            stats["total"] += 1
            stats["by_source"][headline.source] = stats["by_source"].get(headline.source, 0) + 1
            stats["by_category"][headline.category] = stats["by_category"].get(headline.category, 0) + 1

            # ─── Broadcast ──────────────────────────────────────
            await broadcast_headline(h_dict)

            logger.info(
                f"▶ [{headline.source}] {headline.category} "
                f"({headline.sentiment}) → {len(connected_clients)} clients"
            )

        except Exception as e:
            logger.error(f"Dispatcher error: {e}")
            await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════
#  Startup — Launch All Engines
# ═══════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    stats["boot_time"] = datetime.now().isoformat()

    logger.info("═" * 56)
    logger.info("  ⚡ SQUAWK BOX — Financial News Engine v1.0")
    logger.info("  Real-time aggregation • AI filters • Audio squawk")
    logger.info("═" * 56)

    # Launch core tasks
    asyncio.create_task(dispatcher())
    asyncio.create_task(rss_ingester(headline_queue, analyze_headline))
    asyncio.create_task(sec_edgar_ingester(headline_queue, analyze_headline))

    # Optional: Telegram (requires credentials in .env)
    # Note: If main.py is running, the Telegram session may be locked
    api_id = os.getenv('TG_API_ID')
    api_hash = os.getenv('TG_API_HASH')
    if api_id and api_hash:
        try:
            from ingestion import telegram_ingester
            asyncio.create_task(
                telegram_ingester(headline_queue, analyze_headline, int(api_id), api_hash)
            )
            logger.info("Telegram Ingester: ENABLED")
        except Exception as e:
            logger.warning(f"Telegram Ingester: DISABLED ({e})")
    else:
        logger.info("Telegram Ingester: DISABLED (no credentials)")

    logger.info("─" * 56)
    logger.info("  Dashboard: http://localhost:8000")
    logger.info("─" * 56)


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
