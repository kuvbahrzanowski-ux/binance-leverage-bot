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


def init_db():
    """Tworzy tabele jesli nie istnieja."""
    Base.metadata.create_all(engine)
    logger.info("Baza danych zainicjalizowana")


def get_session() -> Session:
    return Session(engine)
