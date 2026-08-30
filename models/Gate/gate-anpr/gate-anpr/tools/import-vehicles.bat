@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0\.."
echo ============================================================
echo   Import vehicles from Excel / CSV
echo ============================================================
echo.
echo Drag the Excel file onto this window, then press Enter.
echo.
set /p FILE=file: 
set FILE=%FILE:"=%
if "%FILE%"=="" goto :end
echo.
echo --- DRY RUN (nothing is saved yet) ---
python tools\import_vehicles.py "%FILE%" --dry-run
echo.
set /p GO=Import for real? type y then Enter: 
if /i not "%GO%"=="y" goto :end
python tools\import_vehicles.py "%FILE%"
:end
pause
