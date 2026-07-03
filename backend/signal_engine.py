"""
signal_engine.py – Multi-timeframe scoring + rozpoznawanie formacji swiecowych (Swing Trade)

Strategia:
 - Timeframy: 1h (fast), 4h (medium), 1d (macro)
 - Scoring: RSI/MACD/BB/Vol/Funding + formacje swiecowe (pattern_engine)
 - Cel TP: +25% ruch ceny (= +250% przy 10x dzwigni)
 - Stop Loss: -8% ruch ceny (= -80% przy 10x)
 - Próg sygnału: 70/100
"""
import logging
import math
from typing import Optional
from datetime import datetime, timezone

from binance_client import client
from indicators import klines_to_df, compute_all, get_latest, trend_direction, support_resistance
from config import (
    SIGNAL_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD,
    SYMBOLS, DEFAULT_LEVERAGE,
    SWING_TP_PCT, SWING_SL_PCT
)
from pattern_engine import detect_candle_patterns, pattern_score
from ml_engine import ml_engine

logger = logging.getLogger(__name__)


def _safe(val, default=0.0):
    return val if val is not None else default


# ─────────────────────────────────────────────────────────────
# SCORING LONG
# ─────────────────────────────────────────────────────────────

def score_long(ind_fast: dict, ind_medium: dict, ind_macro: dict, ind_super_macro: dict,
               funding_rate: float, oi_change: float,
               df_fast=None, df_medium=None,
               weights: Optional[dict] = None) -> tuple[int, list[str]]:
    """
    Oblicza score LONG (0-100) z uwzglednieniem:
    - EMA trendu makro i sredniego
    - RSI / MACD / BB / Vol / Funding (1h fast)
    - Formacji swiecowych (pattern_engine na 1h + 4h)
    """
    if weights is None:
        weights = {"rsi": 12, "macd": 12, "bb": 8, "vol": 8, "funding": 8}

    score = 0
    reasons = []

    # ── 1. Trend makro (1d) – 20 pkt ─────────────────────────
    ema50_1d = _safe(ind_super_macro.get("ema_50"))
    close_1d = _safe(ind_super_macro.get("close"))
    if close_1d > ema50_1d > 0:
        score += 20
        reasons.append("✅ Cena > EMA50 (1d) – trend wzrostowy (makro)")
    elif close_1d > 0 and ema50_1d > 0:
        score -= 5
        reasons.append("❌ Cena < EMA50 (1d) – makro trend spadkowy")

    # ── 2. Trend 4h (EMA 9/21) – 15 pkt ──────────────────────
    ema21_4h = _safe(ind_macro.get("ema_21"))
    ema9_4h  = _safe(ind_macro.get("ema_9"))
    if ema9_4h > ema21_4h > 0:
        score += 15
        reasons.append("✅ EMA9 > EMA21 (4h) – bullish")
    else:
        reasons.append("⚠️ EMA9 < EMA21 (4h) – uwaga, brak byczego trendu 4h")

    # ── 3. RSI 1h ─────────────────────────────────────────────
    rsi = _safe(ind_fast.get("rsi"), 50)
    w_rsi = weights.get("rsi", 12)
    if 40 <= rsi <= 60:
        score += w_rsi
        reasons.append(f"✅ RSI={rsi:.1f} – strefa neutralna (1h, waga {w_rsi})")
    elif rsi < 35:
        sub_pts = int(round(w_rsi * 0.6))
        score += sub_pts
        reasons.append(f"⚠️ RSI={rsi:.1f} – wyprzedanie, potenc. odbicie (1h, +{sub_pts})")
    elif rsi > 70:
        sub_pts = int(round(w_rsi * 0.5))
        score -= sub_pts
        reasons.append(f"❌ RSI={rsi:.1f} – wykupienie (1h, -{sub_pts})")

    # ── 4. MACD 1h ────────────────────────────────────────────
    macd_hist = _safe(ind_fast.get("macd_hist"))
    macd      = _safe(ind_fast.get("macd"))
    macd_sig  = _safe(ind_fast.get("macd_signal"))
    w_macd    = weights.get("macd", 12)
    if macd_hist > 0 and macd > macd_sig:
        score += w_macd
        reasons.append(f"✅ MACD bullish cross (1h, waga {w_macd})")
    elif macd_hist > 0:
        sub_pts = int(round(w_macd * 0.5))
        score += sub_pts
        reasons.append(f"⚠️ MACD hist+ (1h, +{sub_pts})")
    else:
        reasons.append("❌ MACD bearish (1h)")

    # ── 5. Bollinger Bands 1h ─────────────────────────────────
    bb_pct = _safe(ind_fast.get("bb_pct"), 0.5)
    w_bb   = weights.get("bb", 8)
    if 0.1 <= bb_pct <= 0.45:
        score += w_bb
        reasons.append(f"✅ BB%={bb_pct:.2f} – dolna polowa (1h, +{w_bb})")
    elif bb_pct < 0.1:
        sub_pts = int(round(w_bb * 0.7))
        score += sub_pts
        reasons.append(f"⚠️ BB%={bb_pct:.2f} – dolna wstega, potenc. odwrocenie (+{sub_pts})")
    elif bb_pct > 0.9:
        sub_pts = int(round(w_bb * 0.5))
        score -= sub_pts
        reasons.append(f"❌ BB%={bb_pct:.2f} – gorna wstega BB (1h, -{sub_pts})")

    # ── 6. Wolumen 1h ─────────────────────────────────────────
    vol_ratio = _safe(ind_fast.get("volume_ratio"), 1.0)
    w_vol     = weights.get("vol", 8)
    if vol_ratio >= 1.5:
        score += w_vol
        reasons.append(f"✅ Wolumen x{vol_ratio:.1f} – wzrost obrotów (1h, +{w_vol})")
    elif vol_ratio >= 1.0:
        sub_pts = int(round(w_vol * 0.4))
        score += sub_pts
        reasons.append(f"⚠️ Wolumen x{vol_ratio:.1f} – srednie obroty (+{sub_pts})")
    else:
        reasons.append(f"❌ Wolumen x{vol_ratio:.1f} – słabe obroty (1h)")

    # ── 7. Funding Rate ───────────────────────────────────────
    w_fund = weights.get("funding", 8)
    if funding_rate < -0.001:
        score += w_fund
        reasons.append(f"✅ Funding={funding_rate:.4f} – ujemny (presja LONG, +{w_fund})")
    elif -0.001 <= funding_rate <= 0.001:
        sub_pts = int(round(w_fund * 0.5))
        score += sub_pts
        reasons.append(f"✅ Funding={funding_rate:.4f} – neutralny (+{sub_pts})")
    else:
        reasons.append(f"❌ Funding={funding_rate:.4f} – pozytywny (presja SHORT)")

    # ── 8. Stochastic RSI ─────────────────────────────────────
    stoch_k = _safe(ind_fast.get("stoch_k"), 50)
    stoch_d = _safe(ind_fast.get("stoch_d"), 50)
    if stoch_k > stoch_d and stoch_k < 80:
        score += 5
        reasons.append("✅ StochRSI bullish cross (1h)")

    # ── 9. Formacje swiecowe (pattern_engine) ─────────────────
    if df_fast is not None and df_medium is not None:
        try:
            patterns = detect_candle_patterns(df_fast, df_medium)
            p_score, p_reasons = pattern_score(patterns, "LONG")
            score += p_score
            reasons.extend(p_reasons)
        except Exception as e:
            logger.warning(f"Pattern engine blad LONG: {e}")

    return max(0, min(100, score)), reasons


# ─────────────────────────────────────────────────────────────
# SCORING SHORT
# ─────────────────────────────────────────────────────────────

def score_short(ind_fast: dict, ind_medium: dict, ind_macro: dict, ind_super_macro: dict,
                funding_rate: float, oi_change: float,
                df_fast=None, df_medium=None,
                weights: Optional[dict] = None) -> tuple[int, list[str]]:
    """
    Oblicza score SHORT (0-100) – lustrzane odbicie score_long.
    """
    if weights is None:
        weights = {"rsi": 12, "macd": 12, "bb": 8, "vol": 8, "funding": 8}

    score = 0
    reasons = []

    # ── 1. Trend makro (1d) – 20 pkt ─────────────────────────
    ema50_1d = _safe(ind_super_macro.get("ema_50"))
    close_1d = _safe(ind_super_macro.get("close"))
    if 0 < close_1d < ema50_1d:
        score += 20
        reasons.append("✅ Cena < EMA50 (1d) – trend spadkowy (makro)")
    elif close_1d > ema50_1d > 0:
        score -= 5
        reasons.append("❌ Cena > EMA50 (1d) – makro trend wzrostowy")

    # ── 2. Trend 4h (EMA 9/21) – 15 pkt ──────────────────────
    ema21_4h = _safe(ind_macro.get("ema_21"))
    ema9_4h  = _safe(ind_macro.get("ema_9"))
    if 0 < ema9_4h < ema21_4h:
        score += 15
        reasons.append("✅ EMA9 < EMA21 (4h) – bearish")
    else:
        reasons.append("⚠️ EMA9 > EMA21 (4h) – uwaga, brak niedźwiedziego trendu 4h")

    # ── 3. RSI 1h ─────────────────────────────────────────────
    rsi = _safe(ind_fast.get("rsi"), 50)
    w_rsi = weights.get("rsi", 12)
    if 40 <= rsi <= 60:
        score += w_rsi
        reasons.append(f"✅ RSI={rsi:.1f} – strefa neutralna (1h, waga {w_rsi})")
    elif rsi > 70:
        sub_pts = int(round(w_rsi * 0.6))
        score += sub_pts
        reasons.append(f"⚠️ RSI={rsi:.1f} – wykupienie, potenc. odwrocenie (-{sub_pts})")
    elif rsi < 30:
        sub_pts = int(round(w_rsi * 0.5))
        score -= sub_pts
        reasons.append(f"❌ RSI={rsi:.1f} – wyprzedanie (1h, -{sub_pts})")

    # ── 4. MACD 1h ────────────────────────────────────────────
    macd_hist = _safe(ind_fast.get("macd_hist"))
    macd      = _safe(ind_fast.get("macd"))
    macd_sig  = _safe(ind_fast.get("macd_signal"))
    w_macd    = weights.get("macd", 12)
    if macd_hist < 0 and macd < macd_sig:
        score += w_macd
        reasons.append(f"✅ MACD bearish cross (1h, waga {w_macd})")
    elif macd_hist < 0:
        sub_pts = int(round(w_macd * 0.5))
        score += sub_pts
        reasons.append(f"⚠️ MACD hist- (1h, +{sub_pts})")
    else:
        reasons.append("❌ MACD bullish (1h)")

    # ── 5. Bollinger Bands 1h ─────────────────────────────────
    bb_pct = _safe(ind_fast.get("bb_pct"), 0.5)
    w_bb   = weights.get("bb", 8)
    if 0.55 <= bb_pct <= 0.9:
        score += w_bb
        reasons.append(f"✅ BB%={bb_pct:.2f} – gorna polowa (1h, +{w_bb})")
    elif bb_pct > 0.9:
        sub_pts = int(round(w_bb * 0.7))
        score += sub_pts
        reasons.append(f"⚠️ BB%={bb_pct:.2f} – gorna wstega, potenc. odwrocenie (+{sub_pts})")
    elif bb_pct < 0.1:
        sub_pts = int(round(w_bb * 0.5))
        score -= sub_pts
        reasons.append(f"❌ BB%={bb_pct:.2f} – dolna wstega BB (1h, -{sub_pts})")

    # ── 6. Wolumen 1h ─────────────────────────────────────────
    vol_ratio = _safe(ind_fast.get("volume_ratio"), 1.0)
    w_vol     = weights.get("vol", 8)
    if vol_ratio >= 1.5:
        score += w_vol
        reasons.append(f"✅ Wolumen x{vol_ratio:.1f} (1h, +{w_vol})")
    elif vol_ratio >= 1.0:
        sub_pts = int(round(w_vol * 0.4))
        score += sub_pts
        reasons.append(f"⚠️ Wolumen x{vol_ratio:.1f} (+{sub_pts})")
    else:
        reasons.append(f"❌ Wolumen x{vol_ratio:.1f} – słabe obroty (1h)")

    # ── 7. Funding Rate ───────────────────────────────────────
    w_fund = weights.get("funding", 8)
    if funding_rate > 0.001:
        score += w_fund
        reasons.append(f"✅ Funding={funding_rate:.4f} – pozytywny (presja SHORT, +{w_fund})")
    elif -0.001 <= funding_rate <= 0.001:
        sub_pts = int(round(w_fund * 0.5))
        score += sub_pts
        reasons.append(f"✅ Funding={funding_rate:.4f} – neutralny (+{sub_pts})")
    else:
        reasons.append(f"❌ Funding={funding_rate:.4f} – ujemny (presja LONG)")

    # ── 8. Stochastic RSI ─────────────────────────────────────
    stoch_k = _safe(ind_fast.get("stoch_k"), 50)
    stoch_d = _safe(ind_fast.get("stoch_d"), 50)
    if stoch_k < stoch_d and stoch_k > 20:
        score += 5
        reasons.append("✅ StochRSI bearish cross (1h)")

    # ── 9. Formacje swiecowe ───────────────────────────────────
    if df_fast is not None and df_medium is not None:
        try:
            patterns = detect_candle_patterns(df_fast, df_medium)
            p_score, p_reasons = pattern_score(patterns, "SHORT")
            score += p_score
            reasons.extend(p_reasons)
        except Exception as e:
            logger.warning(f"Pattern engine blad SHORT: {e}")

    return max(0, min(100, score)), reasons


# ─────────────────────────────────────────────────────────────
# TP / SL (Swing Trade)
# ─────────────────────────────────────────────────────────────

def calculate_tp_sl(entry: float, direction: str, atr: float, leverage: int) -> tuple[float, float]:
    """
    Oblicza Take Profit i Stop Loss dla swing trade.
    Cel: +25% ruch ceny = +250% zwrotu przy 10x dzwigni.
    SL:   -8% ruch ceny =  -80% straty  przy 10x.
    """
    tp_pct = SWING_TP_PCT / 100.0   # 0.25
    sl_pct = SWING_SL_PCT / 100.0   # 0.08

    if direction == "LONG":
        tp = round(entry * (1 + tp_pct), 6)
        sl = round(entry * (1 - sl_pct), 6)
    else:
        tp = round(entry * (1 - tp_pct), 6)
        sl = round(entry * (1 + sl_pct), 6)

    return tp, sl


# ─────────────────────────────────────────────────────────────
# ANALIZA SYMBOLU
# ─────────────────────────────────────────────────────────────

def analyze_symbol(symbol: str, leverage: int = DEFAULT_LEVERAGE) -> Optional[dict]:
    """
    Glowna funkcja analizy swing trade.
    Timeframy: 1h (fast), 4h (medium), 1d (macro).
    """
    try:
        # ── Pobierz swiecy ────────────────────────────────────
        klines_1h = client.get_klines(symbol, "15m", limit=200)  # fast (15m)
        klines_4h = client.get_klines(symbol, "1h",  limit=100)  # medium (1h)
        klines_1d = client.get_klines(symbol, "4h",  limit=50)   # macro (4h)

        df_1h = compute_all(klines_to_df(klines_1h))
        df_4h = compute_all(klines_to_df(klines_4h))
        df_1d = compute_all(klines_to_df(klines_1d))

        ind_1h = get_latest(df_1h)
        ind_4h = get_latest(df_4h)
        ind_1d = get_latest(df_1d)

        # ── Dane rynkowe live ──────────────────────────────────
        mark = client.get_mark_price(symbol)
        funding_rate  = float(mark.get("lastFundingRate", 0))
        mark_price    = float(mark.get("markPrice", ind_1h.get("close", 0)))

        oi = client.get_open_interest(symbol)
        open_interest = float(oi.get("openInterest", 0))

        entry = mark_price
        atr   = _safe(ind_1h.get("atr"), entry * 0.01)

        # ── Scoring z uwzglednieniem formacji swiecowych ───────
        weights = ml_engine.get_current_weights()
        long_score,  long_reasons  = score_long(
            ind_1h, ind_4h, ind_4h, ind_1d,
            funding_rate, 0,
            df_fast=df_1h, df_medium=df_4h,
            weights=weights
        )
        short_score, short_reasons = score_short(
            ind_1h, ind_4h, ind_4h, ind_1d,
            funding_rate, 0,
            df_fast=df_1h, df_medium=df_4h,
            weights=weights
        )

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

        sr = support_resistance(df_4h)

        # Kalkulacja potencjalnego zysku/straty
        if direction == "LONG":
            potential_profit_pct = round(SWING_TP_PCT * leverage, 1)  # % na pozycji
            potential_loss_pct   = round(SWING_SL_PCT * leverage, 1)
        else:
            potential_profit_pct = round(SWING_TP_PCT * leverage, 1)
            potential_loss_pct   = round(SWING_SL_PCT * leverage, 1)

        return {
            "symbol":                symbol,
            "direction":             direction,
            "score":                 score,
            "confidence":            confidence,
            "entry_price":           round(entry, 6),
            "tp_price":              tp,
            "sl_price":              sl,
            "atr":                   round(atr, 6),
            "leverage":              leverage,
            "funding_rate":          round(funding_rate, 6),
            "open_interest":         round(open_interest, 2),
            "support":               round(sr["support"], 6),
            "resistance":            round(sr["resistance"], 6),
            "potential_profit_pct":  potential_profit_pct,
            "potential_loss_pct":    potential_loss_pct,
            "reasons":               reasons,
            "long_score":            long_score,
            "short_score":           short_score,
            "indicators": {
                "open":         round(_safe(ind_1h.get("open"), 0), 4),
                "close":        round(_safe(ind_1h.get("close"), 0), 4),
                "rsi":          round(_safe(ind_1h.get("rsi"), 0), 2),
                "macd_hist":    round(_safe(ind_1h.get("macd_hist"), 0), 6),
                "bb_pct":       round(_safe(ind_1h.get("bb_pct"), 0), 4),
                "ema_9":        round(_safe(ind_1h.get("ema_9"), 0), 4),
                "ema_21":       round(_safe(ind_1h.get("ema_21"), 0), 4),
                "ema_50":       round(_safe(ind_1h.get("ema_50"), 0), 4),
                "volume_ratio": round(_safe(ind_1h.get("volume_ratio"), 1), 2),
                "stoch_k":      round(_safe(ind_1h.get("stoch_k"), 50), 2),
                "stoch_d":      round(_safe(ind_1h.get("stoch_d"), 50), 2),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"Blad analizy {symbol}: {e}", exc_info=True)
        return None


def analyze_all(leverage: int = DEFAULT_LEVERAGE) -> list[dict]:
    """Analizuje wszystkie skonfigurowane symbole."""
    results = []
    for symbol in SYMBOLS:
        result = analyze_symbol(symbol, leverage)
        if result:
            results.append(result)
    return results
