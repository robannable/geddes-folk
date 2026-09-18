#!/usr/bin/env bash
# Geddes-Folk launcher (Linux / macOS).
# First run: creates .venv, installs deps, prompts for API key, offers to
# build the corpus index.  Subsequent runs: starts Chainlit on
# http://localhost:8000.

set -e
cd "$(dirname "$0")"

# --- 1. virtual env --------------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
    echo "Creating virtual environment in .venv ..."
    if ! python3 -m venv .venv; then
        echo
        echo "Could not create the virtual environment."
        echo "Install Python 3.10 or later (python3 + python3-venv) and try again."
        exit 1
    fi
fi

PY=".venv/bin/python"

# --- 2. dependencies -------------------------------------------------------
if ! "$PY" -c "import chainlit, anthropic, sentence_transformers, faiss" >/dev/null 2>&1; then
    echo "Installing dependencies. First-time install includes torch and is ~1 GB."
    "$PY" -m pip install --upgrade pip >/dev/null
    if ! "$PY" -m pip install -r requirements.txt; then
        echo
        echo "Dependency install failed.  See messages above."
        exit 1
    fi
fi

# --- 3. .env ---------------------------------------------------------------
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo
        echo "Created .env from .env.example."
        echo "Add your ANTHROPIC_API_KEY to .env, save, then re-run this script."
        EDITOR="${EDITOR:-${VISUAL:-}}"
        if [ -n "$EDITOR" ]; then
            "$EDITOR" .env
        else
            echo "(Set \$EDITOR to open it automatically next time.)"
        fi
        exit 0
    else
        echo
        echo "No .env file found.  Create one containing:"
        echo "  ANTHROPIC_API_KEY=sk-ant-..."
        exit 1
    fi
fi

# --- 4. corpus index (optional) -------------------------------------------
if [ ! -f "corpus/index/vectors.faiss" ]; then
    echo
    echo "No corpus index found at corpus/index/vectors.faiss."
    echo "Without it, both voices speak from their prompts alone."
    read -r -p "Build the index now from corpus/raw? [y/N]: " BUILD
    case "$BUILD" in
        [Yy]*)
            if ! "$PY" ingest.py; then
                echo
                echo "Ingest failed.  You can re-run later with:  .venv/bin/python ingest.py"
            fi
            ;;
    esac
fi

# --- 5. run ----------------------------------------------------------------
echo
echo "Starting Chainlit on http://localhost:8000  (Ctrl+C to stop)"
echo
exec "$PY" -m chainlit run app.py
