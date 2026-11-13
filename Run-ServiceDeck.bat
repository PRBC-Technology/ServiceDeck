@echo off
setlocal
cd /d "%~dp0"
title ServiceDeck

echo ServiceDeck
echo Leave this window open during the service. Close it, or press Ctrl+C, to stop.
echo.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python 3 was not found.
  echo Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating a virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)

echo Checking requirements...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

echo.
".venv\Scripts\python.exe" -m servicedeck --open-browser
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo ServiceDeck stopped because of an error.
pause
exit /b 1
