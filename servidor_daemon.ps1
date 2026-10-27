# ==============================================================================
# Servidor Demonio de IA y API Pública (AURA / Alta Perfumería)
# Supervisión continua con reinicio automático (Watchdog) y autoarranque
# ==============================================================================
[CmdletBinding()]
param(
    [switch]$Interactive = $false
)

$ErrorActionPreference = "Continue"
$projectRoot = $PSScriptRoot
Set-Location -Path $projectRoot

# Carpetas y archivos de registro
$logsDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

$daemonLog = Join-Path $logsDir "servidor.log"
$apiOutLog = Join-Path $logsDir "api.log"
$apiErrLog = Join-Path $logsDir "api_error.log"
$ngrokLog  = Join-Path $logsDir "ngrok.log"
$pidFile   = Join-Path $projectRoot "data\servidor_daemon.pid"

function Write-DaemonLog {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$timestamp] [$Level] $Message"
    Add-Content -Path $daemonLog -Value $line -Encoding utf8 -ErrorAction SilentlyContinue
    if ($Interactive) {
        switch ($Level) {
            "ERROR"   { Write-Host $line -ForegroundColor Red }
            "WARN"    { Write-Host $line -ForegroundColor Yellow }
            "SUCCESS" { Write-Host $line -ForegroundColor Green }
            default   { Write-Host $line -ForegroundColor Cyan }
        }
    }
}

Write-DaemonLog "=== Iniciando Servicio de Servidor IA AURA ==="

# ------------------------------------------------------------------------------
# 1. Comprobar si ya existe una instancia activa
# ------------------------------------------------------------------------------
if (Test-Path $pidFile) {
    try {
        $oldPid = Get-Content $pidFile -ErrorAction Stop
        if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Write-DaemonLog "Ya existe una instancia de este servicio ejecutándose (PID: $oldPid). Abortando inicio duplicado." "WARN"
            exit 0
        }
    } catch {}
}
$PID | Out-File -FilePath $pidFile -Encoding ascii -Force

# ------------------------------------------------------------------------------
# 2. Configuración y Parámetros del Entorno
# ------------------------------------------------------------------------------
$dominio = if ($env:AURA_DOMINIO) { $env:AURA_DOMINIO } else { "expend-chaplain-degraded.ngrok-free.dev" }
$env:AURA_MODELO = if ($env:AURA_MODELO) { $env:AURA_MODELO } else { "aura_v3b" }
$port = if ($env:PERFUMISTA_PORT) { $env:PERFUMISTA_PORT } else { "8000" }

$pythonExe = Join-Path $projectRoot "hf-locql\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-DaemonLog "ERROR CRÍTICO: No se encontró el entorno Python en '$pythonExe'." "ERROR"
    exit 1
}

# Localizar ejecutable de ngrok
$ngrokExe = (Get-Command "ngrok.exe" -ErrorAction SilentlyContinue).Source
if (-not $ngrokExe) {
    $candidates = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe",
        "$env:LOCALAPPDATA\ngrok\ngrok.exe",
        "$projectRoot\ngrok.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) { $ngrokExe = $cand; break }
    }
}

if (-not $ngrokExe) {
    Write-DaemonLog "ADVERTENCIA: No se encontró ngrok.exe. La API funcionará en red local pero sin túnel público." "WARN"
} else {
    Write-DaemonLog "ngrok detectado en: $ngrokExe"
}

# ------------------------------------------------------------------------------
# 3. Esperar conexión a Internet (fundamental al reiniciar el equipo)
# ------------------------------------------------------------------------------
if ($ngrokExe) {
    Write-DaemonLog "Comprobando conexión a internet para el túnel..."
    $netOk = $false
    for ($attempt = 1; $attempt -le 25; $attempt++) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $connect = $tcp.BeginConnect("1.1.1.1", 53, $null, $null)
            $wait = $connect.AsyncWaitHandle.WaitOne(2000, $false)
            if ($wait -and $tcp.Connected) {
                $tcp.EndConnect($connect)
                $tcp.Close()
                $netOk = $true
                break
            }
            $tcp.Close()
        } catch {}
        Write-DaemonLog "Esperando conexión de red/Wi-Fi (intento $attempt/25)..."
        Start-Sleep -Seconds 2
    }
    if ($netOk) {
        Write-DaemonLog "Conexión a internet verificada con éxito." "SUCCESS"
    } else {
        Write-DaemonLog "No se detectó internet tras 50s. Se continuará iniciando localmente." "WARN"
    }
}

# ------------------------------------------------------------------------------
# 4. Limpiar posibles procesos zombies en el puerto 8000
# ------------------------------------------------------------------------------
try {
    $existingConns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($existingConns) {
        Write-DaemonLog "Puerto $port ocupado previamente. Liberando proceso..." "WARN"
        foreach ($conn in $existingConns) {
            if ($conn.OwningProcess -and $conn.OwningProcess -ne $PID -and $conn.OwningProcess -gt 0) {
                Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
        Start-Sleep -Seconds 2
    }
} catch {}

# Limpiar instancias huérfanas de ngrok
Get-Process -Name "ngrok" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# ------------------------------------------------------------------------------
# 5. Funciones de inicio de servicios
# ------------------------------------------------------------------------------
function Start-ApiProcess {
    Write-DaemonLog "Iniciando API local con uvicorn (Modelo: $env:AURA_MODELO, Puerto: $port)..."
    $env:PYTHONUNBUFFERED = "1"
    $proc = Start-Process -FilePath $pythonExe `
        -ArgumentList "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", $port `
        -RedirectStandardOutput $apiOutLog `
        -RedirectStandardError $apiErrLog `
        -WorkingDirectory $projectRoot `
        -NoNewWindow -PassThru
    return $proc
}

function Start-NgrokProcess {
    if (-not $ngrokExe) { return $null }
    Write-DaemonLog "Iniciando túnel ngrok hacia https://$dominio ..."
    $proc = Start-Process -FilePath $ngrokExe `
        -ArgumentList "http", $port, "--url=https://$dominio", "--log=$ngrokLog", "--log-format=logfmt" `
        -WorkingDirectory $projectRoot `
        -NoNewWindow -PassThru
    return $proc
}

# ------------------------------------------------------------------------------
# 6. Lanzamiento inicial
# ------------------------------------------------------------------------------
$apiProc = Start-ApiProcess

# Esperar que la API esté lista (endpoint /health)
Write-DaemonLog "Esperando que el modelo cargue en memoria (puede tardar de 15 a 45 segundos)..."
$apiReady = $false
$maxRetries = 60 # 60 * 2s = 120s
for ($i = 1; $i -le $maxRetries; $i++) {
    Start-Sleep -Seconds 2
    if ($apiProc.HasExited) {
        Write-DaemonLog "ERROR: El proceso de la API se detuvo antes de responder. Revisa '$apiErrLog'." "ERROR"
        break
    }
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $apiReady = $true
            break
        }
    } catch {}
}

if ($apiReady) {
    Write-DaemonLog "API local respondiendo correctamente en http://127.0.0.1:$port/health" "SUCCESS"
} else {
    Write-DaemonLog "ADVERTENCIA: La API está tardando en responder o hubo error, supervisando proceso..." "WARN"
}

# Iniciar ngrok
$ngrokProc = Start-NgrokProcess
if ($ngrokProc) {
    Write-DaemonLog "Túnel ngrok en ejecución. Dominio público: https://$dominio" "SUCCESS"
}

Write-DaemonLog "Servidor listo y operativo. Entrando en bucle de supervisión continua..." "SUCCESS"

# ------------------------------------------------------------------------------
# 7. Limpieza al salir
# ------------------------------------------------------------------------------
$cleanup = {
    Write-DaemonLog "Deteniendo procesos del servidor ordenadamente..." "WARN"
    if ($ngrokProc -and -not $ngrokProc.HasExited) {
        Stop-Process -Id $ngrokProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($apiProc -and -not $apiProc.HasExited) {
        Stop-Process -Id $apiProc.Id -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $pidFile) {
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    Write-DaemonLog "Servicio detenido."
}

# ------------------------------------------------------------------------------
# 8. Bucle Watchdog (Supervisión continua)
# ------------------------------------------------------------------------------
try {
    while ($true) {
        Start-Sleep -Seconds 10

        # Supervisar API
        if ($apiProc.HasExited) {
            Write-DaemonLog "ALERTA: El proceso de la API (PID $($apiProc.Id)) se cerró inesperadamente. Reiniciando en 5s..." "ERROR"
            Start-Sleep -Seconds 5
            $apiProc = Start-ApiProcess
        }

        # Supervisar ngrok
        if ($ngrokExe -and ($null -eq $ngrokProc -or $ngrokProc.HasExited)) {
            Write-DaemonLog "ALERTA: El proceso de ngrok se cerró. Reiniciando túnel..." "WARN"
            Start-Sleep -Seconds 3
            $ngrokProc = Start-NgrokProcess
        }
    }
} finally {
    & $cleanup
}
