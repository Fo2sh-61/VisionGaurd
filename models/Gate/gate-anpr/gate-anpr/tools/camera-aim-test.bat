@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0\.."
echo ============================================================
echo   CAMERA TEST - see what the system sees
echo ============================================================
echo.
echo Laptop webcam = 0.  IP camera = rtsp://user:pass@ip:554/...
echo Just press Enter to use the laptop webcam.
echo.
set /p SRC=camera source [0]: 
if "%SRC%"=="" set SRC=0
echo.
echo Opening http://localhost:8090 - keep this window open.
start "" http://localhost:8090
python run.py camtest --source "%SRC%" --port 8090
pause
