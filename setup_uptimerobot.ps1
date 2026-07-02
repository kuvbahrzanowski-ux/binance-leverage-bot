#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Automatyczna rejestracja monitora UptimeRobot dla backendu bota.
  
.USAGE
  1. Wejdź na https://uptimerobot.com → My Settings → API Settings → Main API Key
  2. Skopiuj klucz API
  3. Uruchom: .\setup_uptimerobot.ps1 -ApiKey "twoj-klucz"
#>

param(
  [Parameter(Mandatory=$false)]
  [string]$ApiKey = ""
)

$BACKEND_URL = "https://binance-leverage-bot-backend.onrender.com/health"
$MONITOR_NAME = "Binance Leverage Bot - Backend 24/7"

if (-not $ApiKey) {
  $ApiKey = Read-Host "Wklej swój UptimeRobot API Key"
}

Write-Host ""
Write-Host "🔗 Rejestruję monitor UptimeRobot..." -ForegroundColor Cyan
Write-Host "   URL: $BACKEND_URL"
Write-Host "   Interval: co 5 minut"
Write-Host ""

$body = @{
  api_key          = $ApiKey
  format           = "json"
  type             = 2           # HTTP(s)
  url              = $BACKEND_URL
  friendly_name    = $MONITOR_NAME
  interval         = 300         # 5 minut (w sekundach)
  alert_contacts   = ""
}

try {
  $response = Invoke-RestMethod `
    -Uri "https://api.uptimerobot.com/v2/newMonitor" `
    -Method POST `
    -Body $body `
    -ContentType "application/x-www-form-urlencoded"

  if ($response.stat -eq "ok") {
    Write-Host "✅ Monitor zarejestrowany pomyślnie!" -ForegroundColor Green
    Write-Host "   ID Monitora: $($response.monitor.id)"
    Write-Host ""
    Write-Host "📊 Sprawdź status na: https://uptimerobot.com/dashboard" -ForegroundColor Yellow
  } else {
    Write-Host "❌ Błąd: $($response.error.message)" -ForegroundColor Red
  }
} catch {
  Write-Host "❌ Błąd połączenia: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Status systemu ===" -ForegroundColor Cyan

# Sprawdź backend
Write-Host -NoNewline "Backend /health: "
try {
  $h = Invoke-RestMethod -Uri "https://binance-leverage-bot-backend.onrender.com/health" -TimeoutSec 15
  Write-Host "✅ Online - Mode: $($h.mode)" -ForegroundColor Green
} catch {
  try {
    Invoke-RestMethod -Uri "https://binance-leverage-bot-backend.onrender.com/api/stats" -TimeoutSec 10 | Out-Null
    Write-Host "✅ Online (stary kod - deploy w toku)" -ForegroundColor Yellow
  } catch {
    Write-Host "❌ Offline" -ForegroundColor Red
  }
}

# Sprawdź frontend
Write-Host -NoNewline "Frontend Vercel: "
try {
  Invoke-WebRequest -Uri "https://frontend-tawny-beta-63.vercel.app" -TimeoutSec 10 -UseBasicParsing | Out-Null
  Write-Host "✅ Online" -ForegroundColor Green
} catch {
  Write-Host "❌ Offline" -ForegroundColor Red
}

Write-Host ""
Write-Host "🌐 Frontend: https://frontend-tawny-beta-63.vercel.app" -ForegroundColor Cyan
