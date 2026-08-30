@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
set PYTHONUTF8=1
title Gate ANPR
cd /d "%~dp0gate-anpr\gate-anpr"

cls
echo ==============================================================
echo    GATE ANPR
echo ==============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo   [X] Python was not found. Install from python.org
  echo       and tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

if not exist "config\cameras.yaml" (
  echo   No cameras configured yet - running setup first.
  echo.
  python run.py setup
  if not exist "config\cameras.yaml" (
    echo.
    echo   Setup cancelled. Nothing to start.
    pause
    exit /b 1
  )
  cls
)

set FREED=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8080 ^| findstr LISTENING') do (
  taskkill /F /PID %%a >nul 2>&1
  set FREED=1
)
if "!FREED!"=="1" (
  echo   Stopped a previous copy that was still running.
  timeout /t 2 >nul
)

echo   Dashboard:  http://localhost:8080
echo   The browser opens by itself once the system is ready.
echo   First start can take up to a minute while the OCR models load.
echo   Keep this window open. Closing it stops the system.
echo.
python run.py start --open

echo.
echo ==============================================================
echo    The system stopped. The message above says why.
echo    Full log: %%LOCALAPPDATA%%\GateANPR\data\anpr.log
echo ==============================================================
pause
