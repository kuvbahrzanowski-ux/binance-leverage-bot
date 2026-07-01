"""
api.py – FastAPI REST + WebSocket server
Uruchom: python api.py
"""
import asyncio
import json
import logging
import sys
import os
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import BaseModel

# Dodaj folder backend do sciezki
sys.path.insert(0, os.path.dirname(__file__))

from config import (
    HOST, PORT, SYMBOLS, ANALYZE_INTERVAL_SEC,
    SIGNAL_THRESHOLD, DEFAULT_LEVERAGE, TRADING_MODE
)
from database import init_db, get_session, VirtualWallet, Signal
from signal_engine import analyze_all, analyze_symbol
from tracker import tracker
from order_manager import order_manager
from risk_manager import risk_manager
from binance_client import client
from ml_engine import ml_engine

# Upewnij się, że folder logów i danych istnieje
os.makedirs("data", exist_ok=True)

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("api")

# ── FastAPI ───────────────────────────────────────────────────
app = FastAPI(title="Binance Leverage Bot", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serwuj frontend statycznie
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

# ── Stan globalny ─────────────────────────────────────────────
state = {
    "last_analyses":  {},       # symbol -> dict
    "trading_mode":  TRADING_MODE,
    "leverage":      DEFAULT_LEVERAGE,
    "last_update":   None,
    "countdown":     {},        # symbol -> int (sekund do auto-trade)
}

# ── WebSocket manager ─────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        msg = json.dumps(data, default=str)
        for ws in list(self.active):
            try:
                await ws.send_text(msg)
            except Exception:
                self.active.remove(ws)

ws_manager = ConnectionManager()

# ── Scheduler – analiza co 5 minut ───────────────────────────
scheduler = AsyncIOScheduler(timezone="UTC")

async def run_analysis():
    """Glowna petla analizy – uruchamiana co 5 min przez scheduler."""
    logger.info("▶ Uruchamiam analize rynku...")
    analyses = analyze_all(leverage=state["leverage"])

    for a in analyses:
        symbol = a["symbol"]
        state["last_analyses"][symbol] = a
        state["last_update"] = datetime.now(timezone.utc).isoformat()

        # Sprawdź, czy dla tego symbolu istnieje aktywny sygnał monitorowany w bazie
        monitoring_sig = None
        try:
            with get_session() as session:
                monitoring_sig = session.query(Signal).filter(
                    Signal.symbol == symbol,
                    Signal.status == "MONITORING"
                ).order_by(Signal.created_at.desc()).first()
        except Exception as e:
            logger.error(f"Błąd sprawdzania statusu monitorowania dla {symbol}: {e}")

        if monitoring_sig:
            # Sprawdzamy czy trend został potwierdzony
            indicators = a.get("indicators", {})
            open_p = indicators.get("open", 0)
            close_p = indicators.get("close", 0)
            is_confirmed = False

            if monitoring_sig.direction == "LONG":
                # Dla LONG: Świeca zamknęła się wzrostowo (close > open) i score wciąż >= SIGNAL_THRESHOLD
                if close_p > open_p and a["score"] >= SIGNAL_THRESHOLD:
                    is_confirmed = True
            elif monitoring_sig.direction == "SHORT":
                # Dla SHORT: Świeca zamknęła się spadkowo (close < open) i score wciąż >= SIGNAL_THRESHOLD
                if close_p < open_p and a["score"] >= SIGNAL_THRESHOLD:
                    is_confirmed = True

            if is_confirmed:
                # Potwierdzony! Zmieniamy status z MONITORING na PENDING (aktywny) i wchodzimy
                try:
                    with get_session() as session:
                        db_sig = session.query(Signal).filter(Signal.id == monitoring_sig.id).first()
                        if db_sig:
                            db_sig.status = "PENDING"
                            db_sig.created_at = datetime.now(timezone.utc)  # odświeżamy czas
                            session.commit()
                            
                            a["signal_id"] = db_sig.id
                            logger.info(f"🎯 POTWIERDZONO SYGNAŁ {db_sig.direction} {symbol}! Zmiana statusu na PENDING.")

                            # Powiadomienie przez WebSocket o aktywacji sygnału
                            await ws_manager.broadcast({
                                "type":    "NEW_SIGNAL",
                                "payload": a,
                            })

                            # AUTO TRADE z odliczaniem
                            if state["trading_mode"] == "AUTO_TRADE" and not risk_manager.is_paused:
                                asyncio.create_task(
                                    auto_trade_countdown(a, db_sig.id)
                                )
                except Exception as e:
                    logger.error(f"Błąd aktywacji sygnału z monitorowania dla {symbol}: {e}")
            else:
                # Anulowany/Wygasły (brak potwierdzenia lub score spadł)
                try:
                    with get_session() as session:
                        db_sig = session.query(Signal).filter(Signal.id == monitoring_sig.id).first()
                        if db_sig:
                            db_sig.status = "EXPIRED"
                            session.commit()
                            logger.info(f"❌ Anulowano monitorowanie {db_sig.direction} {symbol} (brak potwierdzenia trendu, open={open_p}, close={close_p}, score={a['score']})")
                            
                            # Wyślij aktualizację anulowanego sygnału do UI
                            await ws_manager.broadcast({
                                "type": "SIGNAL_EXPIRED",
                                "payload": {"signal_id": db_sig.id, "symbol": symbol}
                            })
                except Exception as e:
                    logger.error(f"Błąd wygaszania sygnału monitorowania dla {symbol}: {e}")

        else:
            # Brak aktywnego monitorowania. Jeśli score przekracza próg – zaczynamy monitorowanie!
            if a["score"] >= SIGNAL_THRESHOLD:
                try:
                    sig_id = tracker.save_signal(a, status="MONITORING")
                    logger.info(f"🔍 Rozpoczęto monitorowanie potencjalnego trendu {a['direction']} {symbol} (score={a['score']})")
                    
                    # Powiadom UI przez WebSocket
                    await ws_manager.broadcast({
                        "type": "MONITORING_START",
                        "payload": {
                            "signal_id": sig_id,
                            "symbol": symbol,
                            "direction": a["direction"],
                            "score": a["score"],
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                    })
                except Exception as e:
                    logger.error(f"Błąd zapisu sygnału monitorowania dla {symbol}: {e}")

    # Rozstrzygaj pending sygnaly
    tracker.resolve_pending_signals()
    tracker.update_daily_stats()

    # Retrain ML model and update weights
    try:
        train_res = ml_engine.retrain_model()
        if train_res.get("success"):
            await ws_manager.broadcast({
                "type": "ML_STATUS_UPDATE",
                "payload": ml_engine.get_status()
            })
    except Exception as e:
        logger.error(f"Blad automatycznego uczenia ML: {e}")

    # Wyslij aktualizacje statystyk
    await ws_manager.broadcast({
        "type":    "STATS_UPDATE",
        "payload": tracker.get_stats(),
    })

    logger.info(f"✅ Analiza zakonczona. Symbole: {[a['symbol'] for a in analyses]}")


async def auto_trade_countdown(analysis: dict, signal_id: int):
    """Odliczanie 10s przed zlozeniem zlecenia (mozna anulowac z UI)."""
    symbol = analysis["symbol"]
    for i in range(10, 0, -1):
        state["countdown"][symbol] = i
        await ws_manager.broadcast({
            "type":    "COUNTDOWN",
            "symbol":  symbol,
            "seconds": i,
            "signal":  analysis,
        })
        await asyncio.sleep(1)

    # Sprawdz czy nie anulowano
    if state["countdown"].get(symbol, 0) <= 0:
        logger.info(f"Zlecenie {symbol} anulowane przez uzytkownika")
        return

    state["countdown"].pop(symbol, None)

    result = order_manager.open_position(
        symbol     = symbol,
        direction  = analysis["direction"],
        entry_price = analysis["entry_price"],
        tp_price   = analysis["tp_price"],
        sl_price   = analysis["sl_price"],
        leverage   = state["leverage"],
        signal_id  = signal_id,
    )

    await ws_manager.broadcast({
        "type":    "TRADE_OPENED" if result["success"] else "TRADE_ERROR",
        "payload": result,
    })

# ── Scheduler daily reset ─────────────────────────────────────
async def daily_reset():
    risk_manager.reset_daily()
    await ws_manager.broadcast({"type": "DAILY_RESET"})

# ── REST Endpoints ────────────────────────────────────────────

@app.get("/")
async def index():
    path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return {"status": "Binance Leverage Bot API running"}

@app.get("/style.css")
async def serve_css():
    return FileResponse(os.path.join(FRONTEND_DIR, "style.css"), media_type="text/css")

@app.get("/app.js")
async def serve_js():
    return FileResponse(os.path.join(FRONTEND_DIR, "app.js"), media_type="application/javascript")


@app.get("/api/market/{symbol}")
async def get_market(symbol: str):
    """Live dane rynkowe dla symbolu."""
    try:
        ticker = client.get_ticker(symbol.upper())
        mark   = client.get_mark_price(symbol.upper())
        oi     = client.get_open_interest(symbol.upper())
        return {
            "symbol":      symbol.upper(),
            "price":       float(ticker.get("lastPrice", 0)),
            "change_24h":  float(ticker.get("priceChangePercent", 0)),
            "volume_24h":  float(ticker.get("volume", 0)),
            "mark_price":  float(mark.get("markPrice", 0)),
            "funding_rate": float(mark.get("lastFundingRate", 0)),
            "open_interest": float(oi.get("openInterest", 0)),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/klines/{symbol}")
async def get_klines(symbol: str, interval: str = "5m", limit: int = 100):
    """Swiecy do wykresu frontendowego."""
    try:
        klines = client.get_klines(symbol.upper(), interval, limit)
        return klines
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/signals")
async def get_signals(symbol: Optional[str] = None, limit: int = 50):
    """Ostatnie sygnaly."""
    signals = tracker.get_recent_signals(limit)
    if symbol:
        signals = [s for s in signals if s["symbol"] == symbol.upper()]
    return signals


@app.get("/api/analysis")
async def get_current_analysis():
    """Aktualny wynik analizy (last run)."""
    return {
        "analyses":   list(state["last_analyses"].values()),
        "last_update": state["last_update"],
        "mode":        state["trading_mode"],
        "leverage":    state["leverage"],
    }


@app.get("/api/stats")
async def get_stats(symbol: Optional[str] = None):
    """Statystyki skutecznosci."""
    overall = tracker.get_stats(symbol)
    per_symbol = {}
    for sym in SYMBOLS:
        per_symbol[sym] = tracker.get_stats(sym)
    return {
        "overall":    overall,
        "per_symbol": per_symbol,
        "risk":       risk_manager.get_status(),
    }


@app.get("/api/ml/status")
async def get_ml_status():
    """Zwraca stan uczenia maszynowego."""
    return ml_engine.get_status()


@app.post("/api/ml/train")
async def trigger_ml_train():
    """Ręcznie wymusza proces uczenia."""
    res = ml_engine.retrain_model()
    await ws_manager.broadcast({
        "type": "ML_STATUS_UPDATE",
        "payload": ml_engine.get_status()
    })
    return res


class DepositRequest(BaseModel):
    amount: float


@app.get("/api/wallet")
async def get_wallet():
    """Pobiera aktualne saldo wirtualnego portfela."""
    try:
        with get_session() as session:
            wallet = session.query(VirtualWallet).first()
            if not wallet:
                wallet = VirtualWallet(balance_usdt=1000.0)
                session.add(wallet)
                session.commit()
                session.refresh(wallet)
            return {"balance_usdt": round(wallet.balance_usdt, 2)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania salda: {str(e)}")


@app.post("/api/wallet/deposit")
async def deposit_funds(req: DepositRequest):
    """Zwiększa wirtualne saldo portfela."""
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Kwota doładowania musi być większa od zera")
    try:
        with get_session() as session:
            wallet = session.query(VirtualWallet).first()
            if not wallet:
                wallet = VirtualWallet(balance_usdt=1000.0)
                session.add(wallet)
                session.commit()
                session.refresh(wallet)
            wallet.balance_usdt += req.amount
            wallet.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(wallet)
            
            # Poinformuj UI przez WebSocket
            await ws_manager.broadcast({
                "type": "WALLET_UPDATE",
                "payload": {"balance_usdt": round(wallet.balance_usdt, 2)}
            })
            
            return {"status": "success", "balance_usdt": round(wallet.balance_usdt, 2)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd doładowania portfela: {str(e)}")


@app.post("/api/wallet/reset")
async def reset_wallet():
    """Resetuje wirtualne saldo portfela do 1000 USDT."""
    try:
        with get_session() as session:
            wallet = session.query(VirtualWallet).first()
            if not wallet:
                wallet = VirtualWallet(balance_usdt=1000.0)
                session.add(wallet)
            else:
                wallet.balance_usdt = 1000.0
                wallet.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(wallet)

            await ws_manager.broadcast({
                "type": "WALLET_UPDATE",
                "payload": {"balance_usdt": round(wallet.balance_usdt, 2)}
            })

            return {"status": "reset", "balance_usdt": round(wallet.balance_usdt, 2)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd resetu portfela: {str(e)}")


@app.get("/api/positions")
async def get_positions():
    """Aktualne otwarte pozycje."""
    try:
        return order_manager.get_positions_info()
    except Exception as e:
        return []


@app.get("/api/balance")
async def get_balance():
    """Saldo portfela."""
    try:
        balances = client.get_balance()
        return [b for b in balances if float(b.get("balance", 0)) > 0]
    except Exception as e:
        return {"error": str(e), "note": "Sprawdz klucze API"}


# ── POST endpoints ────────────────────────────────────────────

class TradeRequest(BaseModel):
    symbol:    str
    direction: str
    leverage:  int = 10

class SettingsRequest(BaseModel):
    mode:    Optional[str] = None   # SIGNAL_ONLY | AUTO_TRADE
    leverage: Optional[int] = None

class CancelRequest(BaseModel):
    symbol: str

@app.post("/api/trade")
async def manual_trade(req: TradeRequest):
    """Reczne zlecenie."""
    analysis = state["last_analyses"].get(req.symbol.upper())
    if not analysis:
        raise HTTPException(400, "Brak analizy dla tego symbolu. Poczekaj na kolejny cykl.")
    result = order_manager.open_position(
        symbol      = req.symbol.upper(),
        direction   = req.direction.upper(),
        entry_price = analysis["entry_price"],
        tp_price    = analysis["tp_price"],
        sl_price    = analysis["sl_price"],
        leverage    = req.leverage,
    )
    await ws_manager.broadcast({"type": "TRADE_OPENED", "payload": result})
    return result


@app.post("/api/trade/close")
async def close_trade(req: CancelRequest):
    """Zamknij pozycje dla symbolu."""
    positions = order_manager.get_positions_info()
    pos = next((p for p in positions if p["symbol"] == req.symbol.upper()), None)
    if not pos:
        raise HTTPException(404, "Brak otwartej pozycji dla tego symbolu")
    result = order_manager.close_position(pos["symbol"], pos["direction"], pos["quantity"])
    await ws_manager.broadcast({"type": "TRADE_CLOSED", "payload": result})
    return result


@app.post("/api/trade/close_all")
async def close_all_trades():
    """Emergency – zamknij wszystkie pozycje."""
    results = order_manager.close_all()
    await ws_manager.broadcast({"type": "ALL_CLOSED", "payload": results})
    return results


@app.post("/api/trade/cancel_countdown")
async def cancel_countdown(req: CancelRequest):
    """Anuluj odliczanie auto-trade."""
    state["countdown"][req.symbol.upper()] = 0
    return {"cancelled": True}


@app.post("/api/settings")
async def update_settings(req: SettingsRequest):
    """Zmien tryb lub dzwignie."""
    if req.mode in ("SIGNAL_ONLY", "AUTO_TRADE"):
        state["trading_mode"] = req.mode
        logger.info(f"Tryb zmieniony na: {req.mode}")
    if req.leverage:
        from config import MAX_LEVERAGE
        if 1 <= req.leverage <= MAX_LEVERAGE:
            state["leverage"] = req.leverage
    await ws_manager.broadcast({
        "type": "SETTINGS_CHANGED",
        "mode": state["trading_mode"],
        "leverage": state["leverage"],
    })
    return {"mode": state["trading_mode"], "leverage": state["leverage"]}


@app.post("/api/risk/resume")
async def resume_trading():
    """Wznow trading po circuit breaker."""
    risk_manager.resume()
    return {"resumed": True}


@app.post("/api/analyze_now")
async def trigger_analysis():
    """Wymusz natychmiastowa analize (nie czekaj 5 min)."""
    asyncio.create_task(run_analysis())
    return {"triggered": True}


# ── WebSocket ─────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        wallet_bal = 1000.0
        try:
            with get_session() as session:
                wallet = session.query(VirtualWallet).first()
                if wallet:
                    wallet_bal = wallet.balance_usdt
        except Exception:
            pass

        # Wyslij aktualny stan po polaczeniu
        await websocket.send_json({
            "type":      "CONNECTED",
            "analyses":  list(state["last_analyses"].values()),
            "mode":      state["trading_mode"],
            "leverage":  state["leverage"],
            "last_update": state["last_update"],
            "ml_status":   ml_engine.get_status(),
            "wallet_balance": round(wallet_bal, 2),
        })
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ── Startup ───────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    try:
        init_db()
        # Analiza od razu przy starcie
        asyncio.create_task(run_analysis())
        # Harmonogram co 5 minut
        scheduler.add_job(run_analysis, "interval", seconds=ANALYZE_INTERVAL_SEC, id="analysis")
        # Reset dzienny o polnocy UTC
        scheduler.add_job(daily_reset, "cron", hour=0, minute=0, id="daily_reset")
        scheduler.start()
        logger.info(f"🚀 Bot uruchomiony! Tryb: {state['trading_mode']}  Dzwignia: {state['leverage']}x")
    except Exception as e:
        import traceback
        print("CRITICAL STARTUP ERROR:")
        traceback.print_exc()
        raise e


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


if __name__ == "__main__":
    uvicorn.run("api:app", host=HOST, port=PORT, reload=False)
