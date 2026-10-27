@echo off
chcp 65001 >nul
title Instalador de Autoarranque - Servidor IA AURA
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\servicio\instalar.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocurrió un problema durante la instalación.
    pause
    exit /b %ERRORLEVEL%
)

set /p RESP="¿Deseas iniciar el servidor ahora mismo en segundo plano? (S/N): "
if /i "%RESP%"=="S" (
    echo.
    echo Iniciando servidor en segundo plano...
    start "" wscript.exe "%~dp0iniciar_servidor_silencioso.vbs"
    timeout /t 3 >nul
    echo.
    echo El servidor está arrancando. Puedes verificar su estado en cualquier
    echo momento haciendo doble clic en 'estado_servidor.bat'.
)

echo.
pause
