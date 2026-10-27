@echo off
chcp 65001 >nul
title Servidor IA AURA - Consola Activa
cd /d "%~dp0"

echo ==============================================================================
echo           🌸 SERVIDOR IA LOCAL Y API PÚBLICA (AURA) 🌸
echo ==============================================================================
echo.
echo Iniciando servidor en modo interactivo...
echo Presiona Ctrl+C en esta ventana cuando desees detener el servidor.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0servidor_daemon.ps1" -Interactive

echo.
echo El servidor se ha detenido.
pause
