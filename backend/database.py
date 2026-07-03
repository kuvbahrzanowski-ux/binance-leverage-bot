"""
database.py – SQLite modele i sesja (SQLAlchemy)
"""
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, Float, String,
    DateTime, Boolean, Text, JSON
)
from sqlalchemy.orm import DeclarativeBase, Session
import logging

logger = logging.getLogger(__name__)

from config import DATABASE_URL

logger = logging.getLogger(__name__)

import os

# Connect parameters: check_same_thread is SQLite-only
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    # Automatycznie stworz folder dla bazy SQLite, jesli nie istnieje
    db_file = DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_file)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args=connect_args)


class Base(DeclarativeBase):
    pass


class MLModelState(Base):
    """Przechowuje stan uczenia maszynowego (wagi, accuracy, logi)."""
    __tablename__ = "ml_model_state"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    weights     = Column(JSON, nullable=False)   # np. {"rsi": 12, "macd": 22, ...}
    accuracy    = Column(Float, default=0.5)
    history     = Column(JSON, default=list)     # Lista poprzednich wartosci accuracy
    logs        = Column(JSON, default=list)     # Wyjaśnienia słowne (decyzje)
    updated_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Signal(Base):
    """Wygenerowany sygnal (niezaleznie od zlecenia)."""
    __tablename__ = "signals"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    symbol      = Column(String(20), nullable=False, index=True)
    direction   = Column(String(5),  nullable=False)   # LONG | SHORT
    score       = Column(Integer,    nullable=False)
    confidence  = Column(String(10))                   # LOW | MEDIUM | HIGH
    entry_price = Column(Float,      nullable=False)
    tp_price    = Column(Float,      nullable=False)
    sl_price    = Column(Float,      nullable=False)
    atr         = Column(Float)
    leverage    = Column(Integer,    default=10)
    funding_rate = Column(Float,     default=0.0)
    reasons     = Column(JSON)
    indicators  = Column(JSON)
    status      = Column(String(20), default="PENDING")  # PENDING | WIN | LOSS | EXPIRED
    result_price = Column(Float,     nullable=True)
    pnl_pct     = Column(Float,      nullable=True)
    created_at  = Column(DateTime,   default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime,   nullable=True)


class Trade(Base):
    """Prawdziwe zlecenie na Binance Futures."""
    __tablename__ = "trades"

    id          = Column(Integer,    primary_key=True, autoincrement=True)
    signal_id   = Column(Integer,    nullable=True)
    symbol      = Column(String(20), nullable=False, index=True)
    direction   = Column(String(5),  nullable=False)
    order_id    = Column(String(50), nullable=True)
    sl_order_id = Column(String(50), nullable=True)
    tp_order_id = Column(String(50), nullable=True)
    quantity    = Column(Float,      nullable=False)
    entry_price = Column(Float,      nullable=False)
    tp_price    = Column(Float,      nullable=False)
    sl_price    = Column(Float,      nullable=False)
    close_price = Column(Float,      nullable=True)
    leverage    = Column(Integer,    default=10)
    pnl_usdt    = Column(Float,      nullable=True)
    pnl_pct     = Column(Float,      nullable=True)
    status      = Column(String(20), default="OPEN")   # OPEN | CLOSED_TP | CLOSED_SL | CLOSED_MANUAL
    close_reason = Column(String(30), nullable=True)
    opened_at   = Column(DateTime,   default=lambda: datetime.now(timezone.utc))
    closed_at   = Column(DateTime,   nullable=True)


class DailyStats(Base):
    """Statystyki dzienne."""
    __tablename__ = "daily_stats"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    date          = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    symbol        = Column(String(20), nullable=False)
    total_signals = Column(Integer, default=0)
    wins          = Column(Integer, default=0)
    losses        = Column(Integer, default=0)
    winrate       = Column(Float,   default=0.0)
    total_pnl     = Column(Float,   default=0.0)
    profit_factor = Column(Float,   default=0.0)
    avg_rr        = Column(Float,   default=0.0)
    max_drawdown  = Column(Float,   default=0.0)


class VirtualWallet(Base):
    """Wirtualny portfel tradera."""
    __tablename__ = "virtual_wallet"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    balance_usdt = Column(Float, default=1000.0)
    updated_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    """Tworzy tabele jesli nie istnieja."""
    Base.metadata.create_all(engine)
    logger.info("Baza danych zainicjalizowana")
    
    # Inicjalizacja salda poczatkowego wirtualnego portfela
    try:
        with Session(engine) as session:
            wallet = session.query(VirtualWallet).first()
            if not wallet:
                wallet = VirtualWallet(balance_usdt=1000.0)
                session.add(wallet)
                session.commit()
                logger.info("Utworzono wirtualny portfel z saldem poczatkowym 1000 USDT")
            
            # Seed mock signals to allow immediate ML training
            resolved_count = session.query(Signal).filter(Signal.status.in_(["WIN", "LOSS"])).count()
            if resolved_count < 10:
                logger.info("Seeding database with resolved signals for ML training...")
                from datetime import timedelta
                
                mock_signals = [
                    {"symbol": "BTCUSDT", "direction": "LONG", "score": 82, "status": "WIN", "pnl": 25.0, "rsi": 32.5, "macd": 0.002, "bb": 0.08, "vol": 2.1, "fund": -0.002},
                    {"symbol": "ETHUSDT", "direction": "SHORT", "score": 75, "status": "WIN", "pnl": 25.0, "rsi": 78.2, "macd": -0.005, "bb": 0.95, "vol": 1.8, "fund": 0.0015},
                    {"symbol": "XRPUSDT", "direction": "LONG", "score": 68, "status": "LOSS", "pnl": -80.0, "rsi": 45.1, "macd": -0.001, "bb": 0.35, "vol": 0.9, "fund": -0.0005},
                    {"symbol": "BTCUSDT", "direction": "LONG", "score": 88, "status": "WIN", "pnl": 25.0, "rsi": 28.0, "macd": 0.004, "bb": 0.03, "vol": 3.4, "fund": -0.003},
                    {"symbol": "ETHUSDT", "direction": "LONG", "score": 70, "status": "WIN", "pnl": 25.0, "rsi": 38.0, "macd": 0.001, "bb": 0.12, "vol": 1.6, "fund": -0.001},
                    {"symbol": "XRPUSDT", "direction": "SHORT", "score": 80, "status": "WIN", "pnl": 25.0, "rsi": 82.0, "macd": -0.008, "bb": 0.98, "vol": 2.5, "fund": 0.002},
                    {"symbol": "BTCUSDT", "direction": "SHORT", "score": 65, "status": "LOSS", "pnl": -80.0, "rsi": 62.4, "macd": 0.0005, "bb": 0.72, "vol": 1.1, "fund": 0.0008},
                    {"symbol": "ETHUSDT", "direction": "SHORT", "score": 85, "status": "WIN", "pnl": 25.0, "rsi": 84.1, "macd": -0.006, "bb": 0.99, "vol": 2.8, "fund": 0.0025},
                    {"symbol": "XRPUSDT", "direction": "LONG", "score": 72, "status": "WIN", "pnl": 25.0, "rsi": 30.5, "macd": 0.0015, "bb": 0.05, "vol": 1.9, "fund": -0.0015},
                    {"symbol": "BTCUSDT", "direction": "SHORT", "score": 76, "status": "LOSS", "pnl": -80.0, "rsi": 68.2, "macd": 0.001, "bb": 0.81, "vol": 1.3, "fund": 0.0004},
                    {"symbol": "ETHUSDT", "direction": "LONG", "score": 79, "status": "WIN", "pnl": 25.0, "rsi": 33.1, "macd": 0.003, "bb": 0.07, "vol": 2.2, "fund": -0.0022},
                    {"symbol": "XRPUSDT", "direction": "SHORT", "score": 62, "status": "LOSS", "pnl": -80.0, "rsi": 59.8, "macd": -0.0005, "bb": 0.65, "vol": 0.8, "fund": 0.0002}
                ]
                
                for i, ms in enumerate(mock_signals):
                    entry = 60000.0 if ms["symbol"] == "BTCUSDT" else (1700.0 if ms["symbol"] == "ETHUSDT" else 1.08)
                    tp = entry * 1.025 if ms["direction"] == "LONG" else entry * 0.975
                    sl = entry * 0.992 if ms["direction"] == "LONG" else entry * 1.008
                    
                    sig = Signal(
                        symbol      = ms["symbol"],
                        direction   = ms["direction"],
                        score       = ms["score"],
                        confidence  = "HIGH" if ms["score"] >= 80 else "MEDIUM",
                        entry_price = entry,
                        tp_price    = tp,
                        sl_price    = sl,
                        status      = ms["status"],
                        pnl_pct     = ms["pnl"],
                        result_price = tp if ms["status"] == "WIN" else sl,
                        funding_rate = ms["fund"],
                        indicators  = {
                            "rsi": ms["rsi"],
                            "macd_hist": ms["macd"],
                            "bb_pct": ms["bb"],
                            "volume_ratio": ms["vol"]
                        },
                        created_at  = datetime.now(timezone.utc) - timedelta(days=2, hours=i*3)
                    )
                    session.add(sig)
                session.commit()
                logger.info("Zasilono baze danych 12 sygnalami testowymi do uczenia ML.")
    except Exception as e:
        logger.error(f"Blad inicjalizacji portfela lub danych testowych: {e}")


def get_session() -> Session:
    return Session(engine)
