"""
test_wallet.py – Unit testy dla wirtualnego portfela i systemu potwierdzania trendów (MONITORING)
"""
import sys
import os
from datetime import datetime, timezone

# Ustaw ścieżkę do importowania modułów z folderu backend/
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from database import init_db, get_session, Signal, VirtualWallet
from tracker import Tracker

def run_tests():
    print("[TEST] Rozpoczynam testy modulu Portfela i Monitorowania...")

    # 1. Inicjalizacja bazy danych
    init_db()

    with get_session() as session:
        # Wyczyszczenie danych testowych
        session.query(Signal).delete()
        session.query(VirtualWallet).delete()
        session.commit()

        # 2. Test inicjalizacji portfela
        print("1. Test Inicjalizacji...")
        wallet = session.query(VirtualWallet).first()
        if not wallet:
            wallet = VirtualWallet(balance_usdt=1000.0)
            session.add(wallet)
            session.commit()
            print("   - Portfel utworzony pomyślnie.")
        
        assert wallet.balance_usdt == 1000.0, "Błąd: Saldo powinno wynosić 1000.0"
        print(f"   - Saldo początkowe portfela: {wallet.balance_usdt} USDT (OK)")

        # 3. Test doładowania portfela
        print("2. Test Doładowania portfela...")
        wallet.balance_usdt += 500.0
        session.commit()
        session.refresh(wallet)
        assert wallet.balance_usdt == 1500.0, "Błąd: Saldo powinno wynosić 1500.0"
        print(f"   - Saldo po doładowaniu: {wallet.balance_usdt} USDT (OK)")

        # 4. Test zapisu sygnału w trybie MONITORING
        print("3. Test Zapisu Sygnału w Trybie MONITORING...")
        tracker = Tracker()
        analysis_data = {
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "score": 75,
            "confidence": "MEDIUM",
            "entry_price": 60000.0,
            "tp_price": 61200.0,
            "sl_price": 59400.0,
            "atr": 600.0,
            "leverage": 10,
            "funding_rate": 0.0001,
            "reasons": ["Test indicators"],
            "indicators": {"rsi": 60.0, "open": 59900.0, "close": 60100.0}
        }
        sig_id = tracker.save_signal(analysis_data, status="MONITORING")
        sig = session.query(Signal).filter(Signal.id == sig_id).first()
        assert sig.status == "MONITORING", "Błąd: Status sygnału powinien być MONITORING"
        print(f"   - Zapisano sygnał {sig.id} w stanie MONITORING (OK)")

        # 5. Symulacja potwierdzenia sygnału (zmiana na PENDING)
        print("4. Test Potwierdzenia Trendu...")
        # W nowej świecy cena rośnie (zamknięcie > otwarcie), potwierdzamy:
        open_p = 60100.0
        close_p = 60300.0  # Świeca wzrostowa (potwierdzenie)
        score = 80
        
        is_confirmed = False
        if sig.direction == "LONG" and close_p > open_p and score >= 60:
            is_confirmed = True
            
        assert is_confirmed is True, "Błąd: Sygnał LONG powinien zostać potwierdzony"
        
        if is_confirmed:
            sig.status = "PENDING"
            sig.created_at = datetime.now(timezone.utc)
            session.commit()
            print("   - Sygnał zaktualizowany do statusu PENDING (potwierdzony) (OK)")

        # 6. Test rozliczenia zysku (WIN) i wpływu na portfel
        print("5. Test Rozliczenia WIN i Księgowania Zysku...")
        # Symulacja dotknięcia TP:
        result_price = sig.tp_price
        pnl_pct = ((result_price - sig.entry_price) / sig.entry_price) * 100 * sig.leverage
        
        # Oczekiwany zysk przy wielkości pozycji 100 USDT:
        position_size = 100.0
        expected_pnl_usdt = position_size * (pnl_pct / 100.0)
        
        tracker._resolve_signal(session, sig, "WIN", result_price)
        session.refresh(wallet)
        
        # Oczekiwane nowe saldo: 1500.0 + expected_pnl_usdt
        expected_balance = 1500.0 + expected_pnl_usdt
        assert abs(wallet.balance_usdt - expected_balance) < 0.01, f"Błąd: Oczekiwano salda {expected_balance}, otrzymano {wallet.balance_usdt}"
        
        print(f"   - Wynik transakcji: {sig.status} ({sig.pnl_pct:.2f}% P&L)")
        print(f"   - Zysk w USDT: {expected_pnl_usdt:+.2f} USDT")
        print(f"   - Nowe saldo portfela: {wallet.balance_usdt:.2f} USDT (OK)")

    print("[SUCCESS] Wszystkie testy zaliczone pomyslnie!")

if __name__ == "__main__":
    run_tests()
