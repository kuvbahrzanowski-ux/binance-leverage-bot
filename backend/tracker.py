"""
tracker.py – Sledzenie skutecznosci sygnalow i aktualizacja statystyk
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from database import Signal, Trade, DailyStats, get_session, VirtualWallet
from binance_client import client

logger = logging.getLogger(__name__)


class Tracker:
    """Zapisuje sygnaly i aktualizuje ich wynik (WIN/LOSS)."""

    def save_signal(self, analysis: dict, status: str = "PENDING") -> int:
        """Zapisuje nowy sygnal do bazy. Zwraca ID."""
        with get_session() as session:
            sig = Signal(
                symbol      = analysis["symbol"],
                direction   = analysis["direction"],
                score       = analysis["score"],
                confidence  = analysis["confidence"],
                entry_price = analysis["entry_price"],
                tp_price    = analysis["tp_price"],
                sl_price    = analysis["sl_price"],
                atr         = analysis.get("atr"),
                leverage    = analysis.get("leverage", 10),
                funding_rate = analysis.get("funding_rate", 0.0),
                reasons     = analysis.get("reasons", []),
                indicators  = analysis.get("indicators", {}),
                status      = status,
            )
            session.add(sig)
            session.commit()
            session.refresh(sig)
            return sig.id

    def save_trade(self, signal_id: Optional[int], order_data: dict,
                   entry_price: float, quantity: float,
                   tp: float, sl: float,
                   direction: str, symbol: str, leverage: int) -> int:
        """Zapisuje wykonane zlecenie."""
        with get_session() as session:
            trade = Trade(
                signal_id   = signal_id,
                symbol      = symbol,
                direction   = direction,
                order_id    = str(order_data.get("orderId", "")),
                quantity    = quantity,
                entry_price = entry_price,
                tp_price    = tp,
                sl_price    = sl,
                leverage    = leverage,
                status      = "OPEN",
            )
            session.add(trade)
            session.commit()
            session.refresh(trade)
            return trade.id

    def resolve_pending_signals(self):
        """
        Sprawdza PENDING sygnaly i aktualizuje status
        jezeli cena dotknela TP lub SL.
        """
        with get_session() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
            pending = session.query(Signal).filter(
                Signal.status == "PENDING",
                Signal.created_at >= cutoff,
            ).all()

            for sig in pending:
                try:
                    ticker = client.get_ticker(sig.symbol)
                    high   = float(ticker.get("highPrice", 0))
                    low    = float(ticker.get("lowPrice", 0))

                    if sig.direction == "LONG":
                        if high >= sig.tp_price:
                            self._resolve_signal(session, sig, "WIN", sig.tp_price)
                        elif low <= sig.sl_price:
                            self._resolve_signal(session, sig, "LOSS", sig.sl_price)
                    else:  # SHORT
                        if low <= sig.tp_price:
                            self._resolve_signal(session, sig, "WIN", sig.tp_price)
                        elif high >= sig.sl_price:
                            self._resolve_signal(session, sig, "LOSS", sig.sl_price)

                except Exception as e:
                    logger.warning(f"Blad resolve sygnalu {sig.id}: {e}")

            # Wygaszaj sygnaly starsze niz 4h
            old = session.query(Signal).filter(
                Signal.status == "PENDING",
                Signal.created_at < cutoff,
            ).all()
            for sig in old:
                sig.status = "EXPIRED"
            session.commit()

    def _resolve_signal(self, session, sig: Signal, status: str, result_price: float):
        """Ustawia wynik sygnalu i aktualizuje wirtualny portfel."""
        sig.status      = status
        sig.result_price = result_price
        sig.resolved_at  = datetime.now(timezone.utc)

        if sig.direction == "LONG":
            pnl_pct = ((result_price - sig.entry_price) / sig.entry_price) * 100 * sig.leverage
        else:
            pnl_pct = ((sig.entry_price - result_price) / sig.entry_price) * 100 * sig.leverage

        sig.pnl_pct = round(pnl_pct, 4)
        
        # Oblicz zysk/strate w USDT na podstawie wielkosci pozycji (MAX_POSITION_USDT)
        from config import MAX_POSITION_USDT
        pnl_usdt = MAX_POSITION_USDT * (pnl_pct / 100.0)
        
        # Zaktualizuj saldo wirtualnego portfela
        try:
            wallet = session.query(VirtualWallet).first()
            if not wallet:
                wallet = VirtualWallet(balance_usdt=1000.0)
                session.add(wallet)
            wallet.balance_usdt += pnl_usdt
            wallet.updated_at = datetime.now(timezone.utc)
            logger.info(f"Portfel zaktualizowany: PnL USDT: {pnl_usdt:+.2f}$, Saldo: {wallet.balance_usdt:.2f}$")
        except Exception as e:
            logger.error(f"Blad aktualizacji wirtualnego salda: {e}")

        session.commit()
        logger.info(f"Signal {sig.id} {sig.symbol} {status}  PnL: {sig.pnl_pct:.2f}%")

    def update_daily_stats(self):
        """Przelicza i zapisuje statystyki dzienne."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with get_session() as session:
            from sqlalchemy import func
            from config import SYMBOLS

            for symbol in SYMBOLS:
                signals = session.query(Signal).filter(
                    Signal.symbol == symbol,
                    Signal.created_at >= datetime.now(timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                    Signal.status.in_(["WIN", "LOSS"]),
                ).all()

                if not signals:
                    continue

                wins   = sum(1 for s in signals if s.status == "WIN")
                losses = sum(1 for s in signals if s.status == "LOSS")
                total  = wins + losses
                winrate = (wins / total * 100) if total > 0 else 0.0

                profits = [s.pnl_pct for s in signals if s.status == "WIN"  and s.pnl_pct]
                loss_vals = [abs(s.pnl_pct) for s in signals if s.status == "LOSS" and s.pnl_pct]
                profit_factor = sum(profits) / sum(loss_vals) if sum(loss_vals) > 0 else 0.0
                total_pnl     = sum(s.pnl_pct or 0 for s in signals)

                existing = session.query(DailyStats).filter(
                    DailyStats.date == today,
                    DailyStats.symbol == symbol,
                ).first()

                if existing:
                    existing.total_signals = total
                    existing.wins = wins
                    existing.losses = losses
                    existing.winrate = round(winrate, 2)
                    existing.total_pnl = round(total_pnl, 4)
                    existing.profit_factor = round(profit_factor, 4)
                else:
                    stat = DailyStats(
                        date=today, symbol=symbol,
                        total_signals=total, wins=wins, losses=losses,
                        winrate=round(winrate, 2),
                        total_pnl=round(total_pnl, 4),
                        profit_factor=round(profit_factor, 4),
                    )
                    session.add(stat)

                session.commit()

    def get_stats(self, symbol: Optional[str] = None) -> dict:
        """Zwraca statystyki ogolne lub dla konkretnego symbolu."""
        with get_session() as session:
            query = session.query(Signal).filter(
                Signal.status.in_(["WIN", "LOSS"])
            )
            if symbol:
                query = query.filter(Signal.symbol == symbol)

            signals = query.all()
            if not signals:
                return {"total": 0, "wins": 0, "losses": 0, "winrate": 0, "profit_factor": 0}

            wins   = sum(1 for s in signals if s.status == "WIN")
            losses = sum(1 for s in signals if s.status == "LOSS")
            total  = len(signals)

            profits   = [s.pnl_pct for s in signals if s.status == "WIN" and s.pnl_pct]
            loss_vals = [abs(s.pnl_pct) for s in signals if s.status == "LOSS" and s.pnl_pct]

            profit_factor = sum(profits) / sum(loss_vals) if sum(loss_vals) > 0 else 0.0
            avg_win  = sum(profits) / len(profits) if profits else 0
            avg_loss = sum(loss_vals) / len(loss_vals) if loss_vals else 0

            # Max drawdown (uproszczony)
            cumulative = 0.0
            peak = 0.0
            max_dd = 0.0
            for s in signals:
                cumulative += (s.pnl_pct or 0)
                if cumulative > peak:
                    peak = cumulative
                dd = peak - cumulative
                if dd > max_dd:
                    max_dd = dd

            return {
                "total":         total,
                "wins":          wins,
                "losses":        losses,
                "winrate":       round(wins / total * 100, 2) if total > 0 else 0,
                "profit_factor": round(profit_factor, 3),
                "avg_win_pct":   round(avg_win, 3),
                "avg_loss_pct":  round(avg_loss, 3),
                "avg_rr":        round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
                "total_pnl_pct": round(sum(s.pnl_pct or 0 for s in signals), 3),
                "max_drawdown":  round(max_dd, 3),
            }

    def get_recent_signals(self, limit: int = 50) -> list:
        """Ostatnie sygnaly z bazy."""
        with get_session() as session:
            signals = session.query(Signal).order_by(
                Signal.created_at.desc()
            ).limit(limit).all()
            return [
                {
                    "id":          s.id,
                    "symbol":      s.symbol,
                    "direction":   s.direction,
                    "score":       s.score,
                    "confidence":  s.confidence,
                    "entry_price": s.entry_price,
                    "tp_price":    s.tp_price,
                    "sl_price":    s.sl_price,
                    "leverage":    s.leverage,
                    "status":      s.status,
                    "pnl_pct":     s.pnl_pct,
                    "reasons":     s.reasons or [],
                    "indicators":  s.indicators or {},
                    "created_at":  s.created_at.isoformat() if s.created_at else None,
                    "resolved_at": s.resolved_at.isoformat() if s.resolved_at else None,
                }
                for s in signals
            ]


tracker = Tracker()
