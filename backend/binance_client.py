"""
binance_client.py – Klient Binance Futures (publiczne + prywatne API)
"""
import time
import hmac
import hashlib
import requests
import logging
from typing import Optional
from config import (
    BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_TESTNET
)

logger = logging.getLogger(__name__)

# ── URL bazowe ────────────────────────────────────────────────
BASE_URL  = "https://testnet.binancefuture.com" if BINANCE_TESTNET else "https://fapi.binance.com"
RECV_WINDOW = 5000


class BinanceClient:
    """Klient HTTP dla Binance Futures REST API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": BINANCE_API_KEY,
            "Content-Type": "application/x-www-form-urlencoded",
        })

    # ── Helpers ──────────────────────────────────────────────

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = RECV_WINDOW
        query = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(
            BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    def _get(self, path: str, params: dict = None, signed=False) -> dict:
        if params is None:
            params = {}
        if signed:
            params = self._sign(params)
        r = self.session.get(f"{BASE_URL}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, params: dict = None) -> dict:
        if params is None:
            params = {}
        params = self._sign(params)
        r = self.session.post(f"{BASE_URL}{path}", data=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str, params: dict = None) -> dict:
        if params is None:
            params = {}
        params = self._sign(params)
        r = self.session.delete(f"{BASE_URL}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    # ── Dane publiczne ────────────────────────────────────────

    def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        """Pobiera świece OHLCV."""
        data = self._get("/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })
        return [{
            "open_time": k[0],
            "open":  float(k[1]),
            "high":  float(k[2]),
            "low":   float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": k[6],
        } for k in data]

    def get_ticker(self, symbol: str) -> dict:
        """Aktualny ticker (cena, wolumen 24h, zmiana)."""
        return self._get("/fapi/v1/ticker/24hr", {"symbol": symbol})

    def get_mark_price(self, symbol: str) -> dict:
        """Mark price + funding rate."""
        return self._get("/fapi/v1/premiumIndex", {"symbol": symbol})

    def get_open_interest(self, symbol: str) -> dict:
        """Open Interest (liczba otwartych kontraktów)."""
        return self._get("/fapi/v1/openInterest", {"symbol": symbol})

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        """Orderbook (bids/asks)."""
        return self._get("/fapi/v1/depth", {"symbol": symbol, "limit": limit})

    def get_funding_history(self, symbol: str, limit: int = 5) -> list:
        """Historia funding rate."""
        return self._get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})

    # ── Konto ─────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Saldo konta Futures."""
        return self._get("/fapi/v2/account", signed=True)

    def get_balance(self) -> list:
        """Lista sald."""
        return self._get("/fapi/v2/balance", signed=True)

    def get_positions(self) -> list:
        """Wszystkie otwarte pozycje."""
        data = self._get("/fapi/v2/positionRisk", signed=True)
        return [p for p in data if float(p.get("positionAmt", 0)) != 0]

    def get_open_orders(self, symbol: str) -> list:
        """Otwarte zlecenia dla symbolu."""
        return self._get("/fapi/v1/openOrders", {"symbol": symbol}, signed=True)

    # ── Zlecenia ──────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Ustaw dźwignię dla symbolu."""
        return self._post("/fapi/v1/leverage", {
            "symbol": symbol, "leverage": leverage
        })

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> dict:
        """Ustaw typ marginu: ISOLATED lub CROSS."""
        try:
            return self._post("/fapi/v1/marginType", {
                "symbol": symbol, "marginType": margin_type
            })
        except Exception as e:
            # Ignoruj błąd jeśli margin type już ustawiony
            if "No need to change margin type" in str(e):
                return {"msg": "already set"}
            raise

    def place_order(
        self,
        symbol: str,
        side: str,          # BUY | SELL
        order_type: str,    # MARKET | LIMIT
        quantity: float,
        price: Optional[float] = None,
        reduce_only: bool = False,
        time_in_force: str = "GTC",
        position_side: str = "BOTH",
    ) -> dict:
        """Złóż zlecenie na Futures."""
        params = {
            "symbol":       symbol,
            "side":         side,
            "type":         order_type,
            "quantity":     f"{quantity:.6f}",
            "positionSide": position_side,
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        if order_type == "LIMIT":
            params["price"] = f"{price:.4f}"
            params["timeInForce"] = time_in_force
        return self._post("/fapi/v1/order", params)

    def place_stop_order(
        self,
        symbol: str,
        side: str,
        stop_price: float,
        quantity: float,
        order_type: str = "STOP_MARKET",
        reduce_only: bool = True,
    ) -> dict:
        """Stop loss / Take profit zlecenie."""
        return self._post("/fapi/v1/order", {
            "symbol":      symbol,
            "side":        side,
            "type":        order_type,
            "stopPrice":   f"{stop_price:.4f}",
            "quantity":    f"{quantity:.6f}",
            "reduceOnly":  "true" if reduce_only else "false",
            "timeInForce": "GTC",
        })

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Anuluj zlecenie."""
        return self._delete("/fapi/v1/order", {
            "symbol": symbol, "orderId": order_id
        })

    def cancel_all_orders(self, symbol: str) -> dict:
        """Anuluj wszystkie zlecenia dla symbolu."""
        return self._delete("/fapi/v1/allOpenOrders", {"symbol": symbol})

    def close_position(self, symbol: str, quantity: float, side: str) -> dict:
        """Zamknij pozycję zleceném market."""
        close_side = "SELL" if side == "LONG" else "BUY"
        return self.place_order(
            symbol=symbol,
            side=close_side,
            order_type="MARKET",
            quantity=quantity,
            reduce_only=True,
        )

    def get_exchange_info(self) -> dict:
        """Info o symbolach (precyzja, min qty itp.)."""
        return self._get("/fapi/v1/exchangeInfo")

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Info o konkretnym symbolu."""
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return None


# Singleton
client = BinanceClient()
