@echo off
setlocal

REM Download corpus sources listed in corpus/manifest.json into corpus/raw/.
REM Entries already present are skipped, so this is safe to re-run after
REM adding a download_url to the manifest.
REM
REM   fetch.bat                      everything missing
REM   fetch.bat cities_in_evolution  selected ids
REM
REM Then rebuild the index with ingest.bat.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found.  Run run.bat once first to create it and install deps.
    pause
    exit /b 1
)

.venv\Scripts\python.exe fetch_corpus.py %*

if errorlevel 1 (
    echo.
    echo Some sources could not be fetched.  See messages above.
    echo Entries marked UNVERIFIED in the manifest have no download_url
    echo and are skipped by design - see the Corpus section of README.md.
    pause
)

echo.
echo Now run ingest.bat to rebuild the index.
pause
