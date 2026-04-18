@echo off
cd /d D:\0_jig_dev\smart_health\frontend
echo Starting smart_health Frontend on http://0.0.0.0:3400

:: Kill any node on port 3400
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3400.*LISTENING" 2^>nul') do (
    echo Killing old process %%a on port 3400...
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: BACKEND_URL is also defined in .env.local — set here as defense-in-depth
set BACKEND_URL=http://127.0.0.1:8401

:loop
call npx next start -H 0.0.0.0 -p 3400
echo.
echo [!] Frontend stopped. Restarting in 3 seconds... (Ctrl+C to exit)
timeout /t 3 /nobreak >nul
goto loop
