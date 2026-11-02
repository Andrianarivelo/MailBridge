@echo off
rem GmailBridge : installation en un clic.
rem Dans un dossier telecharge : installe sur place. Seul : telecharge la derniere version.
rem (install.ps1 est lu en UTF-8 pour que les accents s'affichent correctement)
title Installation de GmailBridge
if exist "%~dp0install.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:MAILBRIDGE_SRC='%~dp0'; iex ([IO.File]::ReadAllText('%~dp0install.ps1', [Text.Encoding]::UTF8))"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (irm 'https://raw.githubusercontent.com/Andrianarivelo/MailBridge/main/install.ps1')"
)
echo.
pause
