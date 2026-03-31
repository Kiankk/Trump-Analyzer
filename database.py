# database.py
"""
SQLite persistence layer for the trading system.
Stores signals, trades, and daily performance for analysis and backtesting.
Uses aiosqlite for non-blocking async operations.
"""

import os
import json
import asyncio
import aiosqlite
import logging
from datetime import datetime, date
from typing import Optional, List, Dict

import trading_config as cfg

logger = logging.getLogger("squawkbox.database")


class TradingDatabase:
    """Async SQLite database for trading data persistence."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or cfg.DB_PATH
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Initialize DB connection and create tables."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._create_tables()
        logger.info(f"Trading DB connected: {self.db_path}")

    async def close(self):
        if self._db:
            await self._db.close()

    async def _create_tables(self):
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                headline_id TEXT,
                headline_text TEXT,
                source TEXT,
                category TEXT,
                direction TEXT NOT NULL,
                instrument TEXT NOT NULL,
                confidence REAL NOT NULL,
                urgency TEXT,
                magnitude TEXT,
                reasoning TEXT,
                was_traded INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                signal_id TEXT,
                instrument TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                quantity REAL,
                position_usd REAL,
                stop_loss REAL,
                take_profit REAL,
                status TEXT DEFAULT 'OPEN',
                pnl REAL DEFAULT 0.0,
                pnl_pct REAL DEFAULT 0.0,
                opened_at TEXT DEFAULT (datetime('now')),
                closed_at TEXT,
                close_reason TEXT,
                headline_text TEXT,
                FOREIGN KEY (signal_id) REFERENCES signals(id)
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                starting_equity REAL,
                ending_equity REAL,
                total_pnl REAL DEFAULT 0.0,
                num_trades INTEGER DEFAULT 0,
                num_wins INTEGER DEFAULT 0,
                num_losses INTEGER DEFAULT 0,
                largest_win REAL DEFAULT 0.0,
                largest_loss REAL DEFAULT 0.0,
                signals_generated INTEGER DEFAULT 0,
                signals_traded INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT (datetime('now')),
                equity REAL NOT NULL,
                unrealized_pnl REAL DEFAULT 0.0,
                open_positions INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
            CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
            CREATE INDEX IF NOT EXISTS idx_trades_instrument ON trades(instrument);
            CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_snapshots(timestamp);
        """)
        await self._db.commit()

    # ─── Signals ──────────────────────────────────────────────

    async def insert_signal(self, signal: dict):
        """Store an LLM-generated signal."""
        await self._db.execute("""
            INSERT OR IGNORE INTO signals 
            (id, timestamp, headline_id, headline_text, source, category,
             direction, instrument, confidence, urgency, magnitude, reasoning, was_traded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal['id'], signal['timestamp'], signal.get('headline_id'),
            signal.get('headline_text', ''), signal.get('source', ''),
            signal.get('category', ''), signal['direction'], signal['instrument'],
            signal['confidence'], signal.get('urgency', ''),
            signal.get('magnitude', ''), signal.get('reasoning', ''),
            signal.get('was_traded', 0)
        ))
        await self._db.commit()

    async def get_recent_signals(self, limit: int = 50) -> List[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ─── Trades ───────────────────────────────────────────────

    async def insert_trade(self, trade: dict):
        """Store a new trade."""
        await self._db.execute("""
            INSERT INTO trades 
            (id, signal_id, instrument, symbol, direction, entry_price,
             quantity, position_usd, stop_loss, take_profit, status, headline_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade['id'], trade.get('signal_id'), trade['instrument'],
            trade['symbol'], trade['direction'], trade.get('entry_price'),
            trade.get('quantity'), trade.get('position_usd'),
            trade.get('stop_loss'), trade.get('take_profit'),
            trade.get('status', 'OPEN'), trade.get('headline_text', '')
        ))
        await self._db.commit()

    async def close_trade(self, trade_id: str, exit_price: float,
                          pnl: float, pnl_pct: float, reason: str):
        """Mark a trade as closed."""
        await self._db.execute("""
            UPDATE trades SET 
                exit_price = ?, pnl = ?, pnl_pct = ?,
                status = 'CLOSED', closed_at = datetime('now'),
                close_reason = ?
            WHERE id = ?
        """, (exit_price, pnl, pnl_pct, reason, trade_id))
        await self._db.commit()

    async def get_open_trades(self) -> List[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY opened_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_trade_history(self, limit: int = 100) -> List[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_today_trades(self) -> List[dict]:
        today = date.today().isoformat()
        cursor = await self._db.execute(
            "SELECT * FROM trades WHERE opened_at >= ? ORDER BY opened_at DESC",
            (today,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ─── Daily Stats ──────────────────────────────────────────

    async def get_today_pnl(self) -> float:
        today = date.today().isoformat()
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE opened_at >= ? AND status = 'CLOSED'",
            (today,)
        )
        row = await cursor.fetchone()
        return row['total'] if row else 0.0

    async def get_today_trade_count(self) -> int:
        today = date.today().isoformat()
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE opened_at >= ?",
            (today,)
        )
        row = await cursor.fetchone()
        return row['cnt'] if row else 0

    async def update_daily_stats(self, equity: float):
        """Update or create today's daily stats row."""
        today = date.today().isoformat()
        today_trades = await self.get_today_trades()
        closed_today = [t for t in today_trades if t['status'] == 'CLOSED']

        wins = [t for t in closed_today if t['pnl'] > 0]
        losses = [t for t in closed_today if t['pnl'] < 0]

        await self._db.execute("""
            INSERT INTO daily_stats (date, starting_equity, ending_equity, total_pnl,
                num_trades, num_wins, num_losses, largest_win, largest_loss)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                ending_equity = excluded.ending_equity,
                total_pnl = excluded.total_pnl,
                num_trades = excluded.num_trades,
                num_wins = excluded.num_wins,
                num_losses = excluded.num_losses,
                largest_win = excluded.largest_win,
                largest_loss = excluded.largest_loss
        """, (
            today, equity, equity,
            sum(t['pnl'] for t in closed_today),
            len(today_trades),
            len(wins), len(losses),
            max((t['pnl'] for t in wins), default=0.0),
            min((t['pnl'] for t in losses), default=0.0),
        ))
        await self._db.commit()

    # ─── Equity Snapshots ─────────────────────────────────────

    async def snapshot_equity(self, equity: float, unrealized: float, open_count: int):
        await self._db.execute(
            "INSERT INTO equity_snapshots (equity, unrealized_pnl, open_positions) VALUES (?, ?, ?)",
            (equity, unrealized, open_count)
        )
        await self._db.commit()

    async def get_equity_history(self, limit: int = 500) -> List[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM equity_snapshots ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ─── Performance Stats ────────────────────────────────────

    async def get_performance_stats(self) -> dict:
        """Calculate overall trading performance metrics."""
        cursor = await self._db.execute(
            "SELECT * FROM trades WHERE status = 'CLOSED'"
        )
        closed = [dict(r) for r in await cursor.fetchall()]

        if not closed:
            return {
                "total_trades": 0, "win_rate": 0, "total_pnl": 0,
                "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
                "largest_win": 0, "largest_loss": 0, "avg_pnl": 0,
            }

        wins = [t for t in closed if t['pnl'] > 0]
        losses = [t for t in closed if t['pnl'] < 0]
        total_pnl = sum(t['pnl'] for t in closed)
        gross_profit = sum(t['pnl'] for t in wins) if wins else 0
        gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0

        return {
            "total_trades": len(closed),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(gross_profit / len(wins), 2) if wins else 0,
            "avg_loss": round(gross_loss / len(losses), 2) if losses else 0,
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf'),
            "largest_win": round(max((t['pnl'] for t in wins), default=0), 2),
            "largest_loss": round(min((t['pnl'] for t in losses), default=0), 2),
            "avg_pnl": round(total_pnl / len(closed), 2),
        }


# Singleton
_db_instance: Optional[TradingDatabase] = None


async def get_db() -> TradingDatabase:
    global _db_instance
    if _db_instance is None:
        _db_instance = TradingDatabase()
        await _db_instance.connect()
    return _db_instance
