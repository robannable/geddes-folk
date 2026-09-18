"""Render a daily JSONL log to a legible Markdown transcript.

CLI:
    python transcript.py             # today (UTC)
    python transcript.py 2026-09-18  # specific date

API (called from `session_log.log_turn`):
    transcript.write()               # refresh today's logs/<date>.md

Output puts the conversation first — user, Geddes, Librarian as plain
markdown — and tucks retrieved-chunk metadata, classifier verdict, and
token/cost breakdowns inside `<details><summary>` blocks. The reply text
in the JSONL is the full reply; the markdown is a verbatim transcript,
not a summary. The JSONL remains the source of truth.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import CLASSIFIER_MODEL, GEDDES, LIBRARIAN, VOICE_MODEL, label

LOGS = Path(__file__).parent / "logs"


def _quote(text: str) -> str:
    """Prefix each line with '> ' for a markdown blockquote."""
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _fmt_chunks(chunks: list[dict]) -> str:
    if not chunks:
        return "_(no chunks retrieved — index empty or not built)_"
    out = []
    for c in chunks:
        title = c.get("source_title") or "?"
        year = c.get("source_year")
        section = c.get("section_title")
        cid = c.get("id") or "?"
        line = f"- *{title}*"
        if year:
            line += f" ({year})"
        if section:
            line += f" — “{section}”"
        if c.get("score") is not None:
            line += f"  score {c['score']}"
        if c.get("weight_class") and c["weight_class"] != "general":
            line += f"  [{c['weight_class']}]"
        line += f"  `{cid}`"
        out.append(line)
    return "\n".join(out)


def _fmt_tokens(turn: dict) -> str:
    geddes = turn.get("geddes") or {}
    classifier = turn.get("classifier")
    librarian = turn.get("librarian")
    cost = turn.get("cost_cents") or {}
    voice = label(VOICE_MODEL)
    clf = label(CLASSIFIER_MODEL)
    lines: list[str] = []
    if geddes.get("usage"):
        u = geddes["usage"]
        lines.append(
            f"- Geddes ({voice}): {u['in']} in / {u['out']} out"
            f"  ≈{cost.get('geddes', 0):.3f}¢"
        )
    if classifier:
        u = classifier["usage"]
        lines.append(
            f"- Classifier ({clf}): {u['in']} in / {u['out']} out  "
            f"verdict={classifier.get('verdict')}  ≈{cost.get('classifier', 0):.3f}¢"
        )
    if librarian:
        u = librarian["usage"]
        lines.append(
            f"- Librarian ({voice}, {librarian['trigger']}): "
            f"{u['in']} in / {u['out']} out  ≈{cost.get('librarian', 0):.3f}¢"
        )
    lines.append(f"- **Turn total: ≈{cost.get('turn_total', 0):.3f}¢**")
    lines.append(f"- Session so far: ≈{cost.get('session_total', 0):.2f}¢")
    return "\n".join(lines)


def _hms(ts: str) -> str:
    return datetime.fromisoformat(ts).strftime("%H:%M:%S")


def render_turn(turn: dict, n: int) -> str:
    kind = turn.get("kind")
    chunks = turn.get("context_chunks") or []
    cost = turn.get("cost_cents") or {}
    mode = turn.get("mode") or {}

    summary_parts = [f"Retrieved {len(chunks)} passage(s)"]
    if mode.get("name"):
        summary_parts.append(f"{mode['name']} · effort {mode.get('effort', '?')}")
    summary_parts.append(f"≈{cost.get('turn_total', 0):.2f}¢")
    summary_parts.append(f"session ≈{cost.get('session_total', 0):.2f}¢")
    summary = " · ".join(summary_parts)

    user_name = turn.get("user_name") or "User"

    out: list[str] = []
    out.append(f"## Turn {n} · {_hms(turn['ts'])}")
    out.append("")

    geddes_text = (turn.get("geddes") or {}).get("text") or ""

    if kind == "librarian_explicit":
        out.append("_Librarian summoned explicitly via the action button._")
        out.append("")
        out.append(f"**Original question ({user_name}):** {turn.get('user', '')}")
        out.append("")
        if geddes_text:
            out.append(f"**{GEDDES} had said:**")
            out.append("")
            out.append(_quote(geddes_text))
            out.append("")
    else:
        out.append(f"**{user_name}:** {turn.get('user', '')}")
        out.append("")
        if geddes_text:
            out.append(f"**{GEDDES}:**")
            out.append("")
            out.append(geddes_text)
            out.append("")

    librarian = turn.get("librarian")
    if librarian and librarian.get("text"):
        out.append(f"**{LIBRARIAN}** ({librarian['trigger']}):")
        out.append("")
        out.append(librarian["text"])
        out.append("")

    out.append(f"<details><summary>{summary}</summary>")
    out.append("")
    out.append("**Retrieved chunks**")
    out.append("")
    out.append(_fmt_chunks(chunks))
    out.append("")
    out.append("**Tokens & cost**")
    out.append("")
    out.append(_fmt_tokens(turn))
    out.append("")
    out.append("</details>")
    out.append("")
    out.append("---")
    out.append("")
    return "\n".join(out)


def render(date: str) -> str | None:
    """Return the markdown for `date`, or None if no JSONL exists / is empty."""
    path = LOGS / f"{date}.jsonl"
    if not path.exists():
        return None
    turns = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not turns:
        return None

    total_cents = sum(
        (t.get("cost_cents") or {}).get("turn_total", 0) for t in turns
    )
    plain_turns = sum(1 for t in turns if t.get("kind") == "turn")
    explicit_lib = sum(1 for t in turns if t.get("kind") == "librarian_explicit")

    # Split the auto interjections by which trigger set fired, so false
    # positives are countable per axis rather than pooled.
    verdicts: dict[str, int] = {}
    for t in turns:
        v = (t.get("classifier") or {}).get("verdict")
        if v:
            verdicts[v] = verdicts.get(v, 0) + 1
    verdict_line = ", ".join(f"{k} {n}" for k, n in sorted(verdicts.items())) or "—"

    head = [
        f"# Geddes-folk transcript — {date}",
        "",
        f"- Conversational turns: **{plain_turns}**",
        f"- Classifier verdicts: **{verdict_line}**",
        f"- Explicit Librarian invocations: **{explicit_lib}**",
        f"- Estimated total cost: **≈{total_cents:.2f}¢** (≈${total_cents / 100:.3f})",
        "",
        "---",
        "",
    ]
    body = [render_turn(t, n) for n, t in enumerate(turns, 1)]
    return "\n".join(head + body)


def write(date: str | None = None) -> Path | None:
    """Render JSONL to logs/<date>.md. Returns the output path or None.

    Safe to call from app code: no sys.exit, no exception when the log is
    missing or empty — just returns None.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = render(date)
    if md is None:
        return None
    out_path = LOGS / f"{date}.md"
    out_path.write_text(md, encoding="utf-8")
    return out_path


def main() -> None:
    if len(sys.argv) > 2:
        sys.exit("usage: python transcript.py [YYYY-MM-DD]")
    date = sys.argv[1] if len(sys.argv) == 2 else None
    out = write(date)
    if out is None:
        target = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sys.exit(f"no log to render for {target}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
