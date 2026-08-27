@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0\.."
cls
echo ============================================================
echo   Gate ANPR - command prompt, already in the right folder
echo   Data folder: %ANPR_DATA%
echo ============================================================
echo.
echo   python run.py reset --all     clear demo data, start clean
echo   python run.py setup           configure cameras (gate + entry/exit)
echo   python run.py check           verify cameras and models
echo   python run.py camtest         live camera view (port 8090)
echo   python run.py start           RUN THE REAL SYSTEM (port 8080)
echo.
cmd /k
