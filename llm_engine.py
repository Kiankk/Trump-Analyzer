# llm_engine.py
"""
DeepSeek R1 14B LLM Engine for real-time headline analysis.
Connects to a local Ollama instance and generates structured trade signals
from breaking financial news.

Key design decisions:
- Uses structured JSON output with strict schema enforcement
- Two-tier priority: critical headlines get immediate analysis, others are batched
- Semaphore limits concurrent LLM calls to prevent GPU overload
- Strips <think>...</think> reasoning tags from DeepSeek R1 output
"""

import asyncio
import aiohttp
import json
import re
import time
import hashlib
import logging
from typing import Optional, Dict, Tuple
from dataclasses import dataclass, asdict

import trading_config as cfg

logger = logging.getLogger("squawkbox.llm")


# ═══════════════════════════════════════════════════════════════
#  LLM Signal Data Model
# ═══════════════════════════════════════════════════════════════

@dataclass
class LLMSignal:
    """Structured output from the LLM analysis."""
    direction: str          # LONG, SHORT, NO_TRADE
    instrument: str         # BTC, NQ, ES, GOLD, OIL, etc.
    confidence: float       # 0.0 – 1.0
    urgency: str            # IMMEDIATE, WATCH, IGNORE
    magnitude: str          # SMALL, MEDIUM, LARGE
    reasoning: str          # Brief chain-of-thought
    headline_text: str      # Original headline
    headline_id: str        # Dedup ID
    source: str             # Where the headline came from
    category: str           # Filter category
    timestamp: str          # When analyzed

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_tradeable(self) -> bool:
        return (
            self.direction in ('LONG', 'SHORT')
            and self.confidence >= cfg.MIN_CONFIDENCE
            and self.urgency != 'IGNORE'
        )


# ═══════════════════════════════════════════════════════════════
#  System Prompt — The Brain
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are an elite NEWS SCALP TRADER at a top quantitative hedge fund.
You trade the INITIAL MARKET REACTION to breaking headlines — holding for 5 to 60 minutes MAX.

YOUR JOB: Determine if this headline will cause an IMMEDIATE, tradeable price move. 
You ONLY trade genuinely surprising, market-moving news — NOT routine commentary or old news.

INSTRUMENTS YOU CAN TRADE:
- BTC (Bitcoin) — risk-on/off, crypto regulation, macro surprises
- ETH (Ethereum) — same as BTC, higher beta
- NQ (Nasdaq futures) — tech, Fed policy, AI/semiconductor news
- ES (S&P 500 futures) — broad market, macro data, major policy
- GOLD (Gold) — safe haven, geopolitics, USD weakness, rate surprises
- OIL (Crude Oil) — OPEC, supply disruption, geopolitical conflict
- SPY (S&P 500 ETF) — same as ES
- DXY (US Dollar Index) — Fed hawkish/dovish, rate differentials

SCALPING RULES:
1. We ONLY trade news that will create a 0.3%+ move in the NEXT 5-60 MINUTES
2. We trade the INITIAL REACTION — the first impulse move, not the long-term trend
3. SURPRISE FACTOR is everything — expected/priced-in news = NO_TRADE
4. If the headline is vague, old, opinion-based, or routine → NO_TRADE
5. Pick the SINGLE instrument with the HIGHEST expected immediate move
6. Be EXTREMELY SELECTIVE — most headlines should be NO_TRADE

WHAT ACTUALLY MOVES MARKETS (trade these):
- Surprise Fed rate decisions or emergency statements
- Unexpected tariff/trade war announcements  
- Wars, military strikes, geopolitical escalations
- Major economic data MISSES (CPI, NFP, GDP far from consensus)
- Surprise presidential executive orders on markets/trade
- Emergency central bank interventions
- Major company earnings surprises (if relevant to an index)

WHAT DOES NOT (skip these):
- Routine speeches, scheduled data releases in-line with expectations
- General market commentary, analyst opinions
- News that's hours/days old, or already priced in
- Vague policy discussions without concrete action

CONFIDENCE CALIBRATION (be strict):
- 0.50-0.74: Possible move but uncertain → NO_TRADE (below our threshold)
- 0.75-0.84: Likely short-term move → small position scalp
- 0.85-0.92: High conviction immediate impact → medium position
- 0.93-1.00: Extreme (war, surprise rate cut, black swan) → full position

You MUST respond with ONLY a valid JSON object, no other text:
{
    "direction": "LONG" | "SHORT" | "NO_TRADE",
    "instrument": "BTC" | "ETH" | "NQ" | "ES" | "GOLD" | "OIL" | "SPY" | "DXY",
    "confidence": 0.0 to 1.0,
    "urgency": "IMMEDIATE" | "WATCH" | "IGNORE",
    "magnitude": "SMALL" | "MEDIUM" | "LARGE",
    "reasoning": "One sentence: what moves, how much, and why — in next 5-60 minutes"
}"""


# ═══════════════════════════════════════════════════════════════
#  LLM Engine
# ═══════════════════════════════════════════════════════════════

class LLMEngine:
    """Async engine for analyzing headlines via local DeepSeek R1 14B."""

    def __init__(self):
        self._semaphore = asyncio.Semaphore(cfg.OLLAMA_MAX_CONCURRENT)
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, LLMSignal] = {}  # headline_hash → signal
        self._stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "errors": 0,
            "avg_latency_ms": 0,
            "total_latency_ms": 0,
        }
        self._healthy = False

    async def start(self):
        """Initialize the HTTP session and verify Ollama is running."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=cfg.OLLAMA_TIMEOUT)
        )
        await self._health_check()

    async def stop(self):
        if self._session:
            await self._session.close()

    async def _health_check(self):
        """Verify Ollama is running and the model is available."""
        try:
            async with self._session.get(f"{cfg.OLLAMA_BASE_URL}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get('name', '') for m in data.get('models', [])]
                    # Check if our model is available (handle tag variations)
                    model_base = cfg.OLLAMA_MODEL.split(':')[0]
                    available = any(model_base in m for m in models)
                    if available:
                        self._healthy = True
                        logger.info(f"✓ Ollama connected — model '{cfg.OLLAMA_MODEL}' ready")
                    else:
                        logger.warning(
                            f"⚠ Ollama running but model '{cfg.OLLAMA_MODEL}' not found. "
                            f"Available: {models}. Run: ollama pull {cfg.OLLAMA_MODEL}"
                        )
                        self._healthy = False
                else:
                    logger.error(f"Ollama health check failed: HTTP {resp.status}")
                    self._healthy = False
        except Exception as e:
            logger.error(f"Cannot reach Ollama at {cfg.OLLAMA_BASE_URL}: {e}")
            self._healthy = False

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    def _make_cache_key(self, text: str) -> str:
        """Generate a cache key from headline text."""
        normalized = re.sub(r'\s+', ' ', text.lower().strip())
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    async def analyze_headline(
        self,
        headline_text: str,
        headline_id: str,
        source: str,
        category: str,
        sentiment: str,
        priority: int
    ) -> Optional[LLMSignal]:
        """
        Send a headline to DeepSeek R1 14B and get a structured trade signal.
        Returns None if analysis fails or Ollama is unreachable.
        """
        if not self._healthy:
            await self._health_check()
            if not self._healthy:
                logger.debug("Ollama unavailable — skipping LLM analysis")
                return None

        # Check cache
        cache_key = self._make_cache_key(headline_text)
        if cache_key in self._cache:
            self._stats["cache_hits"] += 1
            logger.debug(f"Cache hit for: {headline_text[:60]}")
            return self._cache[cache_key]

        # Acquire semaphore to limit concurrent calls
        async with self._semaphore:
            return await self._call_ollama(
                headline_text, headline_id, source, category, sentiment, cache_key
            )

    async def _call_ollama(
        self,
        headline_text: str,
        headline_id: str,
        source: str,
        category: str,
        sentiment: str,
        cache_key: str
    ) -> Optional[LLMSignal]:
        """Make the actual API call to Ollama."""
        user_prompt = (
            f"BREAKING HEADLINE:\n"
            f"\"{headline_text}\"\n\n"
            f"Source: {source}\n"
            f"Category: {category}\n"
            f"Initial Sentiment: {sentiment}\n\n"
            f"Analyze this headline and respond with the JSON trade signal."
        )

        payload = {
            "model": cfg.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 4096,       # Needs to be large to accommodate <think> reasoning tags
                "top_p": 0.9,
            }
        }

        start_time = time.perf_counter()

        try:
            async with self._session.post(
                f"{cfg.OLLAMA_BASE_URL}/api/chat",
                json=payload
            ) as resp:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._stats["total_calls"] += 1
                self._stats["total_latency_ms"] += elapsed_ms
                self._stats["avg_latency_ms"] = (
                    self._stats["total_latency_ms"] / self._stats["total_calls"]
                )

                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Ollama HTTP {resp.status}: {error_text[:200]}")
                    self._stats["errors"] += 1
                    return None

                data = await resp.json()
                raw_content = data.get("message", {}).get("content", "")

                # Parse the LLM response
                signal = self._parse_response(
                    raw_content, headline_text, headline_id,
                    source, category
                )

                if signal:
                    self._cache[cache_key] = signal
                    # Keep cache bounded
                    if len(self._cache) > 500:
                        oldest = list(self._cache.keys())[:100]
                        for k in oldest:
                            del self._cache[k]

                    logger.info(
                        f"🧠 LLM [{elapsed_ms:.0f}ms] "
                        f"{signal.direction} {signal.instrument} "
                        f"conf={signal.confidence:.2f} | {headline_text[:60]}"
                    )
                else:
                    logger.warning(f"LLM parse failed [{elapsed_ms:.0f}ms]: {raw_content[:200]}")
                    self._stats["errors"] += 1

                return signal

        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Ollama timeout after {elapsed_ms:.0f}ms")
            self._stats["errors"] += 1
            return None
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            self._stats["errors"] += 1
            return None

    def _parse_response(
        self,
        raw_content: str,
        headline_text: str,
        headline_id: str,
        source: str,
        category: str
    ) -> Optional[LLMSignal]:
        """
        Parse the LLM response into a structured LLMSignal.
        Handles DeepSeek R1's <think>...</think> reasoning blocks.
        """
        # Strip DeepSeek R1 thinking tags
        content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

        # Extract JSON from the response (handle markdown code blocks)
        # We capture from the first { to the last } natively
        json_match = re.search(r'(\{.*\})', content, re.DOTALL)
        if not json_match:
            return None
        else:
            json_str = json_match.group(1)

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            # Try to fix common JSON issues
            json_str = json_str.replace("'", '"')
            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError:
                return None

        # Validate and normalize fields
        direction = str(parsed.get('direction', 'NO_TRADE')).upper()
        if direction not in ('LONG', 'SHORT', 'NO_TRADE'):
            direction = 'NO_TRADE'

        instrument = str(parsed.get('instrument', 'BTC')).upper()
        valid_instruments = set(cfg.INSTRUMENT_CONFIG.keys())
        if instrument not in valid_instruments:
            # Try to match partial names
            for valid in valid_instruments:
                if valid in instrument or instrument in valid:
                    instrument = valid
                    break
            else:
                instrument = 'BTC'  # fallback

        try:
            confidence = float(parsed.get('confidence', 0))
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = 0.0

        urgency = str(parsed.get('urgency', 'WATCH')).upper()
        if urgency not in ('IMMEDIATE', 'WATCH', 'IGNORE'):
            urgency = 'WATCH'

        magnitude = str(parsed.get('magnitude', 'SMALL')).upper()
        if magnitude not in ('SMALL', 'MEDIUM', 'LARGE'):
            magnitude = 'SMALL'

        reasoning = str(parsed.get('reasoning', 'No reasoning provided'))[:300]

        return LLMSignal(
            direction=direction,
            instrument=instrument,
            confidence=confidence,
            urgency=urgency,
            magnitude=magnitude,
            reasoning=reasoning,
            headline_text=headline_text,
            headline_id=headline_id,
            source=source,
            category=category,
            timestamp=__import__('datetime').datetime.now().isoformat()
        )


# ═══════════════════════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════════════════════

_engine_instance: Optional[LLMEngine] = None


async def get_llm_engine() -> LLMEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = LLMEngine()
        await _engine_instance.start()
    return _engine_instance
