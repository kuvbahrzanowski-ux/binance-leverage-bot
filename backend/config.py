"""
config.py – Centralna konfiguracja bota
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Binance ──────────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET    = os.getenv("BINANCE_TESTNET", "True").lower() == "true"
DATABASE_URL       = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")

# Fix Render/Supabase postgres:// prefix issue for SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Force connection pooler (IPv4) for Supabase project to avoid Render IPv6 limitation
if "db.qtfwkxmtrfchgmkxaduu.supabase.co" in DATABASE_URL:
    DATABASE_URL = "postgresql://postgres.qtfwkxmtrfchgmkxaduu:S95CVcjViCTfR7nk@aws-0-eu-west-3.pooler.supabase.com:6543/postgres"

# ── Handel ───────────────────────────────────────────────────
TRADING_MODE       = os.getenv("TRADING_MODE", "SIGNAL_ONLY")   # SIGNAL_ONLY | AUTO_TRADE
MAX_POSITION_USDT  = float(os.getenv("MAX_POSITION_USDT", "100"))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
DEFAULT_LEVERAGE   = int(os.getenv("DEFAULT_LEVERAGE", "10"))
MAX_LEVERAGE       = int(os.getenv("MAX_LEVERAGE", "100"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "10.0"))

# ── Symbole ──────────────────────────────────────────────────
SYMBOLS = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,XRPUSDT").split(",")

# ── Serwer ───────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# ── Stałe analizy ────────────────────────────────────────────
SIGNAL_THRESHOLD        = 60   # Minimalny score do sygnału
HIGH_CONFIDENCE_THRESHOLD = 80  # Wysoka pewność sygnału
ANALYZE_INTERVAL_SEC    = 900  # Co 15 minut
AUTO_TRADE_COUNTDOWN_SEC = 10  # Odliczanie przed zleceniem

# ── Timeframy ────────────────────────────────────────────────
TIMEFRAMES = {
    "entry":  "1m",
    "main":   "5m",
    "medium": "15m",
    "trend":  "1h",
    "macro":  "4h",
}

# ── Wskaźniki ────────────────────────────────────────────────
RSI_PERIOD          = 14
MACD_FAST           = 12
MACD_SLOW           = 26
MACD_SIGNAL         = 9
BB_PERIOD           = 20
BB_STD              = 2.0
EMA_PERIODS         = [9, 21, 50, 200]
STOCH_RSI_PERIOD    = 14
ATR_PERIOD          = 14
