"""Engine smoke test — runs without faiss/torch installed.

    python smoke.py

Covers the pure logic: chunking, OCR cleanup, student name matching,
retrieval weighting, cost estimation, and transcript rendering. It does
not touch the API or a built index — `python ingest.py` and a real
conversation are still the test for those.

The cost-estimation block exists because sharp-folk's price table was
keyed on a model it never called, so every cost it reported read zero
with no error. These assertions fail loudly if that recurs.
"""
import sys, types, json
from pathlib import Path

# Stub the heavy deps so ingest/retrieval import.
for name in ("faiss", "sentence_transformers", "numpy"):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            m = types.ModuleType(name)
            if name == "sentence_transformers":
                m.SentenceTransformer = object
            if name == "faiss":
                m.read_index = m.write_index = m.IndexFlatIP = lambda *a, **k: None
            if name == "numpy":
                m.asarray = lambda *a, **k: None
            sys.modules[name] = m

sys.path.insert(0, str(Path(__file__).parent))
import ingest, retrieval, session_log, transcript, config

ok = fail = 0
def check(label, got, want):
    global ok, fail
    if got == want:
        ok += 1; print(f"  PASS  {label}")
    else:
        fail += 1; print(f"  FAIL  {label}\n        got  {got!r}\n        want {want!r}")

print("\n== chunk_sections on a Geddes-shaped text ==")
sample = """Preface to the reader, which runs on for a good while and says
a number of things worth at least fifteen words so that it survives the
minimum word filter applied by the prose chunker downstream.

CHAPTER I. THE VALLEY SECTION

The valley section runs from hills to sea, and each of its reaches
carries its own occupation: the miner, the woodman, the hunter, the
shepherd, the peasant, the fisher. Folk, work and place are one.

CHAPTER II. CONSERVATIVE SURGERY

Rather than clearance, the diagnostic survey. We open a close here and
plant a garden there, and the quarter lives on rather than being swept
away wholesale by the improver's plan.
"""
secs = ingest.chunk_sections(sample)
titles = [s["section_title"] for s in secs]
check("front matter untitled", titles[0], None)
check("chapter I detected", "THE VALLEY SECTION" in (titles[1] or ""), True)
check("chapter II detected", "CONSERVATIVE SURGERY" in (titles[-1] or ""), True)
check("all sections have text", all(s["text"].strip() for s in secs), True)

print("\n== chunk_sections falls back to prose with no headers ==")
plain = "One paragraph of at least fifteen words so that it clears the minimum filter that ingest applies.\n\nAnother such paragraph, also long enough to survive the very same minimum word count filter."
fb = ingest.chunk_sections(plain)
check("fallback yields untitled chunks", [s["section_title"] for s in fb], [None, None])

print("\n== clean_ocr ==")
check("rejoins hyphenated linebreak", "planning" in ingest.clean_ocr("plan-\nning"), True)
check("collapses blank runs", ingest.clean_ocr("a\n\n\n\n\nb"), "a\n\nb")

print("\n== student name matching ==")
check("exact", retrieval._name_matches("Rob Annable", "Rob Annable"), True)
check("first name only", retrieval._name_matches("Rob", "Rob Annable"), True)
check("case + spacing", retrieval._name_matches("  rob annable ", "Rob Annable"), True)
check("different student excluded", retrieval._name_matches("Sam", "Rob Annable"), False)
check("empty user excluded", retrieval._name_matches("", "Rob Annable"), False)
check("empty owner excluded", retrieval._name_matches("Rob", ""), False)

print("\n== retrieval weighting ==")
r = retrieval.Retriever.__new__(retrieval.Retriever)   # no index needed for _weight
check("general", r._weight({"weight_class": "general"}, "Rob"), 1.0)
check("project boosted", r._weight({"weight_class": "project"}, "Rob"), 1.3)
check("history boosted", r._weight({"weight_class": "history"}, "Rob"), 1.2)
check("own work boosted", r._weight({"weight_class": "student", "owner": "Rob"}, "Rob"), 1.5)
check("other's work excluded", r._weight({"weight_class": "student", "owner": "Sam"}, "Rob"), 0.0)
check("unknown class defaults", r._weight({"weight_class": "nonsense"}, "Rob"), 1.0)

print("\n== cost estimation (the thing that read zero in sharp-folk) ==")
u = {"in": 1_000_000, "out": 0, "cache_read": 0, "cache_write": 0}
check("sonnet 5 input $2/MTok -> 200c", round(session_log.cost_cents("claude-sonnet-5", u), 2), 200.0)
check("haiku input $1/MTok -> 100c", round(session_log.cost_cents("claude-haiku-4-5", u), 2), 100.0)
check("VOICE_MODEL is priced", session_log.cost_cents(config.VOICE_MODEL, u) > 0, True)
check("CLASSIFIER_MODEL is priced", session_log.cost_cents(config.CLASSIFIER_MODEL, u) > 0, True)
check("unknown model -> 0.0", session_log.cost_cents("claude-nope", u), 0.0)
check("None usage -> 0.0", session_log.cost_cents("claude-sonnet-5", None), 0.0)

print("\n== labels come from config, not hardcoded 'Opus' ==")
check("sonnet 5 label", config.label("claude-sonnet-5"), "Sonnet 5")
check("unknown passes through", config.label("claude-future-9"), "claude-future-9")

print("\n== transcript renders a turn ==")
turn = {
    "ts": "2026-09-18T10:00:00+00:00", "kind": "turn",
    "user_name": "Rob", "user": "What is the valley section?",
    "mode": {"name": "survey", "effort": "medium"},
    "geddes": {"text": "From hills to sea, my friend.", "usage": {"in": 900, "out": 120, "cache_read": 0, "cache_write": 0}},
    "classifier": {"verdict": "CHECK", "usage": {"in": 300, "out": 2, "cache_read": 0, "cache_write": 0}},
    "librarian": {"trigger": "auto", "text": "Geddes set this out in Cities in Evolution (1915).",
                  "usage": {"in": 800, "out": 90, "cache_read": 0, "cache_write": 0}},
    "context_chunks": [{"id": "cities_in_evolution:s0007", "source_title": "Cities in Evolution",
                        "source_year": "1915", "section_title": "THE VALLEY SECTION",
                        "weight_class": "general", "score": 0.71}],
    "cost_cents": {"geddes": 0.3, "classifier": 0.03, "librarian": 0.25, "turn_total": 0.58, "session_total": 0.58},
}
md = transcript.render_turn(turn, 1)
check("names the user", "**Rob:**" in md, True)
check("names Geddes from config", f"**{config.GEDDES}:**" in md, True)
check("names Librarian with trigger", f"**{config.LIBRARIAN}** (auto):" in md, True)
check("shows mode and effort", "survey · effort medium" in md, True)
check("shows chunk score", "score 0.71" in md, True)
check("labels model, not 'Opus'", "Geddes (Sonnet 5):" in md, True)
check("no stale Opus label", "Opus" in md, False)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
