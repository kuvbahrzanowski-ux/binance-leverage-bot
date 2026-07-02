"""
pattern_engine.py – Rozpoznawanie formacji swiecowych i wzorcow cenowych
dla systemu swing tradingu.

Analizuje swiecze 1h i 4h pod katem:
- Formacje odwrocenia (hammer, engulfing, gwiazdy)
- Formacje kontynuacji (wyższe szczyty/nizsze dolki)
- Odbicia od wsparcia/oporu
"""
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _body_size(candle: pd.Series) -> float:
    """Rozmiar ciala swiecy (abs)."""
    return abs(candle["close"] - candle["open"])


def _upper_wick(candle: pd.Series) -> float:
    """Gorny cien."""
    return candle["high"] - max(candle["open"], candle["close"])


def _lower_wick(candle: pd.Series) -> float:
    """Dolny cien."""
    return min(candle["open"], candle["close"]) - candle["low"]


def _total_range(candle: pd.Series) -> float:
    """Pelny zakres High-Low."""
    return candle["high"] - candle["low"]


def detect_candle_patterns(df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> dict:
    """
    Wykrywa formacje swiecowe na danych 1h i 4h.
    Zwraca slownik wykrytych wzorcow z ich sila (1-3).
    """
    patterns = {}

    if df_1h is None or len(df_1h) < 5:
        return patterns
    if df_4h is None or len(df_4h) < 5:
        return patterns

    # --- Analiza swiec 1h (ostatnie 5) ---
    last3_1h = df_1h.tail(3)
    c0_1h = df_1h.iloc[-1]   # ostatnia swieca
    c1_1h = df_1h.iloc[-2]   # przedostatnia
    c2_1h = df_1h.iloc[-3]   # trzy wstecz

    # --- Analiza swiec 4h (ostatnie 5) ---
    c0_4h = df_4h.iloc[-1]
    c1_4h = df_4h.iloc[-2]
    c2_4h = df_4h.iloc[-3]

    # == FORMACJE BULLISH (LONG) ==

    # Hammer (Mloteczek) - 1h
    # Dlugi dolny cien, maly korpus na gorze, maly gorny cien
    body_1h = _body_size(c0_1h)
    lower_w = _lower_wick(c0_1h)
    upper_w = _upper_wick(c0_1h)
    total_r = _total_range(c0_1h)
    if total_r > 0:
        if (lower_w >= 2 * body_1h and
                upper_w <= 0.2 * total_r and
                body_1h >= 0.05 * total_r):
            strength = 2 if lower_w >= 3 * body_1h else 1
            patterns["hammer_1h"] = {
                "name": "Hammer (1h)",
                "direction": "LONG",
                "strength": strength,
                "desc": f"Mloteczek na 1h – presja kupna (cien dol {lower_w:.4f})"
            }

    # Bullish Engulfing - 1h
    # Bycza swieca pochlanajaca poprzednia niedzwiedzia
    if (c0_1h["close"] > c0_1h["open"] and        # bycza
            c1_1h["close"] < c1_1h["open"] and        # poprzednia niedzwiedzia
            c0_1h["open"] <= c1_1h["close"] and        # otwarcie ponizej zamkniecia poprzedniej
            c0_1h["close"] >= c1_1h["open"]):          # zamkniecie powyzej otwarcia poprzedniej
        patterns["bullish_engulfing_1h"] = {
            "name": "Bullish Engulfing (1h)",
            "direction": "LONG",
            "strength": 3,
            "desc": "Bycze pochłoniecie – silny sygnal odwrocenia"
        }

    # Morning Star (Gwiazda Poranna) - 3 swiecze na 4h
    # Niedzwiedzia + maly korpus doji/spin + bycza
    if (c2_4h["close"] < c2_4h["open"] and               # niedzwiedzia
            _body_size(c1_4h) < 0.3 * _body_size(c2_4h) and  # maly korpus w srodku
            c0_4h["close"] > c0_4h["open"] and               # bycza
            c0_4h["close"] > (c2_4h["open"] + c2_4h["close"]) / 2):  # zamkniecie w polowie 1 swiecy
        patterns["morning_star_4h"] = {
            "name": "Morning Star (4h)",
            "direction": "LONG",
            "strength": 3,
            "desc": "Gwiazda Poranna 4h – silne odwrocenie trendu"
        }

    # Bullish Engulfing - 4h (silniejszy niz 1h)
    if (c0_4h["close"] > c0_4h["open"] and
            c1_4h["close"] < c1_4h["open"] and
            c0_4h["open"] <= c1_4h["close"] and
            c0_4h["close"] >= c1_4h["open"]):
        patterns["bullish_engulfing_4h"] = {
            "name": "Bullish Engulfing (4h)",
            "direction": "LONG",
            "strength": 3,
            "desc": "Bycze pochłoniecie na 4h – mocny sygnał"
        }

    # Higher Highs & Higher Lows (trend wzrostowy 4h)
    highs_4h = df_4h["high"].tail(6).values
    lows_4h  = df_4h["low"].tail(6).values
    if (highs_4h[-1] > highs_4h[-2] > highs_4h[-3] and
            lows_4h[-1] > lows_4h[-2] > lows_4h[-3]):
        patterns["higher_highs_4h"] = {
            "name": "Wyższe Szczyty i Dołki (4h)",
            "direction": "LONG",
            "strength": 2,
            "desc": "Trend wzrostowy potwierdzony – HH + HL na 4h"
        }

    # Support Bounce (odbicie od wsparcia 4h)
    recent_lows = df_4h["low"].tail(20)
    support_zone = recent_lows.quantile(0.15)  # dolne 15% jako wsparcie
    current_close = c0_4h["close"]
    prev_close = c1_4h["close"]
    if (prev_close <= support_zone * 1.01 and  # poprzednia swieca przy wsparciu
            current_close > support_zone * 1.015 and  # odbicie powyzej wsparcia
            c0_4h["close"] > c0_4h["open"]):  # bycza
        patterns["support_bounce_4h"] = {
            "name": "Odbicie od Wsparcia (4h)",
            "direction": "LONG",
            "strength": 2,
            "desc": f"Cena odbiła od wsparcia {support_zone:.4f} z bykiem"
        }

    # == FORMACJE BEARISH (SHORT) ==

    # Shooting Star - 1h
    # Dlugi gorny cien, maly korpus na dole, maly dolny cien
    body_s = _body_size(c0_1h)
    upper_s = _upper_wick(c0_1h)
    lower_s = _lower_wick(c0_1h)
    total_s = _total_range(c0_1h)
    if total_s > 0:
        if (upper_s >= 2 * body_s and
                lower_s <= 0.2 * total_s and
                body_s >= 0.05 * total_s):
            strength = 2 if upper_s >= 3 * body_s else 1
            patterns["shooting_star_1h"] = {
                "name": "Shooting Star (1h)",
                "direction": "SHORT",
                "strength": strength,
                "desc": f"Gwiazda Spadajaca na 1h – presja sprzedazy (cien gor {upper_s:.4f})"
            }

    # Bearish Engulfing - 1h
    if (c0_1h["close"] < c0_1h["open"] and
            c1_1h["close"] > c1_1h["open"] and
            c0_1h["open"] >= c1_1h["close"] and
            c0_1h["close"] <= c1_1h["open"]):
        patterns["bearish_engulfing_1h"] = {
            "name": "Bearish Engulfing (1h)",
            "direction": "SHORT",
            "strength": 3,
            "desc": "Niedzwiedzie pochłoniecie – silny sygnał odwrocenia w dol"
        }

    # Evening Star (Gwiazda Wieczorna) - 4h
    if (c2_4h["close"] > c2_4h["open"] and                # bycza
            _body_size(c1_4h) < 0.3 * _body_size(c2_4h) and   # maly korpus
            c0_4h["close"] < c0_4h["open"] and                # niedzwiedzia
            c0_4h["close"] < (c2_4h["open"] + c2_4h["close"]) / 2):  # ponizej polowy
        patterns["evening_star_4h"] = {
            "name": "Evening Star (4h)",
            "direction": "SHORT",
            "strength": 3,
            "desc": "Gwiazda Wieczorna 4h – silne odwrocenie w dol"
        }

    # Bearish Engulfing - 4h
    if (c0_4h["close"] < c0_4h["open"] and
            c1_4h["close"] > c1_4h["open"] and
            c0_4h["open"] >= c1_4h["close"] and
            c0_4h["close"] <= c1_4h["open"]):
        patterns["bearish_engulfing_4h"] = {
            "name": "Bearish Engulfing (4h)",
            "direction": "SHORT",
            "strength": 3,
            "desc": "Niedźwiedzie pochłoniecie na 4h – mocny sygnał"
        }

    # Lower Highs & Lower Lows (trend spadkowy 4h)
    if (highs_4h[-1] < highs_4h[-2] < highs_4h[-3] and
            lows_4h[-1] < lows_4h[-2] < lows_4h[-3]):
        patterns["lower_lows_4h"] = {
            "name": "Niższe Szczyty i Dołki (4h)",
            "direction": "SHORT",
            "strength": 2,
            "desc": "Trend spadkowy potwierdzony – LH + LL na 4h"
        }

    # Resistance Rejection (odrzucenie od oporu 4h)
    recent_highs = df_4h["high"].tail(20)
    resistance_zone = recent_highs.quantile(0.85)  # gorny 15% jako opor
    if (prev_close >= resistance_zone * 0.99 and
            current_close < resistance_zone * 0.985 and
            c0_4h["close"] < c0_4h["open"]):
        patterns["resistance_rejection_4h"] = {
            "name": "Odrzucenie od Oporu (4h)",
            "direction": "SHORT",
            "strength": 2,
            "desc": f"Cena odrzucona od oporu {resistance_zone:.4f} z niedzwiedziem"
        }

    # == WZORZEC NEUTRALNY – DOJI (sygnał niepewności) ==
    if total_r > 0 and body_1h < 0.1 * total_r:
        patterns["doji_1h"] = {
            "name": "Doji (1h)",
            "direction": "NEUTRAL",
            "strength": 0,
            "desc": "Doji – nierozstrzygnieta walka, brak wyraznego sygnału"
        }

    return patterns


def pattern_score(patterns: dict, direction: str) -> tuple[int, list[str]]:
    """
    Oblicza punkty i opisy z wykrytych formacji dla danego kierunku.
    direction: 'LONG' lub 'SHORT'
    Zwraca (score, reasons)
    """
    score = 0
    reasons = []

    # Mapa sily na punkty
    strength_pts = {1: 8, 2: 12, 3: 18}

    for key, pattern in patterns.items():
        p_dir = pattern["direction"]
        strength = pattern["strength"]
        pts = strength_pts.get(strength, 8)

        if p_dir == direction:
            # Formacja zgodna z naszym kierunkiem – dodaj punkty
            score += pts
            stars = "⭐" * strength
            reasons.append(f"✅ {pattern['name']} {stars} (+{pts} pkt) – {pattern['desc']}")
        elif p_dir != "NEUTRAL" and p_dir != direction:
            # Formacja przeciwna – odejmij polowe punktow
            penalty = pts // 2
            score -= penalty
            reasons.append(f"❌ {pattern['name']} (przeciwna, -{penalty} pkt)")
        elif p_dir == "NEUTRAL":
            # Doji – brak punktow, ale informacja
            reasons.append(f"⚠️ {pattern['desc']}")

    return score, reasons
