"""
risk_manager.py – Kontrola ryzyka i limitow handlu
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from config import (
    MAX_OPEN_POSITIONS, MAX_DAILY_LOSS_PCT, MAX_POSITION_USDT
)

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Strzeze zasad risk management:
    - Max otwarte pozycje
    - Max dzienna strata (circuit breaker)
    - Nie duplikuj pozycji na tym samym symbolu
    """

    def __init__(self):
        self._open_positions: dict[str, dict] = {}   # symbol -> info
        self._daily_loss_pct: float = 0.0
        self._paused: bool = False
        self._pause_reason: str = ""

    @property
    def is_paused(self) -> bool:
        return self._paused

    def can_open_position(self, symbol: str) -> dict:
        """Sprawdza czy mozna otworzyc nowa pozycje."""
        if self._paused:
            return {"allowed": False, "reason": f"Bot wstrzymany: {self._pause_reason}"}

        if symbol in self._open_positions:
            return {"allowed": False, "reason": f"Juz masz otwarta pozycje na {symbol}"}

        if len(self._open_positions) >= MAX_OPEN_POSITIONS:
            return {"allowed": False, "reason": f"Max pozycji ({MAX_OPEN_POSITIONS}) osiagniete"}

        if abs(self._daily_loss_pct) >= MAX_DAILY_LOSS_PCT:
            self._pause("Max dzienna strata osiagnieta")
            return {"allowed": False, "reason": self._pause_reason}

        return {"allowed": True, "reason": ""}

    def register_open(self, symbol: str, trade_info: dict):
        """Rejestruje otwarta pozycje."""
        self._open_positions[symbol] = {
            **trade_info,
            "opened_at": datetime.now(timezone.utc).isoformat()
        }
        logger.info(f"[Risk] Pozycja otwarta: {symbol}. Aktywne: {len(self._open_positions)}")

    def register_close(self, symbol: str, pnl_pct: float = 0.0):
        """Rejestruje zamkniecie pozycji i aktualizuje dzienna strate."""
        self._open_positions.pop(symbol, None)
        self._daily_loss_pct += pnl_pct

        if pnl_pct < 0:
            logger.warning(f"[Risk] Strata: {pnl_pct:.2f}%  Dzien: {self._daily_loss_pct:.2f}%")
            if abs(self._daily_loss_pct) >= MAX_DAILY_LOSS_PCT:
                self._pause("Przekroczono max dzienna strate")

    def _pause(self, reason: str):
        """Wstrzymuje automatyczny trading."""
        self._paused = True
        self._pause_reason = reason
        logger.warning(f"[Risk] ⛔ CIRCUIT BREAKER: {reason}")

    def resume(self):
        """Reczne wznowienie tradingu."""
        self._paused = False
        self._pause_reason = ""
        logger.info("[Risk] Trading wznowiony")

    def reset_daily(self):
        """Reset statystyk dziennych (wywolywane o polnocy)."""
        self._daily_loss_pct = 0.0
        if self._paused and "dzienna strata" in self._pause_reason:
            self.resume()
        logger.info("[Risk] Reset dzienny")

    def get_status(self) -> dict:
        return {
            "paused":            self._paused,
            "pause_reason":      self._pause_reason,
            "open_positions":    len(self._open_positions),
            "max_positions":     MAX_OPEN_POSITIONS,
            "daily_loss_pct":    round(self._daily_loss_pct, 4),
            "max_daily_loss":    MAX_DAILY_LOSS_PCT,
            "active_symbols":    list(self._open_positions.keys()),
        }


risk_manager = RiskManager()
