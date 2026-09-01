@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0\.."
echo ============================================================
echo   Installing the recognition models (ultralytics + PyTorch)
echo   WARNING: several GB of download. Only needed for real use.
echo ============================================================
python -m pip install -r requirements-ai.txt
pause
