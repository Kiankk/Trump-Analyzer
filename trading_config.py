# trading_config.py
"""
Central configuration for the LLM-powered news trading system.
All tunable parameters live here — edit this file to adjust behavior.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ═══════════════════════════════════════════════════════════════
#  Ollama / LLM Configuration
# ═══════════════════════════════════════════════════════════════

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:14b")
OLLAMA_TIMEOUT = 60            # seconds — R1 thinking can be slow
OLLAMA_MAX_CONCURRENT = 2      # max parallel LLM calls

# ═══════════════════════════════════════════════════════════════
#  Trading Mode
# ═══════════════════════════════════════════════════════════════

TRADING_ENABLED = True                          # Master kill switch
PAPER_MODE = True                               # True = simulated, False = live broker
EXECUTOR_TYPE = os.getenv("EXECUTOR", "paper")  # "paper" or "binance"

# ═══════════════════════════════════════════════════════════════
#  Signal Thresholds
# ═══════════════════════════════════════════════════════════════

MIN_CONFIDENCE = 0.75          # Minimum LLM confidence — higher bar for fast trades
HIGH_CONFIDENCE = 0.85         # Threshold for larger position size
ULTRA_CONFIDENCE = 0.93        # Threshold for maximum position size

# Only analyze headlines with these priority levels (from filters.py)
# 3 = CRITICAL (Fed, Macro, Trump), 2 = HIGH (Geo, Commodities, Flow), 1 = MEDIUM
# Set to 3 = only trade on the BIGGEST headlines that will actually move markets
MIN_PRIORITY_FOR_TRADING = 2

# ═══════════════════════════════════════════════════════════════
#  Risk Management
# ═══════════════════════════════════════════════════════════════

MAX_OPEN_POSITIONS = 3         # Max simultaneous open trades
MAX_DAILY_LOSS_USD = 500.0     # Daily loss circuit breaker ($)
MAX_DAILY_LOSS_PCT = 5.0       # Daily loss circuit breaker (% of starting equity)
MAX_DAILY_TRADES = 15          # Max trades per day (more room for scalps)

# Position sizing (fraction of max position)
POSITION_SIZE_TIERS = {
    "small":  0.30,   # confidence 0.75 – 0.84
    "medium": 0.60,   # confidence 0.85 – 0.92
    "large":  1.00,   # confidence 0.93+
}

# ─── SHORT-TERM SCALP SETTINGS ──────────────────────────────
# Tight stops, fast exits — we're trading the initial news reaction
DEFAULT_STOP_LOSS_PCT = 0.5     # 0.5% stop — tight for scalps
DEFAULT_TAKE_PROFIT_RATIO = 2.0 # TP = SL * 2 (1:2 risk:reward)
MAX_TRADE_DURATION_SEC = 3600   # AUTO-CLOSE after 60 minutes max
TRADE_DURATION_CHECK_SEC = 30   # Check trade duration every 30s

# Cooldowns
COOLDOWN_PER_INSTRUMENT_SEC = 120   # 2 min between trades on same instrument (faster)
COOLDOWN_AFTER_LOSS_SEC = 180       # 3 min cooldown after a losing trade
CONFLICTING_SIGNAL_WINDOW_SEC = 20  # Ignore if opposite signal within 20s

# ═══════════════════════════════════════════════════════════════
#  Instrument Configuration
# ═══════════════════════════════════════════════════════════════

# Paper trading starting balance
PAPER_STARTING_EQUITY = 10000.0

# Default position sizes per instrument (in units)
INSTRUMENT_CONFIG = {
    "BTC": {
        "symbol": "BTCUSDT",
        "max_position_usd": 2000.0,
        "stop_loss_pct": 2.0,
        "tick_size": 0.10,
    },
    "ETH": {
        "symbol": "ETHUSDT",
        "max_position_usd": 1500.0,
        "stop_loss_pct": 2.5,
        "tick_size": 0.01,
    },
    "NQ": {
        "symbol": "NQ",
        "max_position_usd": 3000.0,
        "stop_loss_pct": 1.0,
        "tick_size": 0.25,
    },
    "ES": {
        "symbol": "ES",
        "max_position_usd": 3000.0,
        "stop_loss_pct": 0.8,
        "tick_size": 0.25,
    },
    "GOLD": {
        "symbol": "XAUUSD",
        "max_position_usd": 1500.0,
        "stop_loss_pct": 1.5,
        "tick_size": 0.01,
    },
    "OIL": {
        "symbol": "CL",
        "max_position_usd": 1000.0,
        "stop_loss_pct": 2.0,
        "tick_size": 0.01,
    },
    "SPY": {
        "symbol": "SPY",
        "max_position_usd": 2000.0,
        "stop_loss_pct": 1.0,
        "tick_size": 0.01,
    },
    "DXY": {
        "symbol": "DX",
        "max_position_usd": 1000.0,
        "stop_loss_pct": 0.5,
        "tick_size": 0.01,
    },
}

# ═══════════════════════════════════════════════════════════════
#  Binance Configuration (for live trading)
# ═══════════════════════════════════════════════════════════════

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_SECRET", "")
BINANCE_TESTNET = True  # Use testnet by default

# ═══════════════════════════════════════════════════════════════
#  Database
# ═══════════════════════════════════════════════════════════════

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading.db")

# ═══════════════════════════════════════════════════════════════
#  Logging
# ═══════════════════════════════════════════════════════════════

LOG_TRADES_TO_FILE = True
TRADE_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.log")
