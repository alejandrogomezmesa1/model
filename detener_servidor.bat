@echo off
chcp 65001 >nul
title Detener Servidor IA AURA
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\servicio\detener.ps1"

echo.
pause
