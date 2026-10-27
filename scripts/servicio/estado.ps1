# Estado del Servidor IA AURA
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location -Path $projectRoot

$port = if ($env:PERFUMISTA_PORT) { $env:PERFUMISTA_PORT } else { "8000" }
$dominio = if ($env:AURA_DOMINIO) { $env:AURA_DOMINIO } else { "expend-chaplain-degraded.ngrok-free.dev" }

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "                     ESTADO DEL SERVIDOR IA AURA" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Comprobar Demonio / Supervisor
$pidFile = Join-Path $projectRoot "data\servidor_daemon.pid"
if (Test-Path $pidFile) {
    $dPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($dPid -and (Get-Process -Id $dPid -ErrorAction SilentlyContinue)) {
        Write-Host "[Supervisor Demonio] : ACTIVO [OK] (PID $dPid)" -ForegroundColor Green
    } else {
        Write-Host "[Supervisor Demonio] : INACTIVO (archivo PID obsoleto)" -ForegroundColor Yellow
    }
} else {
    Write-Host "[Supervisor Demonio] : INACTIVO" -ForegroundColor Yellow
}

# 2. Comprobar API Local
try {
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3 -ErrorAction Stop
    Write-Host "[API Local :$port]     : ONLINE [OK]" -ForegroundColor Green
    Write-Host "  - Estado salud     : $($res.status)"
    Write-Host "  - Modelo cargado   : $($res.model)"
    Write-Host "  - Dispositivo      : $($res.device)"
    Write-Host "  - API Key activa   : $($res.api_key_set)"
} catch {
    Write-Host "[API Local :$port]     : OFFLINE [X] (no responde en http://127.0.0.1:$port/health)" -ForegroundColor Red
}

# 3. Comprobar ngrok
$ngrokProc = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
if ($ngrokProc) {
    Write-Host "[Tunel ngrok]        : ACTIVO [OK] (PID $($ngrokProc.Id))" -ForegroundColor Green
    Write-Host "  - URL publica      : https://$dominio" -ForegroundColor Cyan
} else {
    Write-Host "[Tunel ngrok]        : INACTIVO [X]" -ForegroundColor Red
}

# 4. Comprobar Autoarranque
$startupLnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Servidor_IA_AURA.lnk"
if (Test-Path $startupLnk) {
    Write-Host "[Autoarranque PC]    : HABILITADO [OK] (inicia solo al encender el equipo)" -ForegroundColor Green
} else {
    Write-Host "[Autoarranque PC]    : NO HABILITADO (ejecuta instalar_autoarranque.bat)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "------------------ Ultimos registros (logs/servidor.log) ------------------" -ForegroundColor Gray
$logPath = Join-Path $projectRoot "logs\servidor.log"
if (Test-Path $logPath) {
    Get-Content $logPath -Tail 8 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
} else {
    Write-Host "  (Aun no hay archivo de registro servidor.log)" -ForegroundColor Gray
}
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""
