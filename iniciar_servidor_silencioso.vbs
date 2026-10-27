' ==============================================================================
' Lanzador Silencioso en Segundo Plano para el Servidor de IA AURA
' Ejecuta el demonio sin abrir ninguna ventana de consola negra visible.
' ==============================================================================
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = scriptDir

cmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & scriptDir & "\servidor_daemon.ps1"""
WshShell.Run cmd, 0, False
