@echo off
chcp 65001 >nul
title Estado del Servidor IA AURA
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\servicio\estado.ps1"

echo.
pause
