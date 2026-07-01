"""
indicators.py – Obliczanie wskaznikow technicznych
"""
import pandas as pd
import pandas_ta as ta
import numpy as np
import logging
from typing import Optional
from config import (
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, EMA_PERIODS, ATR_PERIOD
)

logger = logging.getLogger(__name__)


def klines_to_df(klines: list) -> pd.DataFrame:
    """Konwertuje liste swiec do DataFrame."""
    df = pd.DataFrame(klines)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("open_time", inplace=True)
    df.sort_index(inplace=True)
    return df


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Oblicza wszystkie wskazniki i dodaje je jako kolumny DataFrame.
    Zwraca DataFrame z kolumnami wskaznikow.
    """
    df = df.copy()

    # ── RSI ───────────────────────────────────────────────────
    df["rsi"] = ta.rsi(df["close"], length=RSI_PERIOD)

    # ── MACD ──────────────────────────────────────────────────
    macd = ta.macd(df["close"], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    if macd is not None and not macd.empty:
        df["macd"]        = macd.iloc[:, 0]
        df["macd_signal"] = macd.iloc[:, 1]
        df["macd_hist"]   = macd.iloc[:, 2]
    else:
        df["macd"] = df["macd_signal"] = df["macd_hist"] = np.nan

    # ── Bollinger Bands ───────────────────────────────────────
    bb = ta.bbands(df["close"], length=BB_PERIOD, std=BB_STD)
    if bb is not None and not bb.empty:
        df["bb_lower"] = bb.iloc[:, 0]
        df["bb_mid"]   = bb.iloc[:, 1]
        df["bb_upper"] = bb.iloc[:, 2]
        df["bb_pct"]   = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    else:
        df["bb_lower"] = df["bb_mid"] = df["bb_upper"] = df["bb_pct"] = np.nan

    # ── EMA ───────────────────────────────────────────────────
    for period in EMA_PERIODS:
        df[f"ema_{period}"] = ta.ema(df["close"], length=period)

    # ── ATR ───────────────────────────────────────────────────
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=ATR_PERIOD)

    # ── Stochastic RSI ────────────────────────────────────────
    stoch = ta.stochrsi(df["close"], length=14, rsi_length=14, k=3, d=3)
    if stoch is not None and not stoch.empty:
        df["stoch_k"] = stoch.iloc[:, 0]
        df["stoch_d"] = stoch.iloc[:, 1]
    else:
        df["stoch_k"] = df["stoch_d"] = np.nan

    # ── OBV (On-Balance Volume) ───────────────────────────────
    df["obv"] = ta.obv(df["close"], df["volume"])

    # ── VWAP (uproszczony, reset dzienny nie mozliwy bez datestampu) ──
    typical = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum()

    # ── Wolumen srednia ───────────────────────────────────────
    df["volume_ma"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma"]

    return df


def get_latest(df: pd.DataFrame) -> dict:
    """Zwraca ostatni wiersz wskaznikow jako slownik."""
    if df.empty or len(df) < 2:
        return {}
    row = df.iloc[-1]
    return {k: (None if pd.isna(v) else round(float(v), 8)) for k, v in row.items()}


def trend_direction(df: pd.DataFrame, ema_fast: int = 9, ema_slow: int = 21) -> str:
    """Okresla kierunek trendu na podstawie EMA."""
    latest = get_latest(df)
    fast_key = f"ema_{ema_fast}"
    slow_key = f"ema_{ema_slow}"
    if latest.get(fast_key) and latest.get(slow_key):
        if latest[fast_key] > latest[slow_key]:
            return "BULLISH"
        elif latest[fast_key] < latest[slow_key]:
            return "BEARISH"
    return "NEUTRAL"


def support_resistance(df: pd.DataFrame, lookback: int = 50) -> dict:
    """Prosta identyfikacja wsparcia i oporu (lokalne min/max)."""
    recent = df.tail(lookback)
    support  = float(recent["low"].min())
    resistance = float(recent["high"].max())
    pivot    = (support + resistance + float(recent["close"].iloc[-1])) / 3
    return {"support": support, "resistance": resistance, "pivot": pivot}
