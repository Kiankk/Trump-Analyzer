# signal_manager.py
"""
Signal Manager — the risk brain of the trading system.
Takes LLM signals and decides whether to trade them, how much to risk,
and enforces all safety guardrails.

Responsibilities:
- Confidence filtering
- Conflicting signal detection
- Cooldown enforcement
- Position sizing
- Daily loss limits
- Trade signal queuing
"""

import asyncio
import time
import uuid
import logging
from datetime import datetime, date
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict, field
from collections import deque

from llm_engine import LLMSignal
from database import get_db
import trading_config as cfg

logger = logging.getLogger("squawkbox.signals")


# ═══════════════════════════════════════════════════════════════
#  Trade Signal (output of signal manager)
# ═══════════════════════════════════════════════════════════════

@dataclass
class TradeSignal:
    """A validated, risk-checked trade signal ready for execution."""
    id: str
    signal_id: str              # Links back to LLMSignal
    instrument: str
    symbol: str                 # Broker symbol (e.g., BTCUSDT)
    direction: str              # LONG or SHORT
    confidence: float
    position_size_usd: float    # Dollar amount to trade
    stop_loss_pct: float        # Distance from entry
    take_profit_pct: float      # Distance from entry
    urgency: str
    magnitude: str
    reasoning: str
    headline_text: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
#  Signal Manager
# ═══════════════════════════════════════════════════════════════

class SignalManager:
    """
    Validates LLM signals against risk rules and converts them
    into executable TradeSignals.
    """

    def __init__(self):
        self._recent_signals: deque = deque(maxlen=100)  # Recent LLM signals for conflict detection
        self._cooldowns: Dict[str, float] = {}   # instrument → last_trade_timestamp
        self._signal_cooldowns: Dict[str, float] = {}  # instrument → last_signal_timestamp
        self._loss_cooldown_until: float = 0      # Global cooldown after loss
        self._daily_pnl: float = 0.0
        self._daily_trade_count: int = 0
        self._current_date: str = date.today().isoformat()
        self._open_position_count: int = 0
        self._open_instruments: set = set()       # Instruments currently in a position
        self._trading_enabled: bool = cfg.TRADING_ENABLED
        self._signal_queue: asyncio.Queue = asyncio.Queue()
        self._signal_throttle_sec: int = 300      # Only 1 signal per instrument per 5 min

        # Stats
        self._stats = {
            "signals_received": 0,
            "signals_passed": 0,
            "signals_rejected": 0,
            "rejection_reasons": {},
        }

    @property
    def trading_enabled(self) -> bool:
        return self._trading_enabled

    @trading_enabled.setter
    def trading_enabled(self, value: bool):
        self._trading_enabled = value
        logger.info(f"Trading {'ENABLED' if value else 'DISABLED'}")

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "daily_pnl": self._daily_pnl,
            "daily_trade_count": self._daily_trade_count,
            "open_positions": self._open_position_count,
            "trading_enabled": self._trading_enabled,
        }

    @property
    def signal_queue(self) -> asyncio.Queue:
        return self._signal_queue

    def _reset_daily(self):
        """Reset daily counters at midnight."""
        today = date.today().isoformat()
        if today != self._current_date:
            logger.info(f"New trading day: {today} — resetting daily counters")
            self._daily_pnl = 0.0
            self._daily_trade_count = 0
            self._current_date = today

    def _reject(self, reason: str, headline: str = "") -> None:
        """Log a rejection with reason tracking."""
        self._stats["signals_rejected"] += 1
        self._stats["rejection_reasons"][reason] = (
            self._stats["rejection_reasons"].get(reason, 0) + 1
        )
        logger.info(f"✗ REJECTED [{reason}]: {headline[:60]}")

    async def process_signal(self, llm_signal: LLMSignal) -> Optional[TradeSignal]:
        """
        Validate an LLM signal through all risk checks.
        Returns a TradeSignal if approved, None if rejected.
        """
        self._reset_daily()
        self._stats["signals_received"] += 1

        # Store for conflict detection
        self._recent_signals.append({
            "signal": llm_signal,
            "timestamp": time.time()
        })

        # Store in database regardless of trading decision
        db = await get_db()
        await db.insert_signal({
            "id": f"sig_{uuid.uuid4().hex[:10]}",
            "timestamp": llm_signal.timestamp,
            "headline_id": llm_signal.headline_id,
            "headline_text": llm_signal.headline_text,
            "source": llm_signal.source,
            "category": llm_signal.category,
            "direction": llm_signal.direction,
            "instrument": llm_signal.instrument,
            "confidence": llm_signal.confidence,
            "urgency": llm_signal.urgency,
            "magnitude": llm_signal.magnitude,
            "reasoning": llm_signal.reasoning,
            "was_traded": 0,
        })

        # ─── Gate 1: Master kill switch ──────────────────────
        if not self._trading_enabled:
            self._reject("TRADING_DISABLED", llm_signal.headline_text)
            return None

        # ─── Gate 2: Direction check ─────────────────────────
        if llm_signal.direction == 'NO_TRADE':
            self._reject("NO_TRADE_SIGNAL", llm_signal.headline_text)
            return None

        # ─── Gate 3: Confidence threshold ────────────────────
        if llm_signal.confidence < cfg.MIN_CONFIDENCE:
            self._reject(
                f"LOW_CONFIDENCE ({llm_signal.confidence:.2f} < {cfg.MIN_CONFIDENCE})",
                llm_signal.headline_text
            )
            return None

        # ─── Gate 4: Daily loss limit ────────────────────────
        if self._daily_pnl <= -cfg.MAX_DAILY_LOSS_USD:
            self._reject("DAILY_LOSS_LIMIT_HIT", llm_signal.headline_text)
            return None

        # ─── Gate 5: Max daily trades ────────────────────────
        if self._daily_trade_count >= cfg.MAX_DAILY_TRADES:
            self._reject("MAX_DAILY_TRADES", llm_signal.headline_text)
            return None

        # ─── Gate 6: Max open positions ──────────────────────
        if self._open_position_count >= cfg.MAX_OPEN_POSITIONS:
            self._reject("MAX_POSITIONS_REACHED", llm_signal.headline_text)
            return None

        # ─── Gate 7: Already in position on this instrument ──
        if llm_signal.instrument in self._open_instruments:
            self._reject(f"ALREADY_IN_{llm_signal.instrument}", llm_signal.headline_text)
            return None

        # ─── Gate 8: Instrument cooldown (since last TRADE) ──
        now = time.time()
        last_trade = self._cooldowns.get(llm_signal.instrument, 0)
        if now - last_trade < cfg.COOLDOWN_PER_INSTRUMENT_SEC:
            remaining = int(cfg.COOLDOWN_PER_INSTRUMENT_SEC - (now - last_trade))
            self._reject(f"TRADE_COOLDOWN_{remaining}s", llm_signal.headline_text)
            return None

        # ─── Gate 8.5: Signal throttle (same instrument flood) ─
        # Prevents acting on 20 headlines about the same topic
        last_signal = self._signal_cooldowns.get(llm_signal.instrument, 0)
        if now - last_signal < self._signal_throttle_sec:
            remaining = int(self._signal_throttle_sec - (now - last_signal))
            self._reject(f"SIGNAL_THROTTLE_{remaining}s", llm_signal.headline_text)
            return None

        # ─── Gate 9: Post-loss cooldown ──────────────────────
        if now < self._loss_cooldown_until:
            remaining = int(self._loss_cooldown_until - now)
            self._reject(f"LOSS_COOLDOWN_{remaining}s", llm_signal.headline_text)
            return None

        # ─── Gate 10: Conflicting signal detection ───────────
        conflict = self._check_conflicting_signals(llm_signal)
        if conflict:
            self._reject("CONFLICTING_SIGNALS", llm_signal.headline_text)
            return None

        # ─── Gate 11: Instrument must be configured ──────────
        inst_config = cfg.INSTRUMENT_CONFIG.get(llm_signal.instrument)
        if not inst_config:
            self._reject(f"UNKNOWN_INSTRUMENT_{llm_signal.instrument}", llm_signal.headline_text)
            return None

        # ═══ ALL GATES PASSED — Generate TradeSignal ═════════
        position_size = self._calculate_position_size(
            llm_signal.confidence, inst_config['max_position_usd']
        )
        stop_loss_pct = inst_config.get('stop_loss_pct', cfg.DEFAULT_STOP_LOSS_PCT)
        take_profit_pct = stop_loss_pct * cfg.DEFAULT_TAKE_PROFIT_RATIO

        # Adjust SL/TP based on magnitude
        if llm_signal.magnitude == 'LARGE':
            stop_loss_pct *= 1.5
            take_profit_pct *= 1.5
        elif llm_signal.magnitude == 'SMALL':
            stop_loss_pct *= 0.7
            take_profit_pct *= 0.7

        trade_signal = TradeSignal(
            id=f"ts_{uuid.uuid4().hex[:10]}",
            signal_id=llm_signal.headline_id,
            instrument=llm_signal.instrument,
            symbol=inst_config['symbol'],
            direction=llm_signal.direction,
            confidence=llm_signal.confidence,
            position_size_usd=round(position_size, 2),
            stop_loss_pct=round(stop_loss_pct, 3),
            take_profit_pct=round(take_profit_pct, 3),
            urgency=llm_signal.urgency,
            magnitude=llm_signal.magnitude,
            reasoning=llm_signal.reasoning,
            headline_text=llm_signal.headline_text,
        )

        self._stats["signals_passed"] += 1
        self._signal_cooldowns[llm_signal.instrument] = time.time()  # Throttle future signals
        logger.info(
            f"✓ SIGNAL APPROVED: {trade_signal.direction} {trade_signal.instrument} "
            f"${trade_signal.position_size_usd} | conf={trade_signal.confidence:.2f} "
            f"| SL={trade_signal.stop_loss_pct}% TP={trade_signal.take_profit_pct}%"
        )

        # Push to execution queue
        await self._signal_queue.put(trade_signal)
        return trade_signal

    def _check_conflicting_signals(self, new_signal: LLMSignal) -> bool:
        """
        Check if there are recent signals on the same instrument
        with the opposite direction within the conflict window.
        """
        now = time.time()
        for entry in self._recent_signals:
            sig = entry['signal']
            ts = entry['timestamp']

            if now - ts > cfg.CONFLICTING_SIGNAL_WINDOW_SEC:
                continue
            if sig.instrument != new_signal.instrument:
                continue
            if sig.direction == new_signal.direction:
                continue
            if sig.direction in ('LONG', 'SHORT') and new_signal.direction in ('LONG', 'SHORT'):
                logger.warning(
                    f"⚠ Conflicting signals on {new_signal.instrument}: "
                    f"{sig.direction} vs {new_signal.direction} within {cfg.CONFLICTING_SIGNAL_WINDOW_SEC}s"
                )
                return True
        return False

    def _calculate_position_size(self, confidence: float, max_usd: float) -> float:
        """Calculate position size based on confidence tier."""
        if confidence >= cfg.ULTRA_CONFIDENCE:
            return max_usd * cfg.POSITION_SIZE_TIERS["large"]
        elif confidence >= cfg.HIGH_CONFIDENCE:
            return max_usd * cfg.POSITION_SIZE_TIERS["medium"]
        else:
            return max_usd * cfg.POSITION_SIZE_TIERS["small"]

    # ─── Position tracking callbacks ─────────────────────────

    def on_trade_opened(self, instrument: str):
        """Called when executor opens a trade."""
        self._open_position_count += 1
        self._open_instruments.add(instrument)
        self._daily_trade_count += 1
        self._cooldowns[instrument] = time.time()

    def on_trade_closed(self, instrument: str, pnl: float):
        """Called when executor closes a trade."""
        self._open_position_count = max(0, self._open_position_count - 1)
        self._open_instruments.discard(instrument)
        self._daily_pnl += pnl

        if pnl < 0:
            self._loss_cooldown_until = time.time() + cfg.COOLDOWN_AFTER_LOSS_SEC
            logger.info(
                f"📉 Loss on {instrument}: ${pnl:.2f} — "
                f"cooldown {cfg.COOLDOWN_AFTER_LOSS_SEC}s"
            )

    def reset_positions(self):
        """Reset tracking (e.g., after emergency close-all)."""
        self._open_position_count = 0
        self._open_instruments.clear()


# ═══════════════════════════════════════════════════════════════
#  Singleton
# ═══════════════════════════════════════════════════════════════

_manager_instance: Optional[SignalManager] = None


def get_signal_manager() -> SignalManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = SignalManager()
    return _manager_instance
