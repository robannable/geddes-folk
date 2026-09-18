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
import ingest, retrieval, session_log, transcript, config, modes, dashboard

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

print("\n== corpus directories ==")
# corpus/raw/ is gitignored and rebuilt per install; corpus/studio/ ships
# with the repo for material that has no download_url. A manifest entry
# resolves against either, studio first.
check("studio dir is where ingest looks first",
      ingest.source_path.__doc__ is not None and
      (Path(__file__).parent / "corpus" / "studio").exists(), True)
check("studio material resolves",
      (ingest.source_path("site_analysis_topics.md") or Path("/nope")).parent.name,
      "studio")
check("an unfetched source resolves to None",
      ingest.source_path("definitely_not_here_9f3a.txt"), None)

print("\n== manifest is internally consistent ==")
# Not "every source is present" — the primary texts still need their
# archive.org identifiers, and that is a task, not a defect. What must
# hold is that nothing is SILENTLY unobtainable: an entry with no way to
# fetch it and no note explaining why would fail quietly at ingest and
# leave a voice unexpectedly ungrounded.
_manifest = json.loads((Path(__file__).parent / "corpus" / "manifest.json").read_text())
_pending = 0
for _e in _manifest:
    _fetchable = "download_url" in _e or "wikipedia_title" in _e
    _shipped = ingest.source_path(_e["file"]) is not None
    if not (_fetchable or _shipped):
        _pending += 1
    check(f"{_e['id']}: fetchable, shipped, or explained",
          _fetchable or _shipped or bool(_e.get("note")), True)
    for _key in ("id", "title", "file", "type", "voice"):
        check(f"{_e['id']}: has {_key}", _key in _e, True)
    check(f"{_e['id']}: chunker type is known",
          _e["type"] in ("prose", "chaptered"), True)
    check(f"{_e['id']}: voice is known",
          _e["voice"] in ("geddes", "librarian", "both"), True)
print(f"  NOTE  {_pending} entr{'y' if _pending == 1 else 'ies'} still need a "
      f"download_url (see README, Adding the primary texts)")

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

print("\n== cognitive mode detection ==")
for prompt, want in [
    ("What is the valley section? Describe it.", "survey"),
    ("Where did you observe this, and when?", "survey"),
    ("How do folk, work and place connect across a region?", "synthesis"),
    ("Why might we propose a different future for this site?", "proposition"),
    ("Imagine you could design an alternative strategy.", "proposition"),
    ("Hello.", "survey"),
    ("", "survey"),
]:
    check(repr(prompt[:38]), modes.detect(prompt).name, want)

# Documented collision: "survey" and "plan" are mode keywords and also
# central Geddes terms, so this ties 2-2 and the tie goes to survey.
check("Geddes-term collision ties to survey",
      modes.detect("What is the relationship between the survey and the plan?").name,
      "survey")

print("\n== effort resolution ==")
m, e, src = modes.resolve("Describe the site.")
check("survey -> medium", (m.name, e, src), ("survey", "medium", "auto (survey)"))
m, e, src = modes.resolve("How do these connect together across domains?")
check("synthesis -> high", (m.name, e), ("synthesis", "high"))
m, e, src = modes.resolve("Propose a vision for the future.")
check("proposition -> xhigh", (m.name, e), ("proposition", "xhigh"))

m, e, src = modes.resolve("Propose a vision for the future.", "low")
check("override replaces effort", e, "low")
check("override keeps the mode", m.name, "proposition")
check("override marked manual", src, "manual")

m, e, src = modes.resolve("Describe the site.", "nonsense")
check("unknown level falls back", (e, src), ("medium", "auto (survey)"))
m, e, src = modes.resolve("Describe the site.", modes.AUTO)
check("AUTO is auto", (e, src), ("medium", "auto (survey)"))

for mo in modes.MODES:
    check(f"{mo.name}: effort is a real level", mo.effort in modes.EFFORT_LEVELS, True)
    check(f"{mo.name}: has guidance text", bool(mo.guidance.strip()), True)

print("\n== dashboard axis ticks ==")
# Counts must get whole-number ticks; an axis reading 1.875 turns is noise.
for v, want_int in [(7, True), (3, True), (23, True), (1, True)]:
    ymax, n = dashboard._axis(v, integer=True)
    ticks = [ymax * i / n for i in range(n + 1)]
    check(f"max={v}: ticks are whole numbers {ticks}",
          all(abs(t - round(t)) < 1e-9 for t in ticks), True)
    check(f"max={v}: axis covers the data", ymax >= v, True)
check("zero data still gives an axis", dashboard._axis(0, True)[0] > 0, True)

print("\n== dashboard analysis ==")
from datetime import datetime, timezone
def _turn(day, verdict, mode, chunks, cost, user="Rob", kind="turn"):
    return {"ts": f"2026-09-{day:02d}T10:00:00+00:00", "kind": kind,
            "_when": datetime(2026, 9, day, 10, tzinfo=timezone.utc),
            "_day": f"2026-09-{day:02d}", "user_name": user,
            "user": "what is the valley section",
            "mode": {"name": mode, "effort": "high", "source": f"auto ({mode})"} if mode else None,
            "context_chunks": chunks,
            "geddes": {"text": "a b c", "usage": {"in": 1, "out": 1, "cache_read": 0, "cache_write": 0}},
            "classifier": {"verdict": verdict, "usage": {"in": 1, "out": 1, "cache_read": 0, "cache_write": 0}} if verdict else None,
            "librarian": None,
            "cost_cents": {"geddes": cost, "classifier": 0, "librarian": 0,
                           "turn_total": cost, "session_total": cost}}

GED = {"id": "a:1", "source_title": "Cities in Evolution", "voice": "both", "score": 0.6}
LIB = {"id": "b:1", "source_title": "Patrick Geddes (Wikipedia)", "voice": "librarian", "score": 0.4}

a = dashboard.analyse([
    _turn(1, "CHECK", "survey", [GED], 1.0),
    _turn(1, "SKIP", "synthesis", [], 2.0),
    _turn(2, "CONTEXT", "proposition", [LIB], 3.0, user="Amara"),
])
check("counts conversational turns", len(a["convo"]), 3)
check("groups by day", a["days"], ["2026-09-01", "2026-09-02"])
check("tallies verdicts", dict(a["verdicts"]), {"CHECK": 1, "SKIP": 1, "CONTEXT": 1})
check("sums cost", round(a["total_cost"], 2), 6.0)
# A librarian-only chunk does not count as grounding for Geddes — that
# distinction is the whole point of the retrieval-health panel.
check("grounded counts only geddes-visible chunks", a["grounded"], 1)
check("ungrounded counts the rest", a["ungrounded"], 2)
check("tracks both users", sorted(a["users"]), ["Amara", "Rob"])
check("per-day verdict series aligns with days",
      [len(v) for v in a["per_day_verdict"].values()], [2, 2, 2])

print("\n== dashboard renders without a browser ==")
html_out = dashboard.render(a, "2026-09-18 10:00 UTC", "all logs")
check("is a complete document", html_out.strip().startswith("<!DOCTYPE html>"), True)
check("closes the document", html_out.strip().endswith("</html>"), True)
check("makes no external requests", "http://" not in html_out and "https://" not in html_out, True)
check("declares dark mode under both scopes",
      'prefers-color-scheme:dark' in html_out and '[data-theme="dark"]' in html_out, True)
check("names both students", "Amara" in html_out and "Rob" in html_out, True)
check("states the retrieval-health percentage", "%" in html_out, True)

empty = dashboard.analyse([])
check("empty logs do not crash", dashboard.render(empty, "x", "y").count("<section>") > 0, True)

print("\n== chainlit integration ==")
# Needs chainlit installed. Skipped in the bare environment; run inside
# .venv (where the app runs) to actually exercise it.
try:
    import chainlit as cl
    from chainlit.input_widget import Select, TextInput
    from chainlit.server import app as server
    from fastapi.testclient import TestClient
except Exception as exc:
    print(f"  SKIP  chainlit not importable here ({type(exc).__name__}) — "
          f"run smoke.py inside .venv to cover the /dashboard route")
else:
    check("mount() registers the route", dashboard.mount(), True)
    # Chainlit's router ends in a catch-all that serves the chat SPA, and
    # it is registered first. A merely-appended route never runs: the
    # request 200s with the chat page instead. mount() moves it to the
    # front, and this is the assertion that catches a regression.
    check("/dashboard is matched before the SPA catch-all",
          getattr(server.routes[0], "path", None), "/dashboard")

    client = TestClient(server)
    r = client.get("/dashboard")
    check("GET /dashboard -> 200", r.status_code, 200)
    check("serves HTML", r.headers["content-type"].startswith("text/html"), True)
    body = r.text
    check("serves the report, not the chat SPA",
          "Retrieval health" in body and "<title>Assistant</title>" not in body, True)
    check("served page makes no external requests",
          "http://" not in body and "https://" not in body, True)
    check("served page is marked live", "Read live from logs" in body, True)
    check("served page offers the range controls",
          'href="/dashboard?days=14"' in body, True)

    r14 = client.get("/dashboard?days=14")
    check("?days scopes the report", "last 14 days" in r14.text, True)
    check("non-numeric ?days is rejected",
          client.get("/dashboard?days=nope").status_code, 422)

    # The widget classes app.py builds the settings panel from. They are
    # pydantic dataclasses, so the declared fields are what must match.
    check("TextInput has the fields app.py passes",
          {"id", "label", "initial", "description"} <= set(TextInput.__dataclass_fields__), True)
    check("Select has the fields app.py passes",
          {"id", "label", "values", "initial_index", "description"} <= set(Select.__dataclass_fields__), True)
    for attr in ("ChatSettings", "Action", "Step", "Message", "on_settings_update"):
        check(f"chainlit exposes cl.{attr}", hasattr(cl, attr), True)

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
