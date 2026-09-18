# geddes-folk

Conversations with **Patrick Geddes** (1854–1932) — biologist, sociologist, and
the man who insisted that town planning is really people planning.

Two voices share the chat. Geddes speaks in his own framework, and a second
voice, the Librarian, checks what he claims and supplies what he leaves out.

Built for architecture students, by Rob Annable at Birmingham School of
Architecture, as part of an experiment in treating large language models as
cultural technology and tools for thought.

## The two voices

**Patrick Geddes** speaks in the first person, self-aware as a ghost in a
neural network — bold, associative, given to the abductive leap and the
provocative question back. He owns his contested work rather than deflecting
it, and he marks recollection as recollection instead of manufacturing a
citation.

**The Librarian** is a contemporary archivist sharing the conversation. It
holds the archive and does the attribution work, on two tracks:

| Verdict | Fires when | What the Librarian does |
|---|---|---|
| `CHECK` | Geddes made a checkable claim — an attribution, quotation, date, figure or named work | verifies it against the corpus, gives the reference, and says plainly when it cannot confirm |
| `CONTEXT` | contested ground — the Indian reports written under British paramountcy, the Zionist Commission work and the 1925 Tel Aviv plan, the anabolic/katabolic theory and its use against women's suffrage, paternalism towards the poor | supplies what a student needs in order to judge, without rewriting his answer |
| `SKIP` | neither | stays silent |

A cheap classifier decides which, after every reply. Students can also summon
the Librarian directly with the button beneath any of Geddes's answers.

Both verdicts are logged separately, so false positives on each track can be
tuned independently.

## Quick start

### Windows

Double-click **`run.bat`**. The first run creates `.venv`, installs
dependencies (~1 GB, includes torch), copies `.env.example` → `.env` for your
`ANTHROPIC_API_KEY`, then offers to download the corpus and build the search
index before launching. Later runs go straight to the app.

Three companions, all using the same venv:

| | |
|---|---|
| `fetch.bat` | download manifest entries into `corpus/raw/` |
| `ingest.bat` | rebuild the search index |
| `dashboard.bat` | export the log report and open it |

### Mac / Linux

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then add ANTHROPIC_API_KEY
python fetch_corpus.py      # download the corpus
python ingest.py            # build the index (~130 MB model download, once)
chainlit run app.py
```

`run.sh` wraps all of that, including the first-run setup.

Opens on http://localhost:8000.

### VPS

`geddes-folk.service` is a systemd unit for the app. Adjust `WorkingDirectory`
and `User`, then `systemctl enable --now geddes-folk`.

## Using it

**Set your name** in the settings panel — the slider icon beside the message
box. Geddes addresses you by it, and any of your own work in the corpus is
surfaced ahead of the general material.

The same panel has an **Effort** control. On *auto* it follows the kind of
question asked; fix it yourself to override.

Each reply carries an **Ask the Librarian** button, and two foldable panels
showing what was retrieved and what the turn cost.

## The corpus

Corpus texts are **built per install, not shipped**. `corpus/raw/` and
`corpus/index/` are gitignored, so a clone stays small and nobody commits a
500 KB djvu dump; `fetch_corpus.py` downloads the texts and `ingest.py` builds
the index. Material that belongs to the repo and has no `download_url` —
teaching notes, studio briefs — lives in `corpus/studio/` and is tracked.
A manifest entry resolves against either directory, studio first.

`corpus/manifest.json` lists every source. Each entry is split by **voice**:

- `"both"` — Geddes's own writings and the studio's teaching material. Both
  voices see them; the Librarian quotes them when citing.
- `"librarian"` — background and scholarship the Librarian alone sees.

and carries a **`weight_class`** that multiplies its similarity score before
the top-k cut, so it can genuinely reorder results:

| Class | Weight | |
|---|---|---|
| `student` | 1.5× | a student's own uploaded work, visible only to them |
| `project` | 1.3× | studio briefs and teaching material |
| `history` | 1.2× | past conversation transcripts |
| `general` | 1.0× | everything else |

### Adding a source

Add an entry with `id`, `title`, `file`, `type` (`prose` or `chaptered`),
`voice`, `weight_class`, a `source_url` for citation, and one of
`download_url` (direct plain-text fetch) or `wikipedia_title`. For your own
material, drop the file in `corpus/studio/` instead and omit both. Then:

```bash
python fetch_corpus.py                 # everything missing
python fetch_corpus.py cities_in_evolution   # or just one
python ingest.py                       # rebuild the index
```

Fetching needs outbound access to archive.org, gutenberg.org and Wikipedia, so
run it on your own machine rather than from a web session.

### Adding the primary texts

Five entries are listed but have no `download_url` yet, because their
archive.org identifiers need confirming by hand:

| id | |
|---|---|
| `cities_in_evolution` | *Cities in Evolution* (1915) — start here |
| `city_development` | the Dunfermline report (1904) |
| `evolution_of_sex` | *The Evolution of Sex* (1889, with Thomson) |
| `evolution_1911` | *Evolution* (1911, with Thomson) |
| `indore_report` | the Indore town planning report (1918) |

For each: open its `source_url`, find the item, copy the "Full Text" /
`_djvu.txt` link into a `download_url` field, then fetch and re-ingest.

*Cities in Evolution* is the one to do first — the valley section,
conservative surgery and the diagnostic survey are all in it, and that is most
of what students ask about.

Until they are in, Geddes answers from what the model already knows rather
than from retrieved passages, and the Librarian's `CHECK` track can catch a
wrong date but cannot confirm a quotation. The **retrieval health** panel on
the dashboard tracks exactly this.

## Dashboard

Served by the running app at **`/dashboard`** — same host and port as the chat.
It reads the logs on each request, so a reload always shows the current state,
and the control at the top right filters by date range. A link appears in a
folded step at the start of every chat.

**Overview** · **retrieval health** — what share of turns reached Geddes with
a passage he can actually see · **Librarian triggers**, split by `CHECK` and
`CONTEXT` so each track can be tuned separately · **cognitive modes** against
reply length · **cost** per day by voice · **corpus usage** and how well each
source scores · **students** · **what is being asked** · **interventions** —
sources reached often but matched weakly · and a table of every turn.

For a copy to keep or send on:

```bash
python dashboard.py              # -> logs/dashboard.html
python dashboard.py --days 14
python dashboard.py --out /tmp/report.html
```

Charts are inline SVG generated in Python, so the page renders identically
served, saved or emailed, and the palette is validated for colour-vision
deficiency in both light and dark.

## Logs

Every turn appends to `logs/YYYY-MM-DD.jsonl`: the student and their question,
retrieved chunks with scores and weight classes, each voice's reply and token
usage, the classifier verdict, the cognitive mode and effort, and a cost
breakdown with a running session total.

`logs/<date>.md` is re-rendered after every turn as a readable transcript —
conversation first, metadata behind `<details>`. Render any day on demand:

```bash
python transcript.py             # today (UTC)
python transcript.py 2026-09-18
```

The JSONL is the source of truth; the Markdown and the dashboard are both
views of it.

## Configuration

`config.py` holds everything that names or prices a model, plus the retrieval
weights.

| | |
|---|---|
| `VOICE_MODEL` | both voices — `claude-sonnet-5` |
| `CLASSIFIER_MODEL` | the trigger classifier — `claude-haiku-4-5` |
| `PRICES_USD_PER_MTOK` | approximate rates for cost estimation |
| `CONTEXT_WEIGHTS` | the retrieval multipliers above |
| `RETRIEVE_K` | passages retrieved per voice per turn |

Add a row to `PRICES_USD_PER_MTOK` before pointing `VOICE_MODEL` at a new
model, or its costs will report as zero. The Anthropic billing console is the
authority on rates.

Cognitive modes live in `modes.py`: `survey` → effort `medium`, `synthesis` →
`high`, `proposition` → `xhigh`, each with its own prompt framing.

The two prompts are plain text in `prompts/` and are meant to be edited.

## Layout

```
app.py             Chainlit entrypoint — two voices, classifier, logging
config.py          models, cost rates, retrieval weights
modes.py           cognitive modes → effort levels
retrieval.py       load the index, filter by voice and student, re-rank
ingest.py          manifest → clean → chunk → embed → FAISS
fetch_corpus.py    manifest → corpus/raw/
session_log.py     per-turn JSONL + cost estimation
transcript.py      JSONL → Markdown
dashboard.py       log analysis, served at /dashboard or exported
smoke.py           tests
prompts/           Geddes persona, Librarian voice
corpus/            manifest.json
  studio/            repo-owned text — tracked
  raw/               fetched text — gitignored
  index/             FAISS index — gitignored
public/            portrait served at /public/
chainlit.md        welcome screen
```

## Tests

```bash
python smoke.py
```

Covers chunking, OCR cleanup, student name matching, retrieval weighting, cost
estimation, mode detection, effort resolution, transcript rendering and
dashboard analysis — and runs without faiss or torch installed.

Run it inside `.venv` and it additionally exercises the `/dashboard` route
against a real Chainlit server. Outside `.venv` that block skips with a note.

## Reference

Design rationale, the reasoning behind the two-voice split, and handover notes
for further work are in [CLAUDE.md](CLAUDE.md).
