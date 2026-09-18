@echo off
setlocal

REM Render logs\*.jsonl as logs\dashboard.html and open it.
REM
REM   dashboard.bat            all logs
REM   dashboard.bat --days 14  last fortnight

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found.  Run run.bat once first to create it and install deps.
    pause
    exit /b 1
)

.venv\Scripts\python.exe dashboard.py %*

if errorlevel 1 (
    echo.
    echo dashboard.py exited with an error.  See messages above.
    pause
    exit /b 1
)

start "" "logs\dashboard.html"
