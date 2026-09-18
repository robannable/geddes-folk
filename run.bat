@echo off
setlocal enabledelayedexpansion

REM Geddes-Folk launcher (Windows).
REM First run: creates .venv, installs deps, prompts for API key, offers to
REM build the corpus index.  Subsequent runs: starts Chainlit on
REM http://localhost:8000.

cd /d "%~dp0"

REM --- 1. virtual env -------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create the virtual environment.
        echo Install Python 3.10 or later and make sure "python" is on PATH:
        echo   https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

set "PY=.venv\Scripts\python.exe"

REM --- 2. dependencies ------------------------------------------------------
"%PY%" -c "import chainlit, anthropic, sentence_transformers, faiss" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies. First-time install includes torch and is ~1 GB.
    "%PY%" -m pip install --upgrade pip >nul
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Dependency install failed.  See messages above.
        pause
        exit /b 1
    )
)

REM --- 3. .env --------------------------------------------------------------
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo.
        echo Created .env from .env.example.
        echo Add your ANTHROPIC_API_KEY, save, and close the editor to continue.
        notepad ".env"
    ) else (
        echo.
        echo No .env file found.  Create one containing:
        echo   ANTHROPIC_API_KEY=sk-ant-...
        pause
        exit /b 1
    )
)

REM --- 4. corpus index (optional) ------------------------------------------
if not exist "corpus\index\vectors.faiss" (
    echo.
    echo No corpus index found at corpus\index\vectors.faiss.
    echo Without it, both voices speak from their prompts alone.
    set /p BUILD="Build the index now from corpus\raw? [y/N]: "
    if /i "!BUILD!"=="y" (
        "%PY%" ingest.py
        if errorlevel 1 (
            echo.
            echo Ingest failed.  You can re-run later with:  .venv\Scripts\python.exe ingest.py
            pause
        )
    )
)

REM --- 5. run ---------------------------------------------------------------
echo.
echo Starting Chainlit on http://localhost:8000  (Ctrl+C to stop)
echo.
"%PY%" -m chainlit run app.py
