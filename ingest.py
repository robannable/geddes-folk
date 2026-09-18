"""Build the corpus index.

Reads corpus/manifest.json, processes each source whose `file` is present in
corpus/raw/, and writes:

    corpus/index/chunks.jsonl   — one JSON object per chunk
    corpus/index/vectors.faiss  — FAISS index, parallel order to chunks.jsonl

Run:
    python ingest.py

The chunker has two modes selected by the manifest entry's `type`:
    "prose"      — paragraph chunks; long paragraphs split at sentence
                   boundaries to stay under the embed model's window.
    "chaptered"  — one chunk per detected chapter or section header, plus
                   any front matter as prose chunks. Geddes's books are
                   long and argue by chapter; keeping a chapter's text
                   together gives retrieval a coherent unit.

OCR cleanup is intentionally light — per-source tuning is expected. Re-run
this script after any change to the manifest or to corpus/raw/.
"""

import json
import re
import sys
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).parent
RAW = ROOT / "corpus" / "raw"
INDEX = ROOT / "corpus" / "index"
MANIFEST = ROOT / "corpus" / "manifest.json"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# "CHAPTER IV", "CHAPTER 4.", "IV. THE VALLEY SECTION", "PART TWO"
SECTION_HEADER = re.compile(
    r"^\s*(?:(?:CHAPTER|PART|BOOK|SECTION)\s+)?"
    r"([IVXLC]+|\d+)\.?\s+([A-Z][A-Z\s\-,'.]{3,})$",
    re.MULTILINE,
)

GUTENBERG_START = re.compile(
    r"\*\*\*\s*START OF (?:THE |THIS )?PROJECT GUTENBERG.*?\*\*\*", re.IGNORECASE
)
GUTENBERG_END = re.compile(
    r"\*\*\*\s*END OF (?:THE |THIS )?PROJECT GUTENBERG.*?\*\*\*", re.IGNORECASE
)


def clean_ocr(text: str) -> str:
    m = GUTENBERG_START.search(text)
    if m:
        text = text[m.end():]
    m = GUTENBERG_END.search(text)
    if m:
        text = text[: m.start()]
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def chunk_prose(text: str, max_words: int = 350, min_words: int = 15) -> list[str]:
    """Paragraph-based prose chunker.

    Long paragraphs are split at sentence boundaries; a single oversized
    sentence is hard-split on word boundaries. Chunks shorter than
    `min_words` are dropped — these are dominated by page numbers, running
    heads, OCR garbage, and one-letter ornamentals in scanned djvu texts.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    for p in paragraphs:
        words = p.split()
        if len(words) <= max_words:
            chunks.append(p)
            continue
        sents = re.split(r"(?<=[.!?])\s+", p)
        buf: list[str] = []
        count = 0
        for s in sents:
            sw = s.split()
            if len(sw) > max_words:
                if buf:
                    chunks.append(" ".join(buf))
                    buf, count = [], 0
                for i in range(0, len(sw), max_words):
                    chunks.append(" ".join(sw[i : i + max_words]))
                continue
            if count + len(sw) > max_words and buf:
                chunks.append(" ".join(buf))
                buf, count = [s], len(sw)
            else:
                buf.append(s)
                count += len(sw)
        if buf:
            chunks.append(" ".join(buf))
    return [c for c in chunks if len(c.split()) >= min_words]


def chunk_sections(text: str, max_words: int = 350) -> list[dict]:
    """Split on chapter/section headers, then prose-chunk within each.

    Falls back to plain prose chunking when no headers match — which is
    the signal that SECTION_HEADER needs widening for that source rather
    than that the source has no chapters.
    """
    headers = list(SECTION_HEADER.finditer(text))
    if not headers:
        return [{"section_title": None, "text": c} for c in chunk_prose(text)]

    out: list[dict] = []
    front = text[: headers[0].start()].strip()
    if front:
        for piece in chunk_prose(front):
            out.append({"section_title": None, "text": piece})

    for i, m in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        title = m.group(2).strip().rstrip(".")
        body = text[m.start() : end].strip()
        # A chapter is far longer than the embed window, so prose-chunk
        # inside it while keeping every piece tagged with its chapter.
        for piece in chunk_prose(body, max_words=max_words):
            out.append({"section_title": title, "text": piece})
    return out


def build_chunks(manifest: list[dict]) -> list[dict]:
    all_chunks: list[dict] = []
    for src in manifest:
        path = RAW / src["file"]
        if not path.exists():
            print(f"  skip {src['id']}: {path.name} not found", file=sys.stderr)
            continue
        text = clean_ocr(path.read_text(encoding="utf-8"))

        base = {
            "source_id": src["id"],
            "source_title": src["title"],
            "source_year": src.get("year"),
            "source_url": src.get("source_url"),
            "voice": src.get("voice", "both"),
            # Retrieval weighting, read by Retriever._weight.
            "weight_class": src.get("weight_class", "general"),
            "owner": src.get("owner"),
        }

        if src["type"] == "prose":
            pieces = chunk_prose(text)
            for i, piece in enumerate(pieces):
                all_chunks.append({
                    "id": f"{src['id']}:p{i:04d}",
                    "type": "prose",
                    "section_title": None,
                    "text": piece,
                    **base,
                })
        elif src["type"] == "chaptered":
            sections = chunk_sections(text)
            for i, sec in enumerate(sections):
                all_chunks.append({
                    "id": f"{src['id']}:s{i:04d}",
                    "type": "section" if sec["section_title"] else "prose",
                    "section_title": sec["section_title"],
                    "text": sec["text"],
                    **base,
                })
        else:
            print(f"  unknown type {src['type']!r} for {src['id']}", file=sys.stderr)
            continue

        added = sum(1 for c in all_chunks if c["source_id"] == src["id"])
        print(f"  {src['id']}: {added} chunks")
    return all_chunks


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not manifest:
        print("manifest is empty; add entries to corpus/manifest.json", file=sys.stderr)
        return 1

    print("chunking sources...")
    chunks = build_chunks(manifest)
    if not chunks:
        print("no chunks produced (no raw files found?)", file=sys.stderr)
        return 1
    print(f"total chunks: {len(chunks)}")

    print(f"loading embed model {EMBED_MODEL}...")
    model = SentenceTransformer(EMBED_MODEL)
    dim = model.get_sentence_embedding_dimension()

    print("embedding...")
    vecs = model.encode(
        [c["text"] for c in chunks],
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    vecs = np.asarray(vecs, dtype="float32")

    INDEX.mkdir(parents=True, exist_ok=True)

    chunks_path = INDEX / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {chunks_path}")

    idx = faiss.IndexFlatIP(dim)
    idx.add(vecs)
    vectors_path = INDEX / "vectors.faiss"
    faiss.write_index(idx, str(vectors_path))
    print(f"wrote {vectors_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
