@echo off
title Binance Leverage Bot
color 0A
cd /d "%~dp0"

echo.
echo  ============================================
echo   BINANCE LEVERAGE BOT - URUCHAMIANIE
echo  ============================================
echo.

:: ── 1. Zabij stary proces na porcie 8000 ───────────────
echo  [1/4] Sprawdzam port 8000...
powershell -NoProfile -Command "$p = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess; if($p){ Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Write-Host '       Zatrzymano stary proces' } else { Write-Host '       Port wolny' }"
echo.

:: ── 2. Sprawdz zaleznosci ───────────────────────────────
echo  [2/4] Sprawdzam zaleznosci Python...
python -c "import fastapi, uvicorn, pandas_ta, apscheduler" >nul 2>&1
if errorlevel 1 (
    echo  Instaluje zaleznosci - pierwsze uruchomienie, chwilke...
    pip install -r requirements.txt -q
    echo  Zainstalowano!
) else (
    echo       OK!
)
echo.

:: ── 3. Folder data ─────────────────────────────────────
if not exist "data" mkdir data

:: ── 4. Otworz przegladarke za 5 sekund (w tle) ─────────
echo  [3/4] Przegladarka otworzy sie za 5 sekund...
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 5; Start-Process 'http://localhost:8000'"
echo.

:: ── 5. Uruchom bota ─────────────────────────────────────
echo  [4/4] Uruchamiam bota...
echo.
echo  ============================================
echo   Dashboard: http://localhost:8000
echo   Zatrzymaj: Ctrl+C lub zamknij to okno
echo  ============================================
echo.

python backend\api.py

echo.
echo  Bot zatrzymany. Nacisnij dowolny klawisz...
pause >nul
