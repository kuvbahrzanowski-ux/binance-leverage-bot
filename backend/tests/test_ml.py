import os
import sys
import random
from datetime import datetime, timezone

# Add backend directory to path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)
os.chdir(os.path.abspath(os.path.join(backend_path, "..")))

from database import init_db, get_session, Signal
from ml_engine import ml_engine

def generate_mock_data():
    init_db()
    with get_session() as session:
        # Clear existing signals to have a clean test
        session.query(Signal).delete()
        session.commit()

        print("Generuje 30 mockowych sygnalow (15 WIN, 15 LOSS) dla testu ML...")
        symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
        
        for i in range(30):
            status = "WIN" if i % 2 == 0 else "LOSS"
            # Skorelowane wartosci indicators w zaleznosci od statusu
            if status == "WIN":
                rsi = random.uniform(30, 50)
                macd_hist = random.uniform(0.0005, 0.002)
            else:
                rsi = random.uniform(60, 85)
                macd_hist = random.uniform(-0.002, -0.0005)
                
            bb_pct = random.uniform(0.0, 1.0)
            volume_ratio = random.uniform(0.5, 3.0)
            funding_rate = random.uniform(-0.002, 0.002)
            direction = "LONG"

            sig = Signal(
                symbol=random.choice(symbols),
                direction=direction,
                score=random.randint(60, 95),
                confidence="MEDIUM",
                entry_price=100.0,
                tp_price=102.0,
                sl_price=99.0,
                atr=1.0,
                leverage=10,
                funding_rate=funding_rate,
                indicators={
                    "rsi": rsi,
                    "macd_hist": macd_hist,
                    "bb_pct": bb_pct,
                    "volume_ratio": volume_ratio
                },
                status=status,
                pnl_pct=2.0 if status == "WIN" else -1.0,
                created_at=datetime.now(timezone.utc)
            )
            session.add(sig)
        session.commit()
        print("Mockowe sygnaly zapisane w bazie!")

def run_test():
    generate_mock_data()
    print("\n--- URUCHAMIAM RETRAIN MODELU ---")
    res = ml_engine.retrain_model()
    print("Wynik retrain:", res)
    
    print("\n--- AKTUALNY STAN MOZGU BOTA (ML) ---")
    status = ml_engine.get_status()
    print(f"Accuracy: {status['accuracy']}%")
    print("Wagi wskaźników:")
    for k, v in status["weights"].items():
        print(f"  - {k.upper()}: {v} pkt")
    
    print("\nLogi decyzji modelu:")
    for l in status["logs"][:5]:
        print(f"  • {l}")

if __name__ == "__main__":
    run_test()
