# geddes-folk

Conversations with **Patrick Geddes** (1854–1932) — biologist, sociologist, and
pioneer of town planning as "people planning" — with a second voice, the
Librarian, that checks what he claims and supplies what he leaves out.

Forked from the [sharp-folk](https://github.com/robannable/sharp-folk) engine
and carrying the cognitive-modes, named-user and analytics ideas from the
Streamlit [Geddes-Ghost](https://github.com/robannable/Geddes-Ghost) it replaces.

> **Status: engine only.** The retrieval, logging and transcript layers are in
> place and tested. `app.py`, `modes.py`, the prompts and the dashboard are not
> written yet — see *Where this is up to* below.

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
`ANTHROPIC_API_KEY`, and offers to build the corpus index.

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

Fetch runs on your own machine — web sessions block archive.org, gutenberg.org
and en.wikipedia.org:

```bash
python fetch_corpus.py                        # everything missing
python fetch_corpus.py wiki_geddes            # selected ids
python ingest.py                              # rebuild the index
```

**Most book entries carry a `note` saying `UNVERIFIED` and have no
`download_url`.** The archive.org identifiers were not confirmed — click
through each `source_url`, find the item, and add its `_djvu.txt` link. The
fetcher skips entries without a fetch field rather than guessing.

This matters more than it looks: Geddes-Ghost ran on three documents, and a
fact-checking Librarian with nothing to check against answers "I cannot confirm
that" to everything. Corpus work gates the Librarian being useful at all.

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

## Tests

```bash
python smoke.py
```

Runs without faiss or torch installed. Covers chunking, OCR cleanup, student
name matching, retrieval weighting, cost estimation and transcript rendering.
Not a substitute for `python ingest.py` and a real conversation.

## Where this is up to

Built and tested:

```
config.py          models, labels, cost rates, retrieval weights
ingest.py          manifest → clean → chunk (prose / chaptered) → embed → FAISS
retrieval.py       load index, voice + student filtering, weighted re-rank
session_log.py     per-turn JSONL + cost estimation
transcript.py      JSONL → Markdown
fetch_corpus.py    manifest → corpus/raw/
smoke.py           engine tests
```

Not yet written:

- `app.py` — Chainlit entrypoint, two voices, three-way classifier
- `modes.py` — cognitive modes (survey / synthesis / proposition) mapped to
  `output_config.effort`, since `temperature` is rejected by current models
- `prompts/patrick_geddes_persona.txt`, `prompts/librarian_voice.txt`
- `dashboard.py` — analytics over `logs/*.jsonl`
- The corpus itself (see above)
