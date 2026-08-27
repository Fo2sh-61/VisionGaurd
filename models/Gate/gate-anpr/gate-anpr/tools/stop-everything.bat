@echo off
chcp 65001 >nul
echo Freeing the ports used by Gate ANPR (8080 and 8090)...
for %%p in (8080 8090) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%p ^| findstr LISTENING') do (
     echo   stopping PID %%a on port %%p
     taskkill /F /PID %%a >nul 2>&1
  )
)
echo Done. You can start the system again now.
timeout /t 6 >nul
