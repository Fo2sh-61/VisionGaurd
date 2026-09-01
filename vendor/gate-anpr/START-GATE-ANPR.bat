@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
set PYTHONUTF8=1
title Gate ANPR
cd /d "%~dp0"

cls
echo ==============================================================
echo    GATE ANPR  -  starting
echo ==============================================================
echo.

REM --- python present? ------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
  echo   [X] Python was not found.
  echo       Install it from python.org and tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

REM --- first run? no cameras configured yet ---------------------------
if not exist "config\cameras.yaml" (
  echo   No cameras configured yet - running the setup wizard first.
  echo.
  python run.py setup
  if not exist "config\cameras.yaml" (
    echo.
    echo   Setup was cancelled. Nothing to start.
    pause
    exit /b 1
  )
  cls
)

REM --- free the port if a previous copy is still holding it ------------
REM This is the whole point of a one-click launcher: the user should never
REM have to hunt for a stray window from yesterday.
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
echo   Keep this window open. Closing it stops the system.
echo.
REM Python opens the browser itself once the port answers, so the user
REM never sees ERR_CONNECTION_REFUSED during startup.
python run.py start --open

REM --- only reached if the system stopped ------------------------------
echo.
echo ==============================================================
echo    The system stopped. The message above says why.
echo ==============================================================
pause
