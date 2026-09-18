"""Per-turn JSONL log and rough cost estimator.

Writes one record per conversational turn to logs/YYYY-MM-DD.jsonl:
user name and message, retrieved chunks (metadata only, not full text),
each voice's reply, classifier verdict, cognitive mode, and token usage
for every API call. Re-renders logs/YYYY-MM-DD.md from the JSONL after
each append so the markdown transcript stays in sync.

A short cost line also prints to stdout each turn. Rates live in
config.PRICES_USD_PER_MTOK; the Anthropic billing console is the source
of truth.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import transcript
from config import PRICES_USD_PER_MTOK

LOGS = Path(__file__).parent / "logs"


def usage_to_dict(usage) -> dict:
    return {
        "in":          getattr(usage, "input_tokens", 0) or 0,
        "out":         getattr(usage, "output_tokens", 0) or 0,
        "cache_read":  getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }


def cost_cents(model: str, u: dict | None) -> float:
    """Approximate cost in cents for one call.

    Returns 0.0 for a model absent from the price table — which is how
    sharp-folk's cost tracking died silently when its VOICE_MODEL moved
    off the only key in the table. If a turn reports 0.0 for a call that
    definitely ran, check config.PRICES_USD_PER_MTOK has that model.
    """
    if not u:
        return 0.0
    p = PRICES_USD_PER_MTOK.get(model)
    if not p:
        return 0.0
    usd = (
        u["in"]            * p["in"]
        + u["out"]         * p["out"]
        + u["cache_read"]  * p["cache_read"]
        + u["cache_write"] * p["cache_write"]
    ) / 1_000_000
    return usd * 100


def chunk_meta(c: dict) -> dict:
    """Chunk metadata for the log — text omitted to keep logs scannable."""
    return {
        "id": c.get("id"),
        "source_title": c.get("source_title"),
        "section_title": c.get("section_title"),
        "voice": c.get("voice"),
        "weight_class": c.get("weight_class"),
        "score": c.get("score"),
    }


def log_turn(record: dict) -> None:
    LOGS.mkdir(exist_ok=True)
    path = LOGS / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    transcript.write()
