# Servicio API del Asistente de Perfumería (IA Soberana local)
# Ejecutar desde la raíz del proyecto:
#   powershell -ExecutionPolicy Bypass -File run_api.ps1
$port = if ($env:PERFUMISTA_PORT) { $env:PERFUMISTA_PORT } else { "8000" }
Write-Host "Iniciando API en http://0.0.0.0:$port ..."
& ./hf-locql/Scripts/python.exe -m uvicorn api:app --host 0.0.0.0 --port $port
