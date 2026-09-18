@echo off
setlocal

REM Build the corpus index using the project's virtual environment.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found.  Run run.bat once first to create it and install deps.
    pause
    exit /b 1
)

.venv\Scripts\python.exe ingest.py %*

if errorlevel 1 (
    echo.
    echo ingest.py exited with an error.  See messages above.
    pause
)
