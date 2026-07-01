"""
signal_engine.py – Multi-timeframe scoring i generowanie sygnalow LONG/SHORT
"""
import logging
import math
from typing import Optional
from datetime import datetime, timezone

from binance_client import client
from indicators import klines_to_df, compute_all, get_latest, trend_direction, support_resistance
from config import (
    TIMEFRAMES, SIGNAL_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD,
    SYMBOLS
)
from ml_engine import ml_engine

logger = logging.getLogger(__name__)


def _safe(val, default=0.0):
    return val if val is not None else default
def score_long(ind_fast: dict, ind_medium: dict, ind_macro: dict, ind_super_macro: dict,
               funding_rate: float, oi_change: float, weights: Optional[dict] = None) -> tuple[int, list[str]]:
    """
    Oblicza score LONG (0-100) i zwraca liste powodow.
    """
    if weights is None:
        weights = {"rsi": 15, "macd": 15, "bb": 10, "vol": 10, "funding": 10}

    score = 0
    reasons = []

    # ── 1. Trend makro (1d) – 20 pkt ─────────────────────────
    ema50_1d = _safe(ind_super_macro.get("ema_50"))
    close_1d = _safe(ind_super_macro.get("close"))
    if close_1d > ema50_1d > 0:
        score += 20
        reasons.append("✅ Cena > EMA50 (1d) – trend wzrostowy")
    elif close_1d > 0 and ema50_1d > 0:
        score -= 5
        reasons.append("❌ Cena < EMA50 (1d) – trend spadkowy")

    # ── 2. Trend sredni (4h) – 15 pkt ────────────────────────
    ema21_4h = _safe(ind_macro.get("ema_21"))
    ema9_4h  = _safe(ind_macro.get("ema_9"))
    if ema9_4h > ema21_4h > 0:
        score += 15
        reasons.append("✅ EMA9 > EMA21 (4h) – bullish")
    else:
        reasons.append("⚠️ EMA9 < EMA21 (4h)")

    # ── 3. RSI 15m – dynamiczna waga (RSI) ────────────────────
    rsi = _safe(ind_fast.get("rsi"), 50)
    w_rsi = weights.get("rsi", 15)
    if 45 <= rsi <= 65:
        score += w_rsi
        reasons.append(f"✅ RSI={rsi:.1f} – strefa neutralna/wzrostowa (15m, waga {w_rsi})")
    elif rsi < 35:
        sub_pts = int(round(w_rsi * 0.5))
        score += sub_pts
        reasons.append(f"⚠️ RSI={rsi:.1f} – wyprzedanie (15m, waga {sub_pts})")
    elif rsi > 75:
        sub_pts = int(round(w_rsi * 0.67))
        score -= sub_pts
        reasons.append(f"❌ RSI={rsi:.1f} – wykupienie (15m, waga -{sub_pts})")

    # ── 4. MACD 15m – dynamiczna waga (MACD) ──────────────────
    macd_hist = _safe(ind_fast.get("macd_hist"))
    macd      = _safe(ind_fast.get("macd"))
    macd_sig  = _safe(ind_fast.get("macd_signal"))
    w_macd    = weights.get("macd", 15)
    if macd_hist > 0 and macd > macd_sig:
        score += w_macd
        reasons.append(f"✅ MACD bullish cross (15m, waga {w_macd})")
    elif macd_hist > 0:
        sub_pts = int(round(w_macd * 0.5))
        score += sub_pts
        reasons.append(f"⚠️ MACD hist dodatni (15m, waga {sub_pts})")
    else:
        reasons.append("❌ MACD bearish (15m)")

    # ── 5. Bollinger Bands 15m – dynamiczna waga (BB) ─────────
    bb_pct = _safe(ind_fast.get("bb_pct"), 0.5)
    w_bb   = weights.get("bb", 10)
    if 0.1 <= bb_pct <= 0.5:
        score += w_bb
        reasons.append(f"✅ BB%={bb_pct:.2f} – dolna polowa pasma (15m, waga {w_bb})")
    elif bb_pct < 0.1:
        sub_pts = int(round(w_bb * 0.7))
        score += sub_pts
        reasons.append(f"⚠️ BB%={bb_pct:.2f} – dolna wstęga BB (15m, waga {sub_pts})")
    elif bb_pct > 0.9:
        sub_pts = int(round(w_bb * 0.5))
        score -= sub_pts
        reasons.append(f"❌ BB%={bb_pct:.2f} – górna wstęga BB (15m, waga -{sub_pts})")

    # ── 6. Wolumen 15m – dynamiczna waga (Vol) ────────────────
    vol_ratio = _safe(ind_fast.get("volume_ratio"), 1.0)
    w_vol     = weights.get("vol", 10)
    if vol_ratio >= 1.5:
        score += w_vol
        reasons.append(f"✅ Wolumen x{vol_ratio:.1f} – wzrost obrotów (15m, waga {w_vol})")
    elif vol_ratio >= 1.0:
        sub_pts = int(round(w_vol * 0.5))
        score += sub_pts
        reasons.append(f"⚠️ Wolumen x{vol_ratio:.1f} – średnie obroty (15m, waga {sub_pts})")
    else:
        reasons.append(f"❌ Wolumen x{vol_ratio:.1f} – słabe obroty (15m)")

    # ── 7. Funding Rate – dynamiczna waga (Funding) ──────────
    w_fund = weights.get("funding", 10)
    if funding_rate < -0.001:
        score += w_fund
        reasons.append(f"✅ Funding={funding_rate:.4f} – ujemny (presja LONG, waga {w_fund})")
    elif -0.001 <= funding_rate <= 0.001:
        sub_pts = int(round(w_fund * 0.5))
        score += sub_pts
        reasons.append(f"✅ Funding={funding_rate:.4f} – neutralny (waga {sub_pts})")
    else:
        reasons.append(f"❌ Funding={funding_rate:.4f} – pozytywny (presja SHORT)")

    # ── 8. Stochastic RSI – 5 pkt ────────────────────────────
    stoch_k = _safe(ind_fast.get("stoch_k"), 50)
    stoch_d = _safe(ind_fast.get("stoch_d"), 50)
    if stoch_k > stoch_d and stoch_k < 80:
        score += 5
        reasons.append("✅ StochRSI bullish cross (15m)")

    return max(0, min(100, score)), reasons


def score_short(ind_fast: dict, ind_medium: dict, ind_macro: dict, ind_super_macro: dict,
                funding_rate: float, oi_change: float, weights: Optional[dict] = None) -> tuple[int, list[str]]:
    """
    Oblicza score SHORT (0-100) – lustrzane odbicie score_long.
    """
    if weights is None:
        weights = {"rsi": 15, "macd": 15, "bb": 10, "vol": 10, "funding": 10}

    score = 0
    reasons = []

    # ── 1. Trend makro (1d) – 20 pkt ─────────────────────────
    ema50_1d = _safe(ind_super_macro.get("ema_50"))
    close_1d = _safe(ind_super_macro.get("close"))
    if 0 < close_1d < ema50_1d:
        score += 20
        reasons.append("✅ Cena < EMA50 (1d) – trend spadkowy")
    elif close_1d > ema50_1d > 0:
        score -= 5
        reasons.append("❌ Cena > EMA50 (1d) – trend wzrostowy")

    # ── 2. Trend sredni (4h) – 15 pkt ────────────────────────
    ema21_4h = _safe(ind_macro.get("ema_21"))
    ema9_4h  = _safe(ind_macro.get("ema_9"))
    if 0 < ema9_4h < ema21_4h:
        score += 15
        reasons.append("✅ EMA9 < EMA21 (4h) – bearish")
    else:
        reasons.append("⚠️ EMA9 > EMA21 (4h)")

    # ── 3. RSI 15m – dynamiczna waga (RSI) ────────────────────
    rsi = _safe(ind_fast.get("rsi"), 50)
    w_rsi = weights.get("rsi", 15)
    if 35 <= rsi <= 55:
        score += w_rsi
        reasons.append(f"✅ RSI={rsi:.1f} – strefa neutralna/spadkowa (15m, waga {w_rsi})")
    elif rsi > 75:
        sub_pts = int(round(w_rsi * 0.5))
        score += sub_pts
        reasons.append(f"⚠️ RSI={rsi:.1f} – wykupienie (15m, waga {sub_pts})")
    elif rsi < 25:
        sub_pts = int(round(w_rsi * 0.67))
        score -= sub_pts
        reasons.append(f"❌ RSI={rsi:.1f} – wyprzedanie (15m, waga -{sub_pts})")

    # ── 4. MACD 15m – dynamiczna waga (MACD) ──────────────────
    macd_hist = _safe(ind_fast.get("macd_hist"))
    macd      = _safe(ind_fast.get("macd"))
    macd_sig  = _safe(ind_fast.get("macd_signal"))
    w_macd    = weights.get("macd", 15)
    if macd_hist < 0 and macd < macd_sig:
        score += w_macd
        reasons.append(f"✅ MACD bearish cross (15m, waga {w_macd})")
    elif macd_hist < 0:
        sub_pts = int(round(w_macd * 0.5))
        score += sub_pts
        reasons.append(f"⚠️ MACD hist ujemny (15m, waga {sub_pts})")
    else:
        reasons.append("❌ MACD bullish (15m)")

    # ── 5. Bollinger Bands 15m – dynamiczna waga (BB) ─────────
    bb_pct = _safe(ind_fast.get("bb_pct"), 0.5)
    w_bb   = weights.get("bb", 10)
    if 0.5 <= bb_pct <= 0.9:
        score += w_bb
        reasons.append(f"✅ BB%={bb_pct:.2f} – gorna polowa pasma (15m, waga {w_bb})")
    elif bb_pct > 0.9:
        sub_pts = int(round(w_bb * 0.7))
        score += sub_pts
        reasons.append(f"⚠️ BB%={bb_pct:.2f} – górna wstęga BB (15m, waga {sub_pts})")
    elif bb_pct < 0.1:
        sub_pts = int(round(w_bb * 0.5))
        score -= sub_pts
        reasons.append(f"❌ BB%={bb_pct:.2f} – dolna wstęga BB (15m, waga -{sub_pts})")

    # ── 6. Wolumen 15m – dynamiczna waga (Vol) ────────────────
    vol_ratio = _safe(ind_fast.get("volume_ratio"), 1.0)
    w_vol     = weights.get("vol", 10)
    if vol_ratio >= 1.5:
        score += w_vol
        reasons.append(f"✅ Wolumen x{vol_ratio:.1f} (15m, waga {w_vol})")
    elif vol_ratio >= 1.0:
        sub_pts = int(round(w_vol * 0.5))
        score += sub_pts
        reasons.append(f"⚠️ Wolumen x{vol_ratio:.1f} (15m, waga {sub_pts})")
    else:
        reasons.append(f"❌ Wolumen x{vol_ratio:.1f} – słabe obroty (15m)")

    # ── 7. Funding Rate – dynamiczna waga (Funding) ──────────
    w_fund = weights.get("funding", 10)
    if funding_rate > 0.001:
        score += w_fund
        reasons.append(f"✅ Funding={funding_rate:.4f} – pozytywny (presja SHORT, waga {w_fund})")
    elif -0.001 <= funding_rate <= 0.001:
        sub_pts = int(round(w_fund * 0.5))
        score += sub_pts
        reasons.append(f"✅ Funding={funding_rate:.4f} – neutralny (waga {sub_pts})")
    else:
        reasons.append(f"❌ Funding={funding_rate:.4f} – ujemny (presja LONG)")

    # ── 8. Stochastic RSI – 5 pkt ────────────────────────────
    stoch_k = _safe(ind_fast.get("stoch_k"), 50)
    stoch_d = _safe(ind_fast.get("stoch_d"), 50)
    if stoch_k < stoch_d and stoch_k > 20:
        score += 5
        reasons.append("✅ StochRSI bearish cross")

    return max(0, min(100, score)), reasons


def calculate_tp_sl(entry: float, direction: str, atr: float, leverage: int) -> tuple[float, float]:
    """
    Oblicza Take Profit i Stop Loss na podstawie ATR i dzwigni.
    Im wyzsza dzwignia, tym blizej SL (ochrona kapitalu).
    """
    # Bazowy % SL = ATR / entry
    base_sl_pct = (atr / entry) if entry > 0 else 0.01

    # Skalowanie SL wzgledem dzwigni (przy 100x max 0.7%)
    max_sl_pct = min(base_sl_pct * 1.5, 1.0 / max(leverage / 10, 1))
    sl_pct = max(max_sl_pct, 0.003)  # min 0.3%

    # TP = 2× SL (Risk:Reward 1:2)
    tp_pct = sl_pct * 2.0

    if direction == "LONG":
        tp = round(entry * (1 + tp_pct / 100), 4)
        sl = round(entry * (1 - sl_pct / 100), 4)
    else:
        tp = round(entry * (1 - tp_pct / 100), 4)
        sl = round(entry * (1 + sl_pct / 100), 4)

    return tp, sl


def analyze_symbol(symbol: str, leverage: int = 10) -> Optional[dict]:
    """
    Glowna funkcja analizy – pobiera dane, oblicza wskazniki, zwraca sygnal.
    """
    try:
        # ── Pobierz swiecy dla wszystkich timeframow ──────────
        klines_15m = client.get_klines(symbol, "15m", limit=200)
        klines_1h  = client.get_klines(symbol, "1h",  limit=100)
        klines_4h  = client.get_klines(symbol, "4h",  limit=100)
        klines_1d  = client.get_klines(symbol, "1d",  limit=50)

        df_15m = compute_all(klines_to_df(klines_15m))
        df_1h  = compute_all(klines_to_df(klines_1h))
        df_4h  = compute_all(klines_to_df(klines_4h))
        df_1d  = compute_all(klines_to_df(klines_1d))

        ind_15m = get_latest(df_15m)
        ind_1h  = get_latest(df_1h)
        ind_4h  = get_latest(df_4h)
        ind_1d  = get_latest(df_1d)

        # ── Dane rynkowe live ─────────────────────────────────
        mark = client.get_mark_price(symbol)
        funding_rate  = float(mark.get("lastFundingRate", 0))
        mark_price    = float(mark.get("markPrice", ind_15m.get("close", 0)))

        oi = client.get_open_interest(symbol)
        open_interest = float(oi.get("openInterest", 0))

        entry = mark_price
        atr   = _safe(ind_15m.get("atr"), entry * 0.01)

        # ── Scoring ───────────────────────────────────────────
        weights = ml_engine.get_current_weights()
        long_score,  long_reasons  = score_long( ind_15m, ind_1h, ind_4h, ind_1d, funding_rate, 0, weights)
        short_score, short_reasons = score_short(ind_15m, ind_1h, ind_4h, ind_1d, funding_rate, 0, weights)

        # ── Wybierz silniejszy sygnal ─────────────────────────
        if long_score >= short_score:
            direction = "LONG"
            score     = long_score
            reasons   = long_reasons
        else:
            direction = "SHORT"
            score     = short_score
            reasons   = short_reasons

        tp, sl = calculate_tp_sl(entry, direction, atr, leverage)

        confidence = "HIGH" if score >= HIGH_CONFIDENCE_THRESHOLD else (
                     "MEDIUM" if score >= SIGNAL_THRESHOLD else "LOW"
        )

        sr = support_resistance(df_15m)

        return {
            "symbol":        symbol,
            "direction":     direction,
            "score":         score,
            "confidence":    confidence,
            "entry_price":   round(entry, 6),
            "tp_price":      tp,
            "sl_price":      sl,
            "atr":           round(atr, 6),
            "leverage":      leverage,
            "funding_rate":  round(funding_rate, 6),
            "open_interest": round(open_interest, 2),
            "support":       round(sr["support"], 6),
            "resistance":    round(sr["resistance"], 6),
            "reasons":       reasons,
            "long_score":    long_score,
            "short_score":   short_score,
            "indicators": {
                "open":       round(_safe(ind_15m.get("open"), 0), 4),
                "close":      round(_safe(ind_15m.get("close"), 0), 4),
                "rsi":        round(_safe(ind_15m.get("rsi"), 0), 2),
                "macd_hist":  round(_safe(ind_15m.get("macd_hist"), 0), 6),
                "bb_pct":     round(_safe(ind_15m.get("bb_pct"), 0), 4),
                "ema_9":      round(_safe(ind_15m.get("ema_9"), 0), 4),
                "ema_21":     round(_safe(ind_15m.get("ema_21"), 0), 4),
                "ema_50":     round(_safe(ind_15m.get("ema_50"), 0), 4),
                "volume_ratio": round(_safe(ind_15m.get("volume_ratio"), 1), 2),
                "stoch_k":    round(_safe(ind_15m.get("stoch_k"), 50), 2),
                "stoch_d":    round(_safe(ind_15m.get("stoch_d"), 50), 2),
            },
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Blad analizy {symbol}: {e}", exc_info=True)
        return None


def analyze_all(leverage: int = 10) -> list[dict]:
    """Analizuje wszystkie skonfigurowane symbole."""
    results = []
    for symbol in SYMBOLS:
        result = analyze_symbol(symbol, leverage)
        if result:
            results.append(result)
    return results
