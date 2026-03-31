# price_feed.py
"""
Live price feed aggregator for all trading instruments.
Fetches real-time prices from multiple free sources:
  - Binance REST API: BTC, ETH, GOLD (XAUUSDT)
  - Yahoo Finance: NQ, ES, OIL (CL=F), SPY, DXY

No API keys required. All endpoints are public.
"""

import asyncio
import aiohttp
import time
import logging
from typing import Dict, Optional

logger = logging.getLogger("squawkbox.prices")


# ═══════════════════════════════════════════════════════════════
#  Symbol Mapping
# ═══════════════════════════════════════════════════════════════

# Binance symbols (crypto + commodities)
BINANCE_SYMBOLS = {
    "BTC":  "BTCUSDT",
    "ETH":  "ETHUSDT",
}

# Yahoo Finance symbols (futures + equities)
YAHOO_SYMBOLS = {
    "NQ":   "NQ=F",      # Nasdaq 100 E-mini futures
    "ES":   "ES=F",      # S&P 500 E-mini futures
    "OIL":  "CL=F",      # Crude Oil WTI futures
    "SPY":  "SPY",        # S&P 500 ETF
    "DXY":  "DX-Y.NYB",  # US Dollar Index
    "GOLD": "GC=F",      # Gold futures
}

# All known symbols
ALL_INSTRUMENTS = {**{k: "binance" for k in BINANCE_SYMBOLS}, **{k: "yahoo" for k in YAHOO_SYMBOLS}}


# ═══════════════════════════════════════════════════════════════
#  Live Price Feed
# ═══════════════════════════════════════════════════════════════

class LivePriceFeed:
    """
    Aggregates live prices from Binance and Yahoo Finance.
    Caches prices and refreshes in background every few seconds.
    """

    def __init__(self, refresh_interval: float = 5.0):
        self._prices: Dict[str, float] = {}
        self._last_update: Dict[str, float] = {}
        self._refresh_interval = refresh_interval
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._errors: Dict[str, int] = {}

    async def start(self):
        """Initialize session and do first price fetch."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        self._running = True
        # Initial fetch
        await self._fetch_all()
        logger.info(f"✓ Live Price Feed started — tracking {len(ALL_INSTRUMENTS)} instruments")
        for inst, price in sorted(self._prices.items()):
            logger.info(f"  {inst:5s}: ${price:,.2f}")

    async def stop(self):
        self._running = False
        if self._session:
            await self._session.close()

    async def get_price(self, instrument: str) -> float:
        """
        Get the latest price for an instrument.
        Returns cached price if fresh enough, otherwise fetches live.
        """
        now = time.time()
        last = self._last_update.get(instrument, 0)

        # If cache is stale, fetch this specific instrument
        if now - last > self._refresh_interval * 2:
            source = ALL_INSTRUMENTS.get(instrument)
            if source == "binance":
                await self._fetch_binance_single(instrument)
            elif source == "yahoo":
                await self._fetch_yahoo_single(instrument)

        price = self._prices.get(instrument)
        if price is None:
            logger.warning(f"No price available for {instrument}")
            return 0.0
        return price

    def get_all_prices(self) -> Dict[str, float]:
        """Return all cached prices."""
        return self._prices.copy()

    # ─── Background refresh loop ─────────────────────────────

    async def run_refresh_loop(self):
        """Background task that continuously refreshes all prices."""
        while self._running:
            try:
                await self._fetch_all()
            except Exception as e:
                logger.error(f"Price refresh error: {e}")
            await asyncio.sleep(self._refresh_interval)

    # ─── Fetch all prices ────────────────────────────────────

    async def _fetch_all(self):
        """Fetch prices from all sources concurrently."""
        await asyncio.gather(
            self._fetch_binance_batch(),
            self._fetch_yahoo_batch(),
            return_exceptions=True
        )

    # ─── Binance ─────────────────────────────────────────────

    async def _fetch_binance_batch(self):
        """Fetch all Binance prices in a single batch call."""
        try:
            url = "https://api.binance.com/api/v3/ticker/price"
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Build a lookup map
                    price_map = {item["symbol"]: float(item["price"]) for item in data}

                    now = time.time()
                    for instrument, binance_symbol in BINANCE_SYMBOLS.items():
                        if binance_symbol in price_map:
                            self._prices[instrument] = price_map[binance_symbol]
                            self._last_update[instrument] = now
                            self._errors.pop(instrument, None)
                else:
                    logger.debug(f"Binance batch HTTP {resp.status}")
        except Exception as e:
            logger.debug(f"Binance batch fetch failed: {e}")

    async def _fetch_binance_single(self, instrument: str):
        """Fetch a single Binance price."""
        symbol = BINANCE_SYMBOLS.get(instrument)
        if not symbol:
            return

        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._prices[instrument] = float(data["price"])
                    self._last_update[instrument] = time.time()
        except Exception as e:
            logger.debug(f"Binance single fetch failed for {instrument}: {e}")

    # ─── Yahoo Finance ───────────────────────────────────────

    async def _fetch_yahoo_batch(self):
        """Fetch all Yahoo Finance prices using the chart endpoint."""
        now = time.time()
        tasks = []
        for instrument, yahoo_symbol in YAHOO_SYMBOLS.items():
            tasks.append(self._fetch_yahoo_single(instrument))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_yahoo_single(self, instrument: str):
        """Fetch a single Yahoo Finance price via the chart API."""
        yahoo_symbol = YAHOO_SYMBOLS.get(instrument)
        if not yahoo_symbol:
            return

        try:
            # Yahoo Finance v8 chart endpoint — returns latest price
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
                f"?interval=1m&range=1d&includePrePost=true"
            )
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("chart", {}).get("result", [])
                    if result:
                        meta = result[0].get("meta", {})
                        price = meta.get("regularMarketPrice", 0)
                        if not price:
                            price = meta.get("previousClose", 0)
                        if price and price > 0:
                            self._prices[instrument] = float(price)
                            self._last_update[instrument] = time.time()
                            self._errors.pop(instrument, None)
                            return

                    # Fallback: try parsing from the indicators
                    if result:
                        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                        # Get last non-None close
                        valid_closes = [c for c in closes if c is not None]
                        if valid_closes:
                            self._prices[instrument] = float(valid_closes[-1])
                            self._last_update[instrument] = time.time()
                            self._errors.pop(instrument, None)
                            return

                elif resp.status == 404:
                    logger.debug(f"Yahoo 404 for {yahoo_symbol}")
                else:
                    logger.debug(f"Yahoo HTTP {resp.status} for {yahoo_symbol}")

        except Exception as e:
            err_count = self._errors.get(instrument, 0) + 1
            self._errors[instrument] = err_count
            if err_count <= 3:
                logger.debug(f"Yahoo fetch failed for {instrument} ({yahoo_symbol}): {e}")

    # ─── Status ──────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return feed health status."""
        now = time.time()
        instruments = {}
        for inst in ALL_INSTRUMENTS:
            price = self._prices.get(inst)
            age = now - self._last_update.get(inst, 0)
            instruments[inst] = {
                "price": price,
                "age_seconds": round(age, 1) if price else None,
                "source": ALL_INSTRUMENTS[inst],
                "healthy": price is not None and age < 60,
            }
        return {
            "total_instruments": len(ALL_INSTRUMENTS),
            "live_count": sum(1 for i in instruments.values() if i["healthy"]),
            "instruments": instruments,
        }


# ═══════════════════════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════════════════════

_feed_instance: Optional[LivePriceFeed] = None


async def get_price_feed() -> LivePriceFeed:
    global _feed_instance
    if _feed_instance is None:
        _feed_instance = LivePriceFeed(refresh_interval=5.0)
        await _feed_instance.start()
    return _feed_instance
