# Walkthrough – Deploy & ML Integration

Zrealizowaliśmy pełne przygotowanie bota do wdrożenia w chmurze (Render + Vercel) oraz zaimplementowaliśmy silnik **ciągłego uczenia maszynowego (ML)** z zakładką analiz w dashboardzie.

---

## 🛠️ Zrobione Zmiany

### 1. Baza Danych & Konfiguracja
- **PostgreSQL Support**: Zaktualizowano [database.py](file:///C:/Users/kacpe/Desktop/binance-leverage-bot/backend/database.py) oraz [config.py](file:///C:/Users/kacpe/Desktop/binance-leverage-bot/backend/config.py) do obsługi PostgreSQL za pomocą zmiennej środowiskowej `DATABASE_URL`. Bot automatycznie przełącza się na PostgreSQL w chmurze (np. Supabase/Render PG) lub lokalną SQLite w trybie deweloperskim.
- **MLModelState**: Dodano nową tabelę bazy danych przechowującą aktualne wagi wskaźników, dokładność (accuracy) oraz logi wyjaśniające proces uczenia.

### 2. Silnik ML (Machine Learning Engine)
- **Logistyczna Regresja**: Stworzono [ml_engine.py](file:///C:/Users/kacpe/Desktop/binance-leverage-bot/backend/ml_engine.py) bazujący na `scikit-learn`. Silnik automatycznie:
  - Pobiera rozstrzygnięte sygnały z bazy.
  - Trenuje model klasyfikacji, aby znaleźć korelacje między wartościami wskaźników a wygraną/przegraną.
  - Rozdziela 60 punktów z puli dynamicznej proporcjonalnie do ważności wskaźników.
  - Zapisuje uaktualniony stan i generuje logi decyzji (np. *„Zwiększono wagę MACD (15 -> 44)...”*).
- **Dynamiczne Ocenianie**: Zmodyfikowano [signal_engine.py](file:///C:/Users/kacpe/Desktop/binance-leverage-bot/backend/signal_engine.py), który zamiast sztywnych wag odpytuje silnik ML o aktualne wagi wskaźników przed kalkulacją score.

### 3. API & WebSockets
- Dodano endpointy `GET /api/ml/status` oraz `POST /api/ml/train` w [api.py](file:///C:/Users/kacpe/Desktop/binance-leverage-bot/backend/api.py).
- Wpięto automatyczne dotrenowanie modelu na końcu 5-minutowej pętli analiz rynkowych (po rozstrzygnięciu oczekujących sygnałów) i rozgłaszanie nowego stanu przez WebSockety.

### 4. Nowoczesny Frontend
- **Zakładka "Mózg Bota (ML)"**: Dodano w [index.html](file:///C:/Users/kacpe/Desktop/binance-leverage-bot/frontend/index.html) i oprogramowano w [app.js](file:///C:/Users/kacpe/Desktop/binance-leverage-bot/frontend/app.js) za pomocą natywnych wykresów HTML5 Canvas:
  - Wykres słupkowy dynamicznie przedstawiający wagi wskaźników (RSI, MACD, BB, Vol, Funding).
  - Wykres liniowy pokazujący dokładność (Accuracy) bota w ostatnich epokach uczenia.
  - Lista logów decyzji wyjaśniająca, dlaczego wagi uległy zmianie.
  - Przycisk ręcznego wywołania treningu.

---

## 🧪 Wyniki Testu Lokalnego

Uruchomiono skrypt weryfikacyjny [test_ml.py](file:///C:/Users/kacpe/Desktop/binance-leverage-bot/backend/tests/test_ml.py), który wygenerował 30 testowych sygnałów (15 WIN, 15 LOSS) z silną korelacją wygranych do wskaźnika MACD.

**Rezultat**:
Model pomyślnie wytrenował się osiągając wysoką dokładność i zaktualizował wagi:
- **MACD**: Wzrost wagi z 15 do **44 punktów** (wykryty jako kluczowy czynnik sukcesu).
- **RSI**: Spadek do 10 punktów.
- **BB, VOL, Funding**: Spadek do minimalnych 2 punktów.
- **Logi decyzji**: Wygenerowano poprawne podsumowanie słowne w dashboardzie.

---

## 🚀 Instrukcja Wdrożenia Chmurowego

### Krok 1: Wdrożenie Bazy Danych
1. Wejdź na [Supabase](https://supabase.com) lub stwórz darmową bazę PostgreSQL na platformie Render.
2. Skopiuj Connection String (Direct Connection URL).

### Krok 2: Wdrożenie Backend (Render)
1. Zaloguj się na [Render.com](https://render.com).
2. Wybierz **Blueprints** → połącz ze swoim repozytorium GitHub bota.
3. Plik `render.yaml` automatycznie skonfiguruje Web Service.
4. Wklej skopiowany URL bazy jako zmienną środowiskową `DATABASE_URL` w panelu Render.

### Krok 3: Wdrożenie Frontend (Vercel)
1. Zaloguj się na [Vercel.com](https://vercel.json).
2. Zaimportuj projekt bota.
3. Plik `vercel.json` automatycznie skieruje ruch na statyczne pliki w folderze `/frontend`.
4. W pliku `app.js` na samej górze zmień `API` na adres url Twojego wdrożonego backendu na Renderze (np. `https://binance-leverage-bot-backend.onrender.com`).
