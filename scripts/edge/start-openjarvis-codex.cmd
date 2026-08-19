@echo off
start "" powershell.exe -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0Start-OpenJarvisCodexDesktop.ps1" %*
