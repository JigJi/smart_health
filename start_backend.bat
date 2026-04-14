@echo off
cd /d D:\0_jig_dev\smart_health\backend
echo Starting smart_health Backend on http://127.0.0.1:8402

:: Kill any python on port 8402
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8402.*LISTENING" 2^>nul') do (
    echo Killing old process %%a on port 8402...
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

:loop
python -m uvicorn app.main:app --host 127.0.0.1 --port 8402
echo.
echo [!] Backend stopped. Restarting in 3 seconds... (Ctrl+C to exit)
timeout /t 3 /nobreak >nul
goto loop
