# Detener Servidor IA AURA
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location -Path $projectRoot

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "                      DETENER SERVIDOR IA AURA" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Deteniendo procesos del servidor (API uvicorn, Python y tunel ngrok)..."
Write-Host ""

$pidFile = Join-Path $projectRoot "data\servidor_daemon.pid"

# 1. Detener Demonio
if (Test-Path $pidFile) {
    try {
        $daemonPid = Get-Content $pidFile -ErrorAction Stop
        if ($daemonPid) {
            Stop-Process -Id $daemonPid -Force -ErrorAction SilentlyContinue
            Write-Host "[OK] Proceso supervisor demonio (PID: $daemonPid) detenido." -ForegroundColor Green
        }
    } catch {}
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# 2. Detener uvicorn / api:app
try {
    Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match "uvicorn" -and $_.CommandLine -match "api:app"
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Proceso API uvicorn (PID: $($_.ProcessId)) detenido." -ForegroundColor Green
    }
} catch {}

# 3. Detener ngrok
try {
    Get-Process -Name "ngrok" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Proceso ngrok (PID: $($_.Id)) detenido." -ForegroundColor Green
    }
} catch {}

# 4. Verificar puerto 8000
Start-Sleep -Seconds 1
$port = if ($env:PERFUMISTA_PORT) { $env:PERFUMISTA_PORT } else { "8000" }
$conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if (-not $conn) {
    Write-Host "[OK] Puerto $port liberado con exito. GPU y memoria VRAM disponibles." -ForegroundColor Green
} else {
    Write-Host "[!] Advertencia: El puerto $port aun parece ocupado." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Operacion completada con exito." -ForegroundColor Cyan
