# geddes-folk — project handover

> Read end-to-end before touching code. This file exists so a fresh session
> doesn't re-litigate decisions already made.

## What this is

An interactive chatbot simulating conversation with **Patrick Geddes**
(1854–1932), with a second **Librarian** voice that fact-checks his claims and
contextualises his contested work. The user is **Rob Annable** (tutor,
Birmingham School of Architecture); the audience is architecture students.

It replaces the Streamlit **Geddes-Ghost** and is forked from the **sharp-folk**
engine. All three repos exist; this one is where new work goes.

## Settled decisions (do not undo)

### Two voices, two trigger sets

sharp-folk's Librarian is an *ethics corrective* — every classifier trigger is
contested ground. That specification does not transfer: Geddes's contested
material is real but thinner, and the pressing problem with a Geddes persona is
different. The persona prompt instructs him to be "bold, eccentric,
unpredictable", to reason abductively toward unusual conclusions, and to cite
specialists when out of his depth. That is a prompt tuned to generate confident
invented attributions, handed to students.

So the classifier returns **one of three verdicts**, not a boolean:

- `SKIP` — silent
- `CHECK` — Geddes made a checkable claim (attribution, quotation, date,
  figure, named work). The Librarian verifies against the corpus and says
  plainly when it cannot confirm.
- `CONTEXT` — contested ground. The Librarian supplies what he left out.

Rob chose both tracks over either alone, knowing the tuning cost. The verdict
is logged per turn precisely so false positives can be tuned per track.

**Contested-ground material for Geddes** — the Indian town planning reports
written for colonial administration (Indore 1918, Madras), the Zionist
Commission work and the 1925 Tel Aviv plan, the anabolic/katabolic theory in
*The Evolution of Sex* (1889, with J. Arthur Thomson) and its use in arguments
against women's suffrage and higher education, and paternalism about slum
populations. **This list was recalled, not checked.** Verify each item against
a source before it goes in a prompt.

### Division of labour

Same as sharp-folk and load-bearing: Geddes speaks in his own framework and
gestures at a field; the Librarian names the source, the date, the page. Do not
move attribution work into Geddes. Do not let the Librarian rewrite his answers
— it supplies what he didn't, alongside.

One change from the Geddes-Ghost persona when porting it: **remove the
instruction to cite other specialists, authors and experts freely.** That line
is the direct cause of the invented attributions the Librarian now exists to
catch.

### Platform: Chainlit

Inherited from sharp-folk, where it was chosen over Streamlit, Gradio,
FastAPI+HTMX, Next.js and Reflex for fastest-to-ship LLM chat with streaming,
threads and actions. Trade-off acknowledged: it looks like a chat product and
resists scholarly typography. Don't migrate without an explicit ask.

### Models

`config.py` is the single source of truth. Both voices on `claude-sonnet-5`;
classifier on `claude-haiku-4-5`.

- Sonnet 5 rather than sharp-folk's `claude-sonnet-4-6`: current generation and
  cheaper ($2/$10 per MTok against $3/$15). **Not** an upgrade to Opus — Rob
  chose the Sonnet tier deliberately and asked not to be nudged to Opus.
- `temperature`, `top_p` and `top_k` are **rejected with a 400** on Sonnet 5,
  Opus 5, Opus 4.7/4.8 and Fable. Geddes-Ghost's whole cognitive-mode →
  temperature mapping, its sidebar slider and its dashboard temperature tab
  depend on a parameter that no longer exists. The translation is
  cognitive mode → `output_config.effort` (`low`/`medium`/`high`/`xhigh`/`max`).
- Haiku 4.5 rejects `effort` — the classifier call sends neither `effort` nor
  adaptive thinking.
- Prompt-cache minimums are model-dependent: 512 tokens on Opus 5, 1024 on
  Sonnet 5 and Sonnet 4.6, 4096 on Haiku 4.5. sharp-folk's CLAUDE.md asserts a
  4096 minimum and concludes caching is inert; that is very likely wrong for
  its own config. Verify with `usage.cache_read_input_tokens > 0` rather than
  reasoning about it.

### Retrieval weighting

`weight_class` on each manifest entry becomes a multiplier on the FAISS
similarity, applied before the top-k cut so it can genuinely reorder:
`student` 1.5, `project` 1.3, `history` 1.2, `general` 1.0. A `student` chunk
whose `owner` doesn't match the current user is excluded outright, not merely
down-weighted.

`_name_matches` is deliberately loose — students type their name differently
each session. A false positive shows someone one of their own files; a false
negative hides their work from them, which is worse.

## Bugs inherited and fixed — don't reintroduce

**From Geddes-Ghost** (fixed on its `claude/gifted-dirac-dbefq9` branch, commit
`7f3fa04`, as the baseline for this port):

- `load_documents` tagged chunks with the bare basename, but the categorisers
  in `weight_context_chunks` and `assemble_enhanced_context` test for
  `'documents'`, `'history'` and `'students/'` in that string. Nothing from
  `documents/` matched, so every primary-corpus chunk fell through all branches
  and was dropped. Retrieval ran and its results were discarded; the persona
  answered alone. Here, chunks carry `weight_class` explicitly from the
  manifest rather than being inferred from a path.
- `chunk_info` indexed `weighted_similarities` by the enumerate counter, not
  the corpus index — so every logged relevance score, and every `chunk1_score`
  chart in the dashboard, was noise. Here, `Retriever.search` attaches the real
  weighted score to each returned chunk.
- `answer.replace("\\'", "')")` — stray paren, corrupted escaped apostrophes.
- `evaluate_response` got the mode temperature even under a manual override.

**From sharp-folk** (still live there):

- `PRICES_USD_PER_MTOK` was keyed on `claude-opus-4-7` while `VOICE_MODEL` was
  `claude-sonnet-4-6`. `cost_cents` returns `0.0` on a missing key, so every
  Sharp and Librarian cost figure in its logs and UI reads zero. Only the Haiku
  classifier was ever costed. `smoke.py` asserts both configured models are
  priced, so this fails loudly here.
- Its Opus 4.7 rates were stale too ($15/$75; actual $5/$25).
- UI and transcript labels hardcode "(Opus)" while the model is Sonnet. Here
  every label goes through `config.label()`.

## Current state

```
geddes-folk/
├── config.py           models, labels, cost rates, retrieval weights
├── ingest.py           manifest → clean_ocr → chunk → embed → FAISS
├── retrieval.py        load index, voice + student filter, weighted re-rank
├── session_log.py      per-turn JSONL + cost estimation
├── transcript.py       JSONL → Markdown (auto-called from log_turn)
├── fetch_corpus.py     manifest → corpus/raw/ (run locally; IA/Gutenberg/
│                       Wikipedia blocked from web sessions)
├── smoke.py            engine tests; runs without faiss/torch
├── corpus/manifest.json
├── corpus/raw/         two teaching docs present; books not fetched
├── public/patrick_geddes.jpg
├── run.sh / run.bat / ingest.bat / geddes-folk.service
└── requirements.txt, .env.example, README.md, CLAUDE.md
```

`ingest.py` chunkers: `prose` (paragraphs, sentence-split when long,
`min_words=15` filter that separates real chunks from page numbers and OCR
garbage) and `chaptered` (splits on `SECTION_HEADER`, then prose-chunks within
each chapter keeping every piece tagged with its chapter). `chunk_sections`
falling back to prose means the regex needs widening for that source, not that
the source has no chapters.

## Not yet built

1. **`app.py`** — Chainlit entrypoint. Follow sharp-folk's shape: retrieve →
   voice → classifier → conditional second voice → log, with `cl.Step` panels
   for retrieval and cost, and an "Ask the Librarian" action. Differences: a
   named user (Geddes-Ghost asked for a name; retrieval weighting needs it), a
   three-way classifier verdict, and cognitive modes.
2. **`modes.py`** — keyword scorer and prompt prefixes from
   `GeddesCognitiveModes` carried over intact; temperature mapping replaced by
   `survey → medium`, `synthesis → high`, `proposition → xhigh`. The
   temperature-guidance paragraphs appended to the character prompt survive
   unchanged — that half was always doing the work a sampling parameter wasn't.
   Manual override becomes a Chainlit chat setting picking effort directly.
3. **Prompts** — port `patrick_geddes_prompt.txt`, minus the free-citation
   instruction. Write the Librarian fresh against the two-track spec above;
   sharp-folk's `librarian_voice.txt` is the model for tone, not content.
4. **`dashboard.py`** — Streamlit over `logs/*.jsonl`. Ports from
   Geddes-Ghost's `admin_dashboard.py`: response metrics, document usage, user
   analysis, topics map, conversation insights, interventions, model usage.
   New: cost trends, and Librarian trigger rates split by verdict. The
   temperature tab has no honest equivalent — five effort levels against a
   continuous range, governing thinking depth rather than sampling. 1,200
   lines and the port is not mechanical: `st.session_state` has no Chainlit
   equivalent, and `ResponseEvaluator` currently lives in the dashboard and is
   imported back into the app, which needs untangling first.
5. **Corpus.** The gating item. See README; most manifest entries are
   `UNVERIFIED` with no `download_url`.
6. **Transcripts as corpus.** sharp-folk lacks this and Geddes-Ghost had it:
   fold yesterday's `logs/<date>.md` back in as a per-user `history` source so
   the tool accumulates a memory of a cohort across sessions.

## Constraints — please respect

1. **Don't over-engineer.** Rob values restraint. A bug fix doesn't need
   surrounding cleanup; a one-shot operation doesn't need a helper.
   Geddes-Ghost became a 1,200-line module plus a 1,200-line dashboard by
   accretion — that is the pattern being escaped.
2. **No additional doc files** unless asked. `README.md` and `CLAUDE.md` are
   the two.
3. **Files stay small and single-purpose.**
4. **Regulatory, dimensional and citation detail gets checked, not recalled.**
   This tool exists to stop a persona inventing citations; the code around it
   should hold itself to the same standard. Say "unverified, check X" rather
   than producing a plausible identifier — see the `note` fields in the
   manifest.
5. **sharp-folk and Geddes-Ghost are siblings, not dumping grounds.** Rob
   accepted three codebases knowingly. Fixes that apply to all three still have
   to be made in all three by hand.

## Provenance

Created in a Claude Code on the web session that reviewed Geddes-Ghost and
sharp-folk end-to-end, fixed the Geddes-Ghost baseline bugs, and forked the
sharp-folk engine here. Rob chose: both Librarian trigger sets, a separate repo
rather than one figure-configurable app, and the full port including the
dashboard.
