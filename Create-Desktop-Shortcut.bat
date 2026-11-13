@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create-Desktop-Shortcut.ps1"
if errorlevel 1 (
  echo Could not create the shortcut.
  pause
  exit /b 1
)
echo You can start ServiceDeck from the ServiceDeck icon on the desktop.
pause
exit /b 0
