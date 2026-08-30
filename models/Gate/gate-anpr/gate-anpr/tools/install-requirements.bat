@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0\.."
echo ============================================================
echo   Installing the core system (small, ~40 MB)
echo ============================================================
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo *** INSTALL FAILED - read the message above
  pause
  exit /b 1
)
echo.
echo Verifying with the test suite...
python tests\test_pipeline.py
echo.
echo Done. Next step: run  2-demo.bat
echo (The AI models are a separate, much bigger install - see 6-install-ai.bat)
pause
