#!/usr/bin/env python3
"""
start.py – Skrypt startowy bota
Uruchom: python start.py
"""
import os
import sys
import subprocess

VENV = ".venv"
REQ  = "requirements.txt"


def check_python():
    if sys.version_info < (3, 10):
        print("❌ Wymagany Python 3.10+")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")


def setup_venv():
    if not os.path.exists(VENV):
        print("📦 Tworzę środowisko wirtualne...")
        subprocess.run([sys.executable, "-m", "venv", VENV], check=True)

    pip = os.path.join(VENV, "Scripts", "pip.exe") if os.name == "nt" else os.path.join(VENV, "bin", "pip")
    print("📥 Instaluję zależności...")
    subprocess.run([pip, "install", "-q", "-r", REQ], check=True)
    print("✅ Zależności zainstalowane")


def check_env():
    if not os.path.exists(".env"):
        print("⚠️  Brak pliku .env!")
        print("   Skopiuj .env.example jako .env i uzupełnij klucze API.")
        if input("   Czy chcesz uruchomić w trybie demo (bez kluczy)? [y/n]: ").lower() == 'y':
            import shutil
            shutil.copy(".env.example", ".env")
            print("✅ Skopiowano .env.example → .env  (tryb SIGNAL_ONLY, Testnet)")
        else:
            sys.exit(0)


def run_bot():
    python = os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV, "bin", "python")
    print("\n🚀 Uruchamiam bota...")
    print("   Dashboard: http://localhost:8000")
    print("   Zatrzymaj: Ctrl+C\n")
    os.makedirs("data", exist_ok=True)
    subprocess.run([python, "backend/api.py"])


if __name__ == "__main__":
    check_python()
    setup_venv()
    check_env()
    run_bot()
