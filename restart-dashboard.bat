@echo off
REM Restart Kimi Code Dashboard (invoked by elevated scheduled task)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING"') do taskkill /F /PID %%a
timeout /t 2 /nobreak >nul
call "C:\Users\Administrator\.kimi-code\bin\kimi-dashboard.bat" 1
