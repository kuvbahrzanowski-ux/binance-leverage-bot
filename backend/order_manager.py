"""
order_manager.py – Skladanie i zarzadzanie zleceniami na Binance Futures
"""
import logging
import math
from typing import Optional
from datetime import datetime, timezone

from binance_client import client
from risk_manager import risk_manager
from config import (
    MAX_POSITION_USDT, RISK_PER_TRADE_PCT, DEFAULT_LEVERAGE
)

logger = logging.getLogger(__name__)


def get_quantity_precision(symbol: str) -> int:
    """Pobiera precyzje ilosci dla symbolu."""
    try:
        info = client.get_symbol_info(symbol)
        if not info:
            return 3
        for f in info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                step = float(f["stepSize"])
                return max(0, int(round(-math.log10(step))))
    except Exception:
        pass
    return 3


def get_price_precision(symbol: str) -> int:
    """Pobiera precyzje ceny dla symbolu."""
    try:
        info = client.get_symbol_info(symbol)
        if not info:
            return 2
        for f in info.get("filters", []):
            if f["filterType"] == "PRICE_FILTER":
                tick = float(f["tickSize"])
                return max(0, int(round(-math.log10(tick))))
    except Exception:
        pass
    return 2


def calculate_quantity(symbol: str, entry_price: float,
                        sl_price: float, leverage: int,
                        account_balance: float) -> float:
    """
    Oblicza ilosc kontraktu na podstawie ryzyka.
    risk_usdt = balance * RISK_PCT / 100
    qty = risk_usdt / (|entry - sl| / entry * entry)  <-- uproszczenie
    """
    risk_usdt = min(
        account_balance * RISK_PER_TRADE_PCT / 100,
        MAX_POSITION_USDT * RISK_PER_TRADE_PCT / 100,
    )

    sl_distance_pct = abs(entry_price - sl_price) / entry_price
    if sl_distance_pct <= 0:
        sl_distance_pct = 0.005  # 0.5% min

    # Wartosc pozycji jaka mozemy zajac
    position_value = risk_usdt / sl_distance_pct
    position_value = min(position_value, MAX_POSITION_USDT)

    qty = position_value / entry_price
    precision = get_quantity_precision(symbol)
    qty = math.floor(qty * (10 ** precision)) / (10 ** precision)

    return max(qty, 10 ** -precision)  # min 1 jednostka


class OrderManager:
    """Zarządza skladaniem zlecen na Binance Futures."""

    def open_position(
        self,
        symbol: str,
        direction: str,      # LONG | SHORT
        entry_price: float,
        tp_price: float,
        sl_price: float,
        leverage: int,
        signal_id: Optional[int] = None,
    ) -> dict:
        """
        Otwiera pozycje LONG lub SHORT z automatycznym TP i SL.
        Zwraca slownik z detalami.
        """
        try:
            # ── Sprawdz risk manager ──────────────────────────
            check = risk_manager.can_open_position(symbol)
            if not check["allowed"]:
                return {"success": False, "error": check["reason"]}

            # ── Pobierz saldo ─────────────────────────────────
            balances  = client.get_balance()
            usdt_bal  = next(
                (float(b["availableBalance"]) for b in balances if b["asset"] == "USDT"),
                0.0
            )
            if usdt_bal < 10:
                return {"success": False, "error": f"Za niskie saldo: {usdt_bal:.2f} USDT"}

            # ── Ustaw dzwignie i margin ───────────────────────
            client.set_margin_type(symbol, "ISOLATED")
            client.set_leverage(symbol, leverage)

            # ── Oblicz ilosc ──────────────────────────────────
            qty = calculate_quantity(symbol, entry_price, sl_price, leverage, usdt_bal)
            logger.info(f"Otwieranie {direction} {symbol} qty={qty} lev={leverage}x")

            # ── Zlozenie zlecenia MARKET ──────────────────────
            side       = "BUY" if direction == "LONG" else "SELL"
            order      = client.place_order(symbol, side, "MARKET", qty)
            order_id   = order.get("orderId")
            fill_price = float(order.get("avgPrice") or entry_price)

            # ── Stop Loss ─────────────────────────────────────
            sl_side    = "SELL" if direction == "LONG" else "BUY"
            sl_order   = client.place_stop_order(
                symbol, sl_side, sl_price, qty, "STOP_MARKET"
            )

            # ── Take Profit ───────────────────────────────────
            tp_order   = client.place_stop_order(
                symbol, sl_side, tp_price, qty, "TAKE_PROFIT_MARKET"
            )

            result = {
                "success":      True,
                "symbol":       symbol,
                "direction":    direction,
                "quantity":     qty,
                "entry_price":  fill_price,
                "tp_price":     tp_price,
                "sl_price":     sl_price,
                "leverage":     leverage,
                "order_id":     order_id,
                "sl_order_id":  sl_order.get("orderId"),
                "tp_order_id":  tp_order.get("orderId"),
                "opened_at":    datetime.now(timezone.utc).isoformat(),
            }

            # ── Zarejestruj w risk managerze ──────────────────
            risk_manager.register_open(symbol, result)

            logger.info(f"✅ Pozycja otwarta: {direction} {symbol} @ {fill_price}")
            return result

        except Exception as e:
            logger.error(f"Blad otwarcia pozycji {symbol}: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def close_position(self, symbol: str, direction: str, quantity: float) -> dict:
        """Zamknij pozycje rynkowo."""
        try:
            result = client.close_position(symbol, quantity, direction)
            risk_manager.register_close(symbol)
            logger.info(f"✅ Pozycja zamknieta: {symbol}")
            return {"success": True, "order": result}
        except Exception as e:
            logger.error(f"Blad zamkniecia pozycji {symbol}: {e}")
            return {"success": False, "error": str(e)}

    def close_all(self) -> list:
        """EMERGENCY: zamknij wszystkie pozycje."""
        results = []
        try:
            positions = client.get_positions()
            for pos in positions:
                symbol = pos["symbol"]
                amt    = float(pos["positionAmt"])
                if amt == 0:
                    continue
                direction = "LONG" if amt > 0 else "SHORT"
                r = self.close_position(symbol, direction, abs(amt))
                results.append(r)
        except Exception as e:
            logger.error(f"Blad close all: {e}")
        return results

    def get_positions_info(self) -> list:
        """Aktualnie otwarte pozycje z PnL."""
        try:
            raw = client.get_positions()
            return [{
                "symbol":       p["symbol"],
                "direction":    "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                "quantity":     abs(float(p["positionAmt"])),
                "entry_price":  float(p.get("entryPrice", 0)),
                "mark_price":   float(p.get("markPrice", 0)),
                "pnl_usdt":     float(p.get("unRealizedProfit", 0)),
                "leverage":     int(p.get("leverage", DEFAULT_LEVERAGE)),
                "liquidation":  float(p.get("liquidationPrice", 0)),
            } for p in raw if float(p.get("positionAmt", 0)) != 0]
        except Exception as e:
            logger.error(f"Blad pobierania pozycji: {e}")
            return []


order_manager = OrderManager()
