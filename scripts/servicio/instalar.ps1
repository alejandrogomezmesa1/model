# Instalador de Autoarranque - Servidor IA AURA
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location -Path $projectRoot

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "        INSTALADOR DE AUTOARRANQUE PARA SERVIDOR IA AURA" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configurando el inicio automatico en Windows..."
Write-Host ""

$vbsPath = Join-Path $projectRoot "iniciar_servidor_silencioso.vbs"
$startupFolder = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup')
$shortcutPath = Join-Path $startupFolder "Servidor_IA_AURA.lnk"

if (-not (Test-Path $vbsPath)) {
    Write-Host "[ERROR] No se encontro '$vbsPath'." -ForegroundColor Red
    exit 1
}

try {
    # 1. Crear acceso directo en la carpeta de Inicio de Windows (Siempre funciona sin requerir permisos de admin)
    $wsh = New-Object -ComObject WScript.Shell
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "wscript.exe"
    $shortcut.Arguments = "`"$vbsPath`""
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = "Servidor Local y API Publica de IA AURA"
    $shortcut.Save()

    Write-Host "[OK] Acceso directo registrado en la carpeta de Inicio de Windows:" -ForegroundColor Green
    Write-Host "     $shortcutPath" -ForegroundColor Gray

    # 2. Intentar registrar tarea programada en Windows (si cuenta con permisos de administrador)
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        $schCmd = "schtasks.exe /Create /TN `"ServidorIA_AURA`" /TR `"wscript.exe \`"$vbsPath\`"`" /SC ONLOGON /F 2>`$null"
        Invoke-Expression $schCmd | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Tarea programada registrada en el Programador de Tareas de Windows." -ForegroundColor Green
        }
    }
} catch {
    Write-Host "[ERROR] Error al configurar el autoarranque: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host "                     CONFIGURACION COMPLETADA" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host "  1. Cada vez que inicies sesion o reinicies el PC, el servidor arrancara"
Write-Host "     automaticamente en segundo plano sin mostrar ventanas molestas."
Write-Host "  2. El modelo cargara en la GPU local y el tunel ngrok se activara solo."
Write-Host "  3. Herramientas disponibles en la carpeta principal:"
Write-Host "     - estado_servidor.bat   : Consulta si la API y el tunel estan activos."
Write-Host "     - detener_servidor.bat  : Detiene el servidor para liberar GPU/memoria."
Write-Host "     - iniciar_servidor.bat  : Inicia el servidor mostrando la consola en vivo."
Write-Host "     - desinstalar_autoarranque.bat : Desactiva el inicio automatico."
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host ""
