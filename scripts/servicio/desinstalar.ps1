# Desinstalar Autoarranque - Servidor IA AURA
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location -Path $projectRoot

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "             DESINSTALAR AUTOARRANQUE SERVIDOR IA AURA" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Eliminando la configuracion de inicio automatico..."
Write-Host ""

$startupFolder = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup')
$shortcutPath = Join-Path $startupFolder "Servidor_IA_AURA.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host "[OK] Acceso directo eliminado de la carpeta de Inicio de Windows." -ForegroundColor Green
} else {
    Write-Host "[i] No habia acceso directo en la carpeta de Inicio." -ForegroundColor Yellow
}

# Intentar eliminar la tarea programada si existia
try {
    $task = schtasks /Query /TN "ServidorIA_AURA" 2>$null
    if ($LASTEXITCODE -eq 0) {
        schtasks /Delete /TN "ServidorIA_AURA" /F 2>$null | Out-Null
        Write-Host "[OK] Tarea programada de Windows eliminada." -ForegroundColor Green
    }
} catch {}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host "Autoarranque desactivado. El servidor ya no se iniciara solo al encender el PC." -ForegroundColor Green
Write-Host "Si en el futuro deseas reactivarlo, solo ejecuta 'instalar_autoarranque.bat'."
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host ""
