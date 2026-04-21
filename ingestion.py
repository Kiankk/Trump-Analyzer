# ingestion.py
"""
Multi-source data ingestion engine for the Financial Squawk Box.
Aggregates headlines from RSS feeds, Telegram channels, SEC EDGAR, and Finnhub.
Each ingester is an async task that pushes normalized Headline objects to a shared queue.
"""

import asyncio
import aiohttp
import feedparser
import hashlib
import logging
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, Callable

logger = logging.getLogger("squawkbox.ingestion")


# ═══════════════════════════════════════════════════════════════
#  Headline Data Model
# ═══════════════════════════════════════════════════════════════

@dataclass
class Headline:
    id: str
    timestamp: str
    source: str          # FIN_JUICE, TELEGRAM, WEB/RSS, SEC_EDGAR
    category: str        # TRUMP_POLICY, FED_MACRO, GEO_ESCALATION, etc.
    sentiment: str       # BULLISH, BEARISH, NEUTRAL
    title: str
    url: Optional[str] = None
    ticker: Optional[str] = None
    audio_url: Optional[str] = None
    priority: int = 0    # 0=normal, 1=high, 2=critical

    def to_dict(self):
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
#  Shared State
# ═══════════════════════════════════════════════════════════════

headline_queue: asyncio.Queue = asyncio.Queue()
trading_queue: asyncio.Queue = asyncio.Queue()   # NEW — fan-out for trading engine
seen_ids: set = set()


async def fan_out(headline):
    """Push a headline to both the UI queue and the trading queue."""
    await headline_queue.put(headline)
    await trading_queue.put(headline)


def _make_id(text: str) -> str:
    """Generate a short dedup ID from text."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════
RSS_FEEDS_FAST = {
    # FinancialJuice — fast breaking news
    "https://www.financialjuice.com/feed.ashx?xy=rss": "FIN_JUICE",
}

RSS_FEEDS_SLOW = {
    # Trump & Policy
    "https://news.google.com/rss/search?q=%22Donald+Trump%22+OR+POTUS+OR+Tariffs+when:1h": "WEB/RSS",
    # Fed & Macro
    "https://news.google.com/rss/search?q=Federal+Reserve+OR+CPI+OR+NFP+OR+Powell+when:1h": "WEB/RSS",
    # General Finance
    "https://finance.yahoo.com/news/rssindex": "WEB/RSS",
    # Geopolitics
    "https://news.google.com/rss/search?q=geopolitics+OR+military+OR+war+OR+sanctions+when:1h": "WEB/RSS",
    # Commodities
    "https://news.google.com/rss/search?q=OPEC+OR+oil+price+OR+gold+price+OR+crude+when:1h": "WEB/RSS",
}

TELEGRAM_CHANNELS = [
    'newrulesgeo', 'rybar_in_english', 'intelslava',
    'ClashReport', 'worldnews'
]


# ═══════════════════════════════════════════════════════════════
#  Helper: Fetch a single RSS/Atom feed
# ═══════════════════════════════════════════════════════════════

async def _fetch_feed(session: aiohttp.ClientSession, url: str):
    """Fetch and parse a single RSS/Atom feed. Returns parsed feed or None."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                return feedparser.parse(await resp.text())
            else:
                logger.debug(f"RSS HTTP {resp.status} for {url[:60]}")
    except asyncio.TimeoutError:
        logger.debug(f"RSS timeout: {url[:60]}")
    except Exception as e:
        logger.debug(f"RSS error for {url[:60]}: {e}")
    return None


# ═══════════════════════════════════════════════════════════════
#  RSS Ingester
# ═══════════════════════════════════════════════════════════════

async def _run_rss_loop(feeds_dict: dict, sleep_time: int, name: str, analyze_fn: Callable):
    """Internal loop to fetch feeds continuously."""
    logger.info(f"{name} started — monitoring {len(feeds_dict)} feeds every {sleep_time}s")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        while True:
            try:
                fetch_tasks = [_fetch_feed(session, url) for url in feeds_dict]
                results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                
                for (url, source_label), result in zip(feeds_dict.items(), results):
                    if isinstance(result, Exception) or not result:
                        continue
                    if not hasattr(result, 'entries'):
                        continue
                    
                    for entry in result.entries:
                        link = getattr(entry, 'link', '') or ''
                        title = getattr(entry, 'title', '') or ''
                        if not title:
                            continue
                        
                        clean_title = title
                        if source_label == 'FIN_JUICE' and clean_title.startswith('FinancialJuice: '):
                            clean_title = clean_title[len('FinancialJuice: '):]
                        
                        hid = _make_id(link or clean_title)
                        if hid in seen_ids:
                            continue
                        seen_ids.add(hid)
                        
                        category, sentiment, priority = analyze_fn(clean_title, source=source_label)
                        if category:
                            headline = Headline(
                                id=hid,
                                timestamp=datetime.now().strftime('%H:%M:%S'),
                                source=source_label,
                                category=category,
                                sentiment=sentiment,
                                title=clean_title[:200].strip(),
                                url=link or None,
                                priority=priority
                            )
                            await fan_out(headline)
                            logger.info(f"[{source_label}] {category} | {clean_title[:80]}")
                            
            except Exception as e:
                logger.error(f"{name} cycle error: {e}")
            
            await asyncio.sleep(sleep_time)

async def fast_rss_ingester(queue: asyncio.Queue, analyze_fn: Callable):
    """Polls high-priority API feeds (FinancialJuice) aggressively."""
    await _run_rss_loop(RSS_FEEDS_FAST, sleep_time=3, name="Fast RSS Ingester", analyze_fn=analyze_fn)

async def slow_rss_ingester(queue: asyncio.Queue, analyze_fn: Callable):
    """Polls bulk aggregator feeds (Google) gently to avoid rate limits."""
    await _run_rss_loop(RSS_FEEDS_SLOW, sleep_time=30, name="Slow RSS Ingester", analyze_fn=analyze_fn)


# ═══════════════════════════════════════════════════════════════
#  SEC EDGAR Ingester
# ═══════════════════════════════════════════════════════════════

SEC_EDGAR_ATOM = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&dateb="
    "&owner=include&count=20&search_text=&start=0&output=atom"
)

async def sec_edgar_ingester(queue: asyncio.Queue, analyze_fn: Callable):
    """
    Polls SEC EDGAR for latest 8-K filings (material corporate events).
    Uses the official Atom feed — no API key required.
    """
    headers = {
        'User-Agent': 'SquawkBox/1.0 (squawkbox@proton.me)',
        'Accept': 'application/atom+xml,application/xml'
    }
    logger.info("SEC EDGAR Ingester started — polling 8-K filings every 30s")
    
    async with aiohttp.ClientSession(headers=headers) as session:
        while True:
            try:
                feed = await _fetch_feed(session, SEC_EDGAR_ATOM)
                if feed and hasattr(feed, 'entries'):
                    for entry in feed.entries:
                        title = getattr(entry, 'title', '') or ''
                        link = getattr(entry, 'link', '') or ''
                        if not title:
                            continue
                        
                        hid = _make_id(link or title)
                        if hid in seen_ids:
                            continue
                        seen_ids.add(hid)
                        
                        # SEC filings are always categorized as SEC_FILING
                        _, sentiment, _ = analyze_fn(title, source='SEC_EDGAR')
                        headline = Headline(
                            id=hid,
                            timestamp=datetime.now().strftime('%H:%M:%S'),
                            source='SEC_EDGAR',
                            category='SEC_FILING',
                            sentiment=sentiment or 'NEUTRAL',
                            title=f"SEC 8-K: {title[:180].strip()}",
                            url=link or None,
                            priority=1
                        )
                        await fan_out(headline)
                        logger.info(f"[SEC_EDGAR] {title[:80]}")
                        
            except Exception as e:
                logger.debug(f"SEC EDGAR error: {e}")
            
            await asyncio.sleep(30)


# ═══════════════════════════════════════════════════════════════
#  Telegram Ingester
# ═══════════════════════════════════════════════════════════════

async def telegram_ingester(queue: asyncio.Queue, analyze_fn: Callable,
                             api_id: int, api_hash: str):
    """
    Listens to Telegram channels via MTProto.
    Requires Telethon and valid Telegram API credentials.
    Reuses the existing 'terminal_session' if available to avoid re-authentication.
    """
    try:
        from telethon import TelegramClient, events
    except ImportError:
        logger.warning("Telethon not installed — Telegram ingester disabled")
        return
    
    # Reuse the existing session file from main.py (already authenticated)
    session_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'terminal_session'
    )
    
    # Check if existing session file exists
    if not os.path.exists(session_path + '.session'):
        logger.warning("Telegram session file not found — run main.py first to authenticate")
        return
    
    client = TelegramClient(session_path, api_id, api_hash)
    
    try:
        # Connect without prompting for phone number
        await client.connect()
        
        if not await client.is_user_authorized():
            logger.warning("Telegram session not authorized — run main.py first to authenticate")
            await client.disconnect()
            return
            
    except Exception as e:
        logger.error(f"Telegram connection failed (is main.py running?): {e}")
        return
    
    logger.info(f"Telegram Ingester started — listening to {len(TELEGRAM_CHANNELS)} channels")
    
    @client.on(events.NewMessage(chats=TELEGRAM_CHANNELS))
    async def _handler(event):
        text = event.message.message or ''
        if not text or len(text) < 10:
            return
        
        hid = _make_id(text)
        if hid in seen_ids:
            return
        seen_ids.add(hid)
        
        category, sentiment, priority = analyze_fn(text, source='TELEGRAM')
        if category:
            clean_text = text.replace('\n', ' | ')
            headline = Headline(
                id=hid,
                timestamp=datetime.now().strftime('%H:%M:%S'),
                source='TELEGRAM',
                category=category,
                sentiment=sentiment,
                title=clean_text[:200].strip(),
                priority=priority
            )
            await fan_out(headline)
            logger.info(f"[TELEGRAM] {category} | {clean_text[:80]}")
    
    await client.run_until_disconnected()
