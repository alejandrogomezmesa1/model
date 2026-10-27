@echo off
chcp 65001 >nul
title Desinstalar Autoarranque Servidor IA AURA
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\servicio\desinstalar.ps1"

echo.
pause
