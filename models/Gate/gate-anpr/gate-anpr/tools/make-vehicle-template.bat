@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0\.."
python tools\import_vehicles.py --template vehicles_template.xlsx
echo.
echo Template created: vehicles_template.xlsx (in the project folder)
echo Fill it in, then run import-vehicles.bat
pause
