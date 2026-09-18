"""Build the corpus index.

Reads corpus/manifest.json, processes each source whose `file` is present in
corpus/studio/ or corpus/raw/, and writes:

    corpus/index/chunks.jsonl   — one JSON object per chunk
    corpus/index/vectors.faiss  — FAISS index, parallel order to chunks.jsonl

Run:
    python ingest.py

Source files may be plain text (.txt, .md) or PDF (.pdf). PDF text is
extracted with pypdf. A scanned PDF with no text layer yields nothing and
says so — OCR it elsewhere first, since this does not bundle an OCR engine.

The chunker has two modes selected by the manifest entry's `type`:
    "prose"      — paragraph chunks; long paragraphs split at sentence
                   boundaries to stay under the embed model's window.
    "chaptered"  — one chunk per detected chapter or section header, plus
                   any front matter as prose chunks. Geddes's books are
                   long and argue by chapter; keeping a chapter's text
                   together gives retrieval a coherent unit.

OCR cleanup is intentionally light — per-source tuning is expected. Re-run
this script after any change to the manifest or to either corpus directory.
"""

import json
import re
import sys
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus"
RAW = CORPUS / "raw"
STUDIO = CORPUS / "studio"
INDEX = CORPUS / "index"
MANIFEST = CORPUS / "manifest.json"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# PDFs only. A scanned PDF with no text layer extracts to nothing or a
# few stray characters, and would otherwise be indexed as a real but
# useless source; any genuine page of prose clears this comfortably.
# Text files are not held to it — a short studio note is a deliberate
# short note, not a failed read.
MIN_PDF_WORDS = 20

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


def source_path(filename: str) -> Path | None:
    """Locate a manifest entry's text, or None if it isn't here yet.

    Two directories, because the texts have two provenances:

      corpus/studio/  material that belongs to the repo — teaching notes,
                      briefs, anything with no download_url. Tracked in git.
      corpus/raw/     everything fetched from the manifest. Gitignored and
                      rebuilt per install, so a clone stays small.

    studio wins on a name clash, since a local edit should beat a
    re-download.
    """
    for directory in (STUDIO, RAW):
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def read_source(path: Path) -> str:
    """Return a source file's text. Handles .pdf as well as .txt / .md.

    A PDF's text layer is what is extracted — a scan with no text layer
    returns almost nothing, which `build_chunks` reports rather than
    passing on as an empty source. There is no OCR here on purpose:
    Geddes-Ghost carried pytesseract and the system binary it needs, and
    that is a heavy dependency for a case better handled by OCRing the
    file once, outside this tool.
    """
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError(
                f"{path.name} is a PDF but pypdf is not installed — "
                f"`pip install -r requirements.txt`"
            ) from exc
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:
                print(f"    page skipped in {path.name}: {exc}", file=sys.stderr)
        # Pages are separated by a blank line so the paragraph chunker
        # does not run the last line of one page into the first of the
        # next.
        return "\n\n".join(pages)

    return path.read_text(encoding="utf-8", errors="replace")


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
        path = source_path(src["file"])
        if path is None:
            print(f"  skip {src['id']}: {src['file']} not found "
                  f"(run fetch_corpus.py)", file=sys.stderr)
            continue

        # One unreadable source should cost its own chunks, not the whole
        # index. Before this, a PDF raised UnicodeDecodeError out of
        # read_text and took the entire run down with it.
        try:
            text = clean_ocr(read_source(path))
        except Exception as exc:
            print(f"  skip {src['id']}: could not read {path.name} — {exc}",
                  file=sys.stderr)
            continue

        if path.suffix.lower() == ".pdf" and len(text.split()) < MIN_PDF_WORDS:
            print(f"  skip {src['id']}: {path.name} yielded only "
                  f"{len(text.split())} words — a scan with no text layer? "
                  f"OCR it before adding it", file=sys.stderr)
            continue

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
