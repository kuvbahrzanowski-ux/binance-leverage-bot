"""
ml_engine.py – Silnik uczenia maszynowego (ML) bota.
Analizuje historyczne sygnały i optymalizuje wagi wskaźników technicznych.
"""
import logging
from datetime import datetime, timezone
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

from database import get_session, MLModelState, Signal

logger = logging.getLogger(__name__)

# Domyślne wagi wskaźników (łącznie 60 punktów z puli dynamicznej)
DEFAULT_WEIGHTS = {
    "rsi": 15,
    "macd": 15,
    "bb": 10,
    "vol": 10,
    "funding": 10,
}


class MLEngine:
    """Zarządza ciągłym uczeniem i optymalizacją wag wskaźników."""

    def get_current_weights(self) -> dict:
        """Pobiera aktualne wagi z bazy lub zwraca domyślne."""
        try:
            with get_session() as session:
                state = session.query(MLModelState).order_by(MLModelState.updated_at.desc()).first()
                if state and state.weights:
                    return state.weights
        except Exception as e:
            logger.warning(f"Nie udało się odczytać wag z bazy (używam domyślnych): {e}")
        return DEFAULT_WEIGHTS.copy()

    def get_status(self) -> dict:
        """Pobiera pełny stan ML (wagi, dokładność, historia, logi)."""
        try:
            with get_session() as session:
                state = session.query(MLModelState).order_by(MLModelState.updated_at.desc()).first()
                if state:
                    return {
                        "weights": state.weights,
                        "accuracy": round(state.accuracy * 100, 1),
                        "history": [round(x * 100, 1) for x in (state.history or [])],
                        "logs": state.logs or [],
                        "updated_at": state.updated_at.isoformat()
                    }
        except Exception as e:
            logger.warning(f"Błąd pobierania stanu ML: {e}")
        
        return {
            "weights": DEFAULT_WEIGHTS.copy(),
            "accuracy": 50.0,
            "history": [50.0],
            "logs": ["Brak historii do nauki (wymagane min. 10 rozstrzygniętych sygnałów)."],
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

    def retrain_model(self) -> dict:
        """
        Pobiera rozstrzygnięte sygnały z bazy, trenuje LogisticRegression
        i aktualizuje wagi w bazie danych.
        """
        logger.info("Rozpoczynam trening modelu ML...")
        try:
            with get_session() as session:
                # 1. Pobierz dane historyczne (sygnały zakończone wygraną/przegraną)
                signals = session.query(Signal).filter(
                    Signal.status.in_(["WIN", "LOSS"])
                ).all()

                if len(signals) < 10:
                    msg = f"Niewystarczająca liczba danych do uczenia: {len(signals)}/10. Pozostawiam domyślne wagi."
                    logger.info(msg)
                    return {"success": False, "reason": msg}

                # 2. Przygotuj macierz cech X i wektor etykiet y
                X = []
                y = []
                for s in signals:
                    ind = s.indicators or {}
                    # Cechy wejściowe (znormalizowane w przybliżeniu)
                    rsi = float(ind.get("rsi", 50)) / 100.0
                    macd = float(ind.get("macd_hist", 0)) * 1000.0  # Skalowanie małej wartości
                    bb = float(ind.get("bb_pct", 0.5))
                    vol = float(ind.get("volume_ratio", 1.0)) / 5.0  # Normowanie wolumenu
                    fund = float(s.funding_rate or 0.0) * 100.0

                    X.append([rsi, macd, bb, vol, fund])
                    y.append(1 if s.status == "WIN" else 0)

                X = np.array(X)
                y = np.array(y)

                # 3. Ucz model logistycznej regresji
                model = LogisticRegression(max_iter=1000)
                model.fit(X, y)

                # Oblicz dokładność
                predictions = model.predict(X)
                accuracy = float(accuracy_score(y, predictions))

                # 4. Oblicz wagi na podstawie ważności współczynników (coefficients)
                coefs = np.abs(model.coef_[0])
                total_coef = sum(coefs) if sum(coefs) > 0 else 1.0

                # Rozdziel 60 punktów proporcjonalnie do ważności wskaźników
                raw_weights = (coefs / total_coef) * 60
                
                # Zapewnij min. 2 punkty na wskaźnik, żeby żaden nie został całkowicie wyzerowany
                new_weights = {
                    "rsi": max(2, int(round(raw_weights[0]))),
                    "macd": max(2, int(round(raw_weights[1]))),
                    "bb": max(2, int(round(raw_weights[2]))),
                    "vol": max(2, int(round(raw_weights[3]))),
                    "funding": max(2, int(round(raw_weights[4]))),
                }

                # Wyrównaj sumę do dokładnie 60 punktów
                current_sum = sum(new_weights.values())
                diff = 60 - current_sum
                if diff != 0:
                    # Dodaj/odejmij różnicę do najsilniejszego wskaźnika
                    strongest = max(new_weights, key=new_weights.get)
                    new_weights[strongest] += diff

                # 5. Generuj logi decyzji
                old_weights = self.get_current_weights()
                new_logs = []
                
                for key in ["rsi", "macd", "bb", "vol", "funding"]:
                    o_w = old_weights.get(key, DEFAULT_WEIGHTS[key])
                    n_w = new_weights[key]
                    if n_w > o_w:
                        new_logs.append(f"Zwiększono wagę {key.upper()} ({o_w} -> {n_w}) z powodu wysokiej skuteczności prognostycznej.")
                    elif n_w < o_w:
                        new_logs.append(f"Zmniejszono wagę {key.upper()} ({o_w} -> {n_w}) - wykryto wzrost liczby fałszywych sygnałów.")

                if not new_logs:
                    new_logs.append("Wagi wskaźników stabilne - brak potrzeby modyfikacji w tej epoce.")

                # Dodaj wpis o dokładności
                new_logs.insert(0, f"Zakończono epokę uczenia na {len(signals)} sygnałach. Dokładność modelu: {accuracy*100:.1f}%.")

                # 6. Zapisz nowy stan modelu do bazy danych
                prev_state = session.query(MLModelState).order_by(MLModelState.updated_at.desc()).first()
                history = prev_state.history if prev_state and prev_state.history else []
                history.append(accuracy)
                # Ogranicz historię do ostatnich 20 wpisów
                if len(history) > 20:
                    history = history[-20:]

                # Połącz stare logi z nowymi (max 30 linii łącznie)
                old_logs = prev_state.logs if prev_state and prev_state.logs else []
                all_logs = new_logs + old_logs
                all_logs = all_logs[:30]

                new_state = MLModelState(
                    weights=new_weights,
                    accuracy=accuracy,
                    history=history,
                    logs=all_logs,
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(new_state)
                session.commit()

                logger.info(f"Trening zakończony sukcesem. Nowe wagi: {new_weights}. Accuracy: {accuracy*100:.1f}%")
                return {"success": True, "weights": new_weights, "accuracy": accuracy}

        except Exception as e:
            logger.error(f"Błąd podczas uczenia modelu ML: {e}", exc_info=True)
            return {"success": False, "reason": str(e)}


# Singleton
ml_engine = MLEngine()
