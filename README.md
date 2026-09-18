# geddes-folk

Conversations with **Patrick Geddes** (1854–1932) — biologist, sociologist, and
pioneer of town planning as "people planning" — with a second voice, the
Librarian, that checks what he claims and supplies what he leaves out.

Forked from the [sharp-folk](https://github.com/robannable/sharp-folk) engine
and carrying the cognitive-modes, named-user and analytics ideas from the
Streamlit [Geddes-Ghost](https://github.com/robannable/Geddes-Ghost) it replaces.

> **Status: complete except the corpus.** Both voices, the three-way
> classifier, cognitive modes, logging and the dashboard are built. Most of
> the corpus is not fetched — see *What a fresh install actually indexes*.

## The two voices

**Patrick Geddes** speaks in first person, self-aware as a ghost in a neural
network — bold, eccentric, pushing for abductive leaps and unexpected
connections. That is the character, and it is also the risk: a persona tuned to
make confident cross-disciplinary claims will invent attributions, and these
conversations are had with architecture students.

**The Librarian** is the answer to that, on two tracks:

| Verdict | Fires when | What the Librarian does |
|---|---|---|
| `SKIP` | neither below | stays silent |
| `CHECK` | Geddes made a checkable claim — an attribution, quotation, date, figure or named work | verifies it against the corpus, and says plainly when it cannot be confirmed |
| `CONTEXT` | contested ground — the Indian reports written for colonial administration, the Zionist Commission work and 1925 Tel Aviv plan, the anabolic/katabolic sex theory and its use against women's suffrage, paternalism about slum populations | supplies what Geddes left out, without rewriting his answer |

Both verdicts are recorded per turn so false positives can be tuned on each
track separately — which is the cost of running two trigger sets instead of one.

## Quick start

### Windows

Double-click `run.bat`. First run creates `.venv`, installs dependencies
(~1 GB, includes torch), copies `.env.example` → `.env` for your
`ANTHROPIC_API_KEY`, then offers to **download the corpus and build the
index** before launching.

Afterwards, `fetch.bat` downloads new manifest entries and `ingest.bat`
rebuilds the index — the pair you'll want each time you add a
`download_url` to the manifest. `dashboard.bat` renders the log report and
opens it.

### Mac / Linux

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then add ANTHROPIC_API_KEY
python fetch_corpus.py      # download the corpus (run locally — see below)
python ingest.py            # build corpus/index/ (~130MB model download)
chainlit run app.py
```

### VPS

`geddes-folk.service` is a systemd unit for the Chainlit app, adapted from
Geddes-Ghost's. Adjust `WorkingDirectory` and `User` before installing.

## Corpus

`corpus/manifest.json` is split by **voice**:

- `"voice": "both"` — Geddes's own writings and the teaching material. Both
  voices see them; the Librarian quotes them when citing.
- `"voice": "librarian"` — background and scholarship the Librarian alone sees.

and weighted by **`weight_class`**, carried over from Geddes-Ghost's
`CONTEXT_WEIGHTS`: `student` (1.5×, and only visible to the named student who
owns it), `project` (1.3×), `history` (1.2×), `general` (1.0×). The weights are
multipliers on the FAISS similarity, applied before the top-k cut, so they can
actually reorder results.

`run.bat` / `run.sh` do the first fetch and ingest for you. Afterwards, or on
a machine where you're driving it by hand:

```bash
python fetch_corpus.py                        # everything missing
python fetch_corpus.py wiki_geddes            # selected ids
python ingest.py                              # rebuild the index
```

On Windows: `fetch.bat` and `ingest.bat` wrap those two against the venv.

Note that fetching has to happen on a machine with outbound access — Claude
Code on the web sessions block archive.org, gutenberg.org and en.wikipedia.org,
which is why the corpus isn't already in the repo.

**Most book entries carry a `note` saying `UNVERIFIED` and have no
`download_url`.** The archive.org identifiers were not confirmed — click
through each `source_url`, find the item, and add its `_djvu.txt` link. The
fetcher skips entries without a fetch field rather than guessing.

### What a fresh install actually indexes

Only 7 of the 12 manifest entries, and the split is lopsided:

| Voice | Sources | What |
|---|---:|---|
| Geddes | 2 | the two teaching documents (974 words) — **none of his own writing** |
| Librarian | 7 | those two, plus five Wikipedia articles |

The five books are all `UNVERIFIED` and don't index. So out of the box Geddes
is reconstructed almost entirely from what the model already knows about him,
with nothing retrieved to hold him to, and the Librarian's CHECK track can
catch a wrong date but cannot confirm a quotation or a page.

This matters more than it looks: Geddes-Ghost ran on three documents, and a
fact-checking Librarian with nothing to check against answers "I cannot confirm
that" to everything. Corpus work gates the Librarian being useful at all, and
*Cities in Evolution* is the one to find first — the valley section,
conservative surgery and the diagnostic survey all live there, and that is most
of what students will ask about.

## Observation surfaces

Per turn, `logs/YYYY-MM-DD.jsonl` records the user and their message, retrieved
chunk metadata with scores and weight classes, each voice's reply and token
usage, the classifier verdict, the cognitive mode and effort level, and a cost
breakdown with a running session total.

`logs/<date>.md` is re-rendered after every turn — conversation first, with
chunks and token counts behind `<details>`. Re-render any day on demand:

```bash
python transcript.py             # today (UTC)
python transcript.py 2026-09-18  # specific date
```

Cost rates live in `config.py:PRICES_USD_PER_MTOK` and are approximate; the
Anthropic billing console is the source of truth. `cost_cents` returns `0.0`
for a model missing from that table — silently, which is how the same tracking
died in sharp-folk — so add a row before repointing `VOICE_MODEL`.

## Dashboard

Served by the running app at **`/dashboard`** — same host and port as the
chat, no second process and no extra dependency. Chainlit runs on FastAPI
and `dashboard.mount()` registers the route on that same server. It reads
`logs/*.jsonl` per request, so reloading always shows the current state,
and the day-range control at the top right filters it
(`/dashboard?days=14`). A link appears in a folded step at the start of
each chat.

For a copy to keep or send on:

```bash
python dashboard.py              # all logs  -> logs/dashboard.html
python dashboard.py --days 14    # last fortnight
python dashboard.py --out /tmp/report.html
```

`dashboard.bat` does the same on Windows and opens the result. Charts are
inline SVG generated in Python rather than drawn by a charting library, so
the page renders identically served, saved or emailed.

Panels: overview, **retrieval health** (what share of turns actually reached
Geddes with a passage — the check the predecessor failed silently), Librarian
triggers split by CHECK / CONTEXT so the two tracks can be tuned separately,
cognitive modes against reply length, cost per day by voice, corpus usage,
students, question keywords, interventions, and a table of every turn.

Two things it deliberately does not do. There is no successor to
Geddes-Ghost's temperature analysis — temperature is rejected by current
models, so there is no continuous dial to plot response length against, and
the cognitive-mode panel is the nearest honest equivalent. And the
interventions panel reports scores against the median of the set it is
looking at rather than an absolute threshold, because a similarity number
only means something relative to the same corpus and embedding model.

Colours come from a palette validated for colour-vision deficiency on all
pairs in both light and dark. Adding a fourth series would break that, so
extra categories fold into "other" rather than getting a new hue.

## Tests

```bash
python smoke.py
```

Runs without faiss or torch installed. Covers chunking, OCR cleanup, student
name matching, retrieval weighting, cost estimation, mode detection, effort
resolution, transcript rendering and dashboard analysis.

Run it inside `.venv`, where Chainlit is installed, and it also exercises the
`/dashboard` route against a real Chainlit server — including that the route
is matched ahead of Chainlit's catch-all, which is the failure that makes
`/dashboard` silently return the chat page with a 200. Outside `.venv` that
block skips with a note.

Not a substitute for `python ingest.py` and a real conversation.

## Where this is up to

Built:

```
app.py             Chainlit entrypoint — two voices, three-way classifier
modes.py           cognitive modes → output_config.effort
config.py          models, labels, cost rates, retrieval weights
ingest.py          manifest → clean → chunk (prose / chaptered) → embed → FAISS
retrieval.py       load index, voice + student filtering, weighted re-rank
session_log.py     per-turn JSONL + cost estimation
transcript.py      JSONL → Markdown
fetch_corpus.py    manifest → corpus/raw/
dashboard.py       log analysis; served at /dashboard, or exported
prompts/           Geddes persona, Librarian voice
smoke.py           97 assertions (80 without chainlit installed)
```

Not built:

- **The corpus.** Most manifest entries are `UNVERIFIED` with no
  `download_url`. Until they're fetched, the Librarian's CHECK track has almost
  nothing to check against and will correctly but uselessly answer "I can't
  confirm that".
- **Transcripts as corpus.** Fold yesterday's `logs/<date>.md` back in as a
  per-user `history` source, so the tool accumulates a memory of a cohort.

## Cognitive modes

Carried over from Geddes-Ghost, with one forced change. It varied `temperature`
per mode (survey 0.7, synthesis 0.8, proposition 0.9); `temperature`, `top_p`
and `top_k` are rejected with a 400 on every current model. The nearest
equivalent is `output_config.effort`, which governs how much the model thinks
rather than how randomly it samples:

| Mode | Triggered by | Effort |
|---|---|---|
| survey | what, describe, observe, where, when | `medium` |
| synthesis | how, connect, relate, pattern, between | `high` |
| proposition | why, propose, imagine, design, future | `xhigh` |

The prompt prefixes and guidance paragraphs survive unchanged — they were
always doing more of the work than the sampler was. Override the effort level
in the settings panel; the mode still follows from the question, so the prose
steering stays.

Known collision, left alone: "survey", "plan", "pattern" and "design" are mode
keywords *and* central Geddes terms, so a question about his diagnostic survey
scores toward survey mode whatever it asks. The scorer is crude on purpose. If
the logs show modes consistently misread, prune the keyword lists before adding
machinery.
