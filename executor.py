# executor.py
"""
Trade Executor — handles actual order placement and position management.

Two implementations:
  1. PaperExecutor — simulated trading with full P&L tracking (no real money)
  2. BinanceExecutor — live/testnet trading via Binance Futures API

Both share the same interface so the rest of the system doesn't care
which one is active.
"""

import asyncio
import uuid
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict, field

from signal_manager import TradeSignal, get_signal_manager
from database import get_db
import trading_config as cfg

logger = logging.getLogger("squawkbox.executor")


# ═══════════════════════════════════════════════════════════════
#  Position Data Model
# ═══════════════════════════════════════════════════════════════

@dataclass
class Position:
    """An open trading position."""
    id: str
    signal_id: str
    instrument: str
    symbol: str
    direction: str              # LONG or SHORT
    entry_price: float
    quantity: float             # Number of units
    position_usd: float        # Dollar value at entry
    stop_loss: float            # Absolute price
    take_profit: float          # Absolute price
    opened_at: str = field(default_factory=lambda: datetime.now().isoformat())
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    headline_text: str = ""
    high_watermark: float = 0.0
    trailing_active: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def update_pnl(self, current_price: float):
        """Recalculate unrealized P&L and update high watermark."""
        self.current_price = current_price
        if self.high_watermark == 0.0:
            self.high_watermark = current_price

        if self.direction == 'LONG':
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
            if current_price > self.high_watermark:
                self.high_watermark = current_price
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity
            if current_price < self.high_watermark:
                self.high_watermark = current_price

    def should_stop_loss(self, current_price: float) -> bool:
        if self.direction == 'LONG':
            return current_price <= self.stop_loss
        return current_price >= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        if self.direction == 'LONG':
            return current_price >= self.take_profit
        return current_price <= self.take_profit


# ═══════════════════════════════════════════════════════════════
#  Abstract Base Executor
# ═══════════════════════════════════════════════════════════════

class BaseExecutor(ABC):
    """Interface that all executors must implement."""

    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.equity: float = cfg.PAPER_STARTING_EQUITY
        self.realized_pnl: float = 0.0
        self._trade_callbacks = []

    def on_trade_event(self, callback):
        """Register a callback for trade events (for WebSocket broadcasting)."""
        self._trade_callbacks.append(callback)

    async def _notify(self, event_type: str, data: dict):
        """Notify all registered callbacks."""
        for cb in self._trade_callbacks:
            try:
                await cb(event_type, data)
            except Exception as e:
                logger.error(f"Trade callback error: {e}")

    @abstractmethod
    async def execute_signal(self, signal: TradeSignal) -> Optional[Position]:
        """Execute a trade signal. Returns a Position if successful."""
        pass

    @abstractmethod
    async def close_position(self, position_id: str, reason: str = "MANUAL") -> Optional[float]:
        """Close a position. Returns realized P&L."""
        pass

    @abstractmethod
    async def close_all(self, reason: str = "EMERGENCY") -> float:
        """Close all positions. Returns total realized P&L."""
        pass

    @abstractmethod
    async def update_prices(self):
        """Update current prices and check SL/TP for all positions."""
        pass

    def get_open_positions(self) -> List[dict]:
        return [p.to_dict() for p in self.positions.values()]

    def get_status(self) -> dict:
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return {
            "mode": "PAPER" if cfg.PAPER_MODE else "LIVE",
            "equity": round(self.equity, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "total_pnl": round(self.realized_pnl + total_unrealized, 2),
            "open_positions": len(self.positions),
            "positions": self.get_open_positions(),
        }


# ═══════════════════════════════════════════════════════════════
#  Paper Executor — Simulated Trading
# ═══════════════════════════════════════════════════════════════

class PaperExecutor(BaseExecutor):
    """
    Simulated executor that tracks trades without real money.
    Uses live price data from Binance + Yahoo Finance for realistic P&L.
    """

    def __init__(self):
        super().__init__()
        self._price_feed = None
        logger.info(
            f"📝 Paper Executor initialized — starting equity: ${self.equity:,.2f}"
        )

    async def _ensure_feed(self):
        """Lazily initialize the price feed."""
        if self._price_feed is None:
            from price_feed import get_price_feed
            self._price_feed = await get_price_feed()

    async def _get_price(self, instrument: str) -> float:
        """Get current live price for any instrument."""
        await self._ensure_feed()
        price = await self._price_feed.get_price(instrument)
        if price <= 0:
            logger.warning(f"Zero price for {instrument} — skipping")
        return price

    async def execute_signal(self, signal: TradeSignal) -> Optional[Position]:
        """Simulate opening a position at current market price."""
        try:
            current_price = await self._get_price(signal.instrument)

            # Calculate quantity from USD position size
            quantity = signal.position_size_usd / current_price

            # Calculate SL/TP prices
            if signal.direction == 'LONG':
                stop_loss = current_price * (1 - signal.stop_loss_pct / 100)
                take_profit = current_price * (1 + signal.take_profit_pct / 100)
            else:
                stop_loss = current_price * (1 + signal.stop_loss_pct / 100)
                take_profit = current_price * (1 - signal.take_profit_pct / 100)

            position = Position(
                id=f"pos_{uuid.uuid4().hex[:10]}",
                signal_id=signal.signal_id,
                instrument=signal.instrument,
                symbol=signal.symbol,
                direction=signal.direction,
                entry_price=current_price,
                quantity=quantity,
                position_usd=signal.position_size_usd,
                stop_loss=round(stop_loss, 4),
                take_profit=round(take_profit, 4),
                current_price=current_price,
                headline_text=signal.headline_text,
            )

            self.positions[position.id] = position

            # Notify signal manager
            get_signal_manager().on_trade_opened(signal.instrument)

            # Store in database
            db = await get_db()
            await db.insert_trade({
                "id": position.id,
                "signal_id": signal.signal_id,
                "instrument": signal.instrument,
                "symbol": signal.symbol,
                "direction": signal.direction,
                "entry_price": current_price,
                "quantity": quantity,
                "position_usd": signal.position_size_usd,
                "stop_loss": position.stop_loss,
                "take_profit": position.take_profit,
                "status": "OPEN",
                "headline_text": signal.headline_text,
            })

            logger.info(
                f"📈 PAPER TRADE OPENED: {signal.direction} {signal.instrument} "
                f"@ ${current_price:,.2f} | qty={quantity:.6f} | "
                f"SL=${position.stop_loss:,.2f} TP=${position.take_profit:,.2f} | "
                f"${signal.position_size_usd:,.2f}"
            )

            await self._notify("trade_executed", {
                "action": "OPEN",
                "position": position.to_dict(),
                "signal": signal.to_dict(),
            })

            return position

        except Exception as e:
            logger.error(f"Paper execution failed: {e}")
            return None

    async def close_position(self, position_id: str, reason: str = "MANUAL") -> Optional[float]:
        """Close a paper position and calculate realized P&L."""
        position = self.positions.get(position_id)
        if not position:
            logger.warning(f"Position {position_id} not found")
            return None

        current_price = await self._get_price(position.instrument)
        position.update_pnl(current_price)
        pnl = position.unrealized_pnl

        # Update equity
        self.equity += pnl
        self.realized_pnl += pnl

        # Remove from active positions
        del self.positions[position_id]

        # Notify signal manager
        get_signal_manager().on_trade_closed(position.instrument, pnl)

        # Update database
        db = await get_db()
        pnl_pct = (pnl / position.position_usd * 100) if position.position_usd else 0
        await db.close_trade(position_id, current_price, pnl, pnl_pct, reason)

        emoji = "💰" if pnl >= 0 else "💸"
        logger.info(
            f"{emoji} PAPER TRADE CLOSED [{reason}]: {position.direction} {position.instrument} "
            f"entry=${position.entry_price:,.2f} exit=${current_price:,.2f} | "
            f"P&L: ${pnl:,.2f} ({pnl_pct:+.2f}%) | Equity: ${self.equity:,.2f}"
        )

        await self._notify("trade_closed", {
            "action": "CLOSE",
            "position_id": position_id,
            "instrument": position.instrument,
            "direction": position.direction,
            "entry_price": position.entry_price,
            "exit_price": current_price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "reason": reason,
            "equity": round(self.equity, 2),
        })

        return pnl

    async def close_all(self, reason: str = "EMERGENCY") -> float:
        """Close all open positions."""
        total_pnl = 0.0
        position_ids = list(self.positions.keys())

        for pid in position_ids:
            pnl = await self.close_position(pid, reason)
            if pnl is not None:
                total_pnl += pnl

        get_signal_manager().reset_positions()
        logger.info(f"🛑 ALL POSITIONS CLOSED [{reason}] — Total P&L: ${total_pnl:,.2f}")
        return total_pnl

    async def update_prices(self):
        """Update all position prices and check SL/TP + max duration triggers."""
        positions_to_close = []
        now = time.time()

        for pid, position in self.positions.items():
            try:
                current_price = await self._get_price(position.instrument)
                position.update_pnl(current_price)

                # Update Trailing Stop
                if getattr(cfg, 'ENABLE_TRAILING_STOP', False):
                    activation_pct = cfg.TRAILING_STOP_ACTIVATION_PCT / 100.0
                    trail_dist = cfg.TRAILING_STOP_DISTANCE_PCT / 100.0
                    
                    if position.direction == 'LONG':
                        if (position.high_watermark - position.entry_price) / position.entry_price >= activation_pct:
                            new_sl = position.high_watermark * (1 - trail_dist)
                            if new_sl > position.stop_loss:
                                position.stop_loss = round(new_sl, 4)
                                position.trailing_active = True
                    else: # SHORT
                        if (position.entry_price - position.high_watermark) / position.entry_price >= activation_pct:
                            new_sl = position.high_watermark * (1 + trail_dist)
                            if new_sl < position.stop_loss:
                                position.stop_loss = round(new_sl, 4)
                                position.trailing_active = True

                # Check stop loss
                if position.should_stop_loss(current_price):
                    positions_to_close.append((pid, "STOP_LOSS"))
                    continue

                # Check take profit
                if position.should_take_profit(current_price):
                    positions_to_close.append((pid, "TAKE_PROFIT"))
                    continue

                # Check max trade duration (auto-close after 1 hour)
                from datetime import datetime
                opened = datetime.fromisoformat(position.opened_at)
                age_seconds = (datetime.now() - opened).total_seconds()
                if age_seconds >= cfg.MAX_TRADE_DURATION_SEC:
                    positions_to_close.append((pid, "MAX_DURATION"))
                    logger.info(
                        f"⏰ Auto-closing {position.instrument} — held {age_seconds/60:.0f} min "
                        f"(max {cfg.MAX_TRADE_DURATION_SEC/60:.0f} min)"
                    )
                    continue

            except Exception as e:
                logger.debug(f"Price update failed for {position.instrument}: {e}")

        # Close triggered positions
        for pid, reason in positions_to_close:
            await self.close_position(pid, reason)

        # Broadcast position updates
        if self.positions:
            await self._notify("position_update", {
                "positions": self.get_open_positions(),
                "equity": round(self.equity, 2),
                "unrealized_pnl": round(
                    sum(p.unrealized_pnl for p in self.positions.values()), 2
                ),
            })

    async def cleanup(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()


# ═══════════════════════════════════════════════════════════════
#  Price Monitor Loop
# ═══════════════════════════════════════════════════════════════

async def price_monitor_loop(executor: BaseExecutor):
    """
    Background task that continuously updates prices
    and checks SL/TP for all open positions.
    """
    logger.info("Price monitor started — checking positions every 5s")
    while True:
        try:
            if executor.positions:
                await executor.update_prices()

                # Periodic equity snapshot
                db = await get_db()
                unrealized = sum(p.unrealized_pnl for p in executor.positions.values())
                await db.snapshot_equity(executor.equity, unrealized, len(executor.positions))
        except Exception as e:
            logger.error(f"Price monitor error: {e}")

        await asyncio.sleep(5)


# ═══════════════════════════════════════════════════════════════
#  Execution Loop — Reads from signal queue
# ═══════════════════════════════════════════════════════════════

async def execution_loop(executor: BaseExecutor):
    """
    Reads approved TradeSignals from the signal manager queue
    and executes them via the executor.
    """
    signal_mgr = get_signal_manager()
    logger.info("Execution loop started — waiting for trade signals...")

    while True:
        try:
            signal: TradeSignal = await signal_mgr.signal_queue.get()

            logger.info(
                f"⚡ Executing: {signal.direction} {signal.instrument} "
                f"${signal.position_size_usd:,.2f} | {signal.reasoning[:60]}"
            )

            position = await executor.execute_signal(signal)

            if position:
                # Update signal in DB as traded
                db = await get_db()
                await db._db.execute(
                    "UPDATE signals SET was_traded = 1 WHERE headline_id = ?",
                    (signal.signal_id,)
                )
                await db._db.commit()

        except Exception as e:
            logger.error(f"Execution loop error: {e}")
            await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════
#  Factory
# ═══════════════════════════════════════════════════════════════

def create_executor() -> BaseExecutor:
    """Create the appropriate executor based on config."""
    if cfg.PAPER_MODE or cfg.EXECUTOR_TYPE == "paper":
        return PaperExecutor()
    else:
        # Future: BinanceExecutor, NinjaTraderExecutor
        logger.warning("Live executor not implemented — falling back to paper")
        return PaperExecutor()
