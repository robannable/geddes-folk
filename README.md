# geddes-folk

Conversations with **Patrick Geddes** (1854–1932) — biologist, sociologist, and
pioneer of town planning as "people planning" — with a second voice, the
Librarian, that checks what he claims and supplies what he leaves out.

Forked from the [sharp-folk](https://github.com/robannable/sharp-folk) engine
and carrying the cognitive-modes, named-user and analytics ideas from the
Streamlit [Geddes-Ghost](https://github.com/robannable/Geddes-Ghost) it replaces.

> **Status: app runs; corpus is the gap.** Both voices, the three-way
> classifier, cognitive modes and logging are wired. The dashboard is not
> built, and most of the corpus is not fetched — see *Where this is up to*.

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
`download_url` to the manifest.

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

## Tests

```bash
python smoke.py
```

Runs without faiss or torch installed. Covers chunking, OCR cleanup, student
name matching, retrieval weighting, cost estimation and transcript rendering.
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
prompts/           Geddes persona, Librarian voice
smoke.py           56 assertions, no faiss/torch needed
```

Not built:

- **`dashboard.py`** — analytics over `logs/*.jsonl`. Ports from Geddes-Ghost's
  `admin_dashboard.py`: response metrics, document usage, user analysis, topics
  map, conversation insights, interventions. New: cost trends, and classifier
  verdict rates split by track. The temperature tab has no honest equivalent.
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
