"""Single source of truth for models, display labels, and cost rates.

sharp-folk hardcoded "(Opus)" into its UI steps and transcript while the
model config said Sonnet, and its price table was keyed on a model no
call ever used — so every cost figure it reported read zero. Everything
that names a model or prices a call reads from here instead.
"""

# --- Models -----------------------------------------------------------
#
# Both voices run on Sonnet 5: current generation, and cheaper per token
# than the Sonnet 4.6 sharp-folk pins ($2/$10 against $3/$15 per MTok).
# The classifier is a cheap three-way string classification, so Haiku.
#
# Haiku 4.5 rejects `output_config.effort` — see EFFORT_BY_MODE below and
# the classifier call in app.py, neither of which sends it.

VOICE_MODEL = "claude-sonnet-5"
CLASSIFIER_MODEL = "claude-haiku-4-5"

MODEL_LABELS = {
    "claude-opus-5": "Opus 5",
    "claude-sonnet-5": "Sonnet 5",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-haiku-4-5": "Haiku 4.5",
}


def label(model: str) -> str:
    """Short display name for a model id, for logs and UI panels."""
    return MODEL_LABELS.get(model, model)


# --- Cost rates -------------------------------------------------------
#
# USD per million tokens. Approximate and drifting — the Anthropic
# billing console is the source of truth. Cache reads run ~0.1x base
# input; cache writes ~1.25x for the default 5-minute TTL.
#
# cost_cents() returns 0.0 for a model missing from this table, which is
# how sharp-folk's cost tracking died silently. Add a row before you
# point VOICE_MODEL at anything new.

PRICES_USD_PER_MTOK = {
    "claude-opus-5":    {"in":  5.00, "out": 25.00, "cache_read": 0.50, "cache_write":  6.25},
    "claude-sonnet-5":  {"in":  2.00, "out": 10.00, "cache_read": 0.20, "cache_write":  2.50},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00, "cache_read": 0.30, "cache_write":  3.75},
    "claude-haiku-4-5": {"in":  1.00, "out":  5.00, "cache_read": 0.10, "cache_write":  1.25},
}


# --- Voices -----------------------------------------------------------

GEDDES = "Patrick Geddes"
LIBRARIAN = "The Librarian"

# --- Retrieval --------------------------------------------------------

RETRIEVE_K = 5

# Multipliers applied to a chunk's similarity score by source directory,
# carried over from Geddes-Ghost's CONTEXT_WEIGHTS. A student's own
# uploaded work outranks the general corpus when they ask about it.
CONTEXT_WEIGHTS = {
    "student": 1.5,
    "project": 1.3,
    "history": 1.2,
    "general": 1.0,
}
