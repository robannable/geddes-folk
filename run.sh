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

# --- 4. corpus -------------------------------------------------------------
# Fetch before ingest.  A fresh clone carries only the two teaching
# documents; everything else has to be downloaded first, and ingesting
# without fetching silently builds an index of almost nothing.
if [ ! -f "corpus/index/vectors.faiss" ]; then
    echo
    echo "No corpus index found at corpus/index/vectors.faiss."
    echo "Without it, both voices speak from their prompts alone."
    echo
    read -r -p "Download the corpus and build the index now? [y/N]: " BUILD
    case "$BUILD" in
        [Yy]*)
            echo
            echo "Downloading sources listed in corpus/manifest.json ..."
            # Non-zero exit means some entries failed; the rest still
            # downloaded, so carry on to ingest what did arrive.
            "$PY" fetch_corpus.py || echo "Some sources could not be fetched (see above)."

            echo
            if ! "$PY" ingest.py; then
                echo
                echo "Ingest failed.  Re-run later with:  .venv/bin/python ingest.py"
            fi

            echo
            echo "Note: manifest entries marked UNVERIFIED have no download_url"
            echo "and were skipped.  Geddes's own books are among them - see the"
            echo "Corpus section of README.md."
            ;;
    esac
fi

# --- 5. run ----------------------------------------------------------------
echo
echo "Starting Chainlit on http://localhost:8000  (Ctrl+C to stop)"
echo
exec "$PY" -m chainlit run app.py
