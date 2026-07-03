"""
config.py – Centralna konfiguracja bota (Swing Trading Edition)
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
TRADING_MODE       = os.getenv("TRADING_MODE", "ANALYZE")   # ANALYZE | ANALYZE_AND_TRADE
DEFAULT_LEVERAGE   = int(os.getenv("DEFAULT_LEVERAGE", "100"))
MAX_LEVERAGE       = int(os.getenv("MAX_LEVERAGE", "100"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "10.0"))

# ── Swing Trade – Wielkość Pozycji ───────────────────────────
MIN_POSITION_USDT     = float(os.getenv("MIN_POSITION_USDT", "30.0"))
MAX_POSITION_USDT     = float(os.getenv("MAX_POSITION_USDT", "100.0"))
DEFAULT_POSITION_USDT = float(os.getenv("DEFAULT_POSITION_USDT", "50.0"))
RISK_PER_TRADE_PCT    = float(os.getenv("RISK_PER_TRADE_PCT", "5.0"))  # 5% salda na trade

# ── Swing Trade – Dzienny Limit ──────────────────────────────
MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "15"))   # Zwiększony limit (min 5 trades dziennie)
MIN_DAILY_TRADES = int(os.getenv("MIN_DAILY_TRADES", "5"))    # Target min 5 trades dziennie

# ── Swing Trade – Cele TP/SL ─────────────────────────────────
# Przy 100x dźwigni: 2.5% ruch = 250% zysku z pozycji
SWING_TP_PCT = float(os.getenv("SWING_TP_PCT", "2.5"))     # TP: +2.5% ruch ceny (250% na pozycji)
SWING_SL_PCT = float(os.getenv("SWING_SL_PCT", "0.8"))     # SL: -0.8% ruch ceny (80% na pozycji)

# ── Symbole ──────────────────────────────────────────────────
SYMBOLS = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,XRPUSDT").split(",")

# ── Serwer ───────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# ── Stałe analizy ────────────────────────────────────────────
SIGNAL_THRESHOLD          = 60   # Obniżony próg dla częstszych sygnałów (at least 5/day)
HIGH_CONFIDENCE_THRESHOLD = 80   # Wysoka pewność sygnału
ANALYZE_INTERVAL_SEC      = 180  # Analiza co 3 minuty dla ciągłego skanowania rynku
AUTO_TRADE_COUNTDOWN_SEC  = 10   # Odliczanie przed zleceniem

# ── Timeframy (Częstsze Tradingi: 15m fast, 1h medium, 4h macro) ─
TIMEFRAMES = {
    "fast":        "15m",   # Szybki: 15m (RSI, MACD, świeczki)
    "medium":      "1h",    # Średni: 1h
    "macro":       "4h",    # Makro: 4h
    # Zachowane dla kompatybilnosci wstecznej
    "entry":       "5m",
    "main":        "15m",
    "trend":       "1h",
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
