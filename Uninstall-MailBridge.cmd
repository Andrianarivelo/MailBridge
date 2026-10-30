@echo off
rem MailBridge : desinstallation (tache planifiee + icones). Reglages, journaux et identifiants conserves.
title Desinstallation de MailBridge
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:MAILBRIDGE_SRC='%~dp0'; $env:MAILBRIDGE_REMOVE='1'; iex ([IO.File]::ReadAllText('%~dp0install.ps1', [Text.Encoding]::UTF8))"
echo.
pause
