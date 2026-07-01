# ⚡ Binance Leverage Bot – Dashboard

Bot do analizy i automatycznego tradingu na dźwigni **50x/100x** na Binance Futures.
Obsługuje **BTC, ETH, XRP** z analizą multi-timeframe co 5 minut.

---

## 🚀 Szybki start

### 1. Sklonuj / przejdź do folderu projektu

```bash
cd binance-leverage-bot
```

### 2. Uruchom automatyczny setup

```bash
python start.py
```

Skrypt sam:
- Sprawdzi wersję Pythona (wymagana 3.10+)
- Stworzy środowisko wirtualne
- Zainstaluje wszystkie zależności
- Poprosi o konfigurację `.env`
- Uruchomi serwer

### 3. Otwórz dashboard

```
http://localhost:8000
```

---

## ⚙️ Konfiguracja (`.env`)

Skopiuj `.env.example` → `.env` i uzupełnij:

```env
BINANCE_API_KEY=twoj_api_key
BINANCE_SECRET_KEY=twoj_secret_key
BINANCE_TESTNET=True          # False = prawdziwy Binance
TRADING_MODE=SIGNAL_ONLY      # Zacznij od SIGNAL_ONLY!
MAX_POSITION_USDT=100
DEFAULT_LEVERAGE=10
```

### Generowanie kluczy API Binance

1. Zaloguj się na [binance.com](https://binance.com)
2. Profil → **API Management**
3. Utwórz klucz → zaznacz **Futures**
4. **WYŁĄCZ** opcję Withdrawal (wypłaty)!
5. Skopiuj API Key i Secret do `.env`

---

## 🧪 Testowanie bez ryzyka

Użyj **Binance Testnet** (wirtualne pieniądze):
```
URL: https://testnet.binancefuture.com
BINANCE_TESTNET=True  (domyślnie)
```

---

## 📊 Funkcje dashboardu

| Funkcja | Opis |
|---------|------|
| **Karty BTC/ETH/XRP** | Live cena, sygnał, score, TP/SL |
| **Score 0-100** | Multi-timeframe scoring |
| **Wykres świecowy** | TradingView Lightweight Charts |
| **Sygnały LONG/SHORT** | Historia z wynikami WIN/LOSS |
| **Statystyki** | Winrate %, Profit Factor, Max Drawdown |
| **Aktywne pozycje** | PnL na żywo, cena likwidacji |
| **Sound alerts** | Różne dźwięki dla każdego zdarzenia |
| **Visual alerts** | Toasty, flash, konfetti |
| **Countdown** | 10s odliczanie przed auto-trade |
| **Tryby** | Signal Only / Auto Trade |
| **Dźwignia** | 10x / 25x / 50x / 100x |

---

## ⚠️ Ryzyko

> **WAŻNE**: Handel z dźwignią, szczególnie 50x/100x, wiąże się z ekstremalnym ryzykiem straty całego kapitału.
> Bot jest narzędziem analitycznym i NIE gwarantuje zysku.
> **Zawsze zaczynaj od SIGNAL_ONLY i Testnet!**

---

## 🏗️ Struktura projektu

```
binance-leverage-bot/
├── backend/
│   ├── api.py              ← FastAPI server (uruchom ten plik)
│   ├── config.py           ← Konfiguracja
│   ├── binance_client.py   ← Klient Binance Futures API
│   ├── indicators.py       ← Wskaźniki techniczne
│   ├── signal_engine.py    ← Silnik sygnałów (scoring)
│   ├── order_manager.py    ← Składanie zleceń
│   ├── risk_manager.py     ← Risk management
│   ├── tracker.py          ← Śledzenie skuteczności
│   └── database.py         ← Modele SQLite
├── frontend/
│   ├── index.html          ← Dashboard
│   ├── style.css           ← Premium dark CSS
│   └── app.js              ← Logika + WebSocket + Charts
├── data/                   ← Baza danych + logi
├── .env.example            ← Szablon konfiguracji
├── requirements.txt        ← Zależności Python
└── start.py                ← Skrypt startowy
```
