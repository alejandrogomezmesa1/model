# Publica la API de AURA en internet con el dominio fijo y gratis de ngrok.
# Ejecutar desde la raíz del proyecto:
#   powershell -ExecutionPolicy Bypass -File run_publico.ps1
# Requiere haber guardado el token una vez: ngrok config add-authtoken <TOKEN>
$dominio = if ($env:AURA_DOMINIO) { $env:AURA_DOMINIO } else { "expend-chaplain-degraded.ngrok-free.dev" }
$env:AURA_MODELO = if ($env:AURA_MODELO) { $env:AURA_MODELO } else { "aura_v2" }

Write-Host "Iniciando API local (modelo $env:AURA_MODELO)..."
$api = Start-Process -FilePath "./hf-locql/Scripts/python.exe" `
    -ArgumentList "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000" `
    -NoNewWindow -PassThru

# Esperar a que la API responda antes de abrir el túnel
do {
    Start-Sleep -Seconds 3
    try { $ok = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/health" -TimeoutSec 5).StatusCode -eq 200 } catch { $ok = $false }
} until ($ok -or $api.HasExited)
if ($api.HasExited) { Write-Host "La API no arrancó."; exit 1 }

Write-Host "API pública en https://$dominio  (Ctrl+C para detener)"
try {
    ngrok http 127.0.0.1:8000 --url="https://$dominio"
} finally {
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
}
