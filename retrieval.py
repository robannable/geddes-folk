"""Query-side retrieval. Loads the index once; `search` is called per query.

If the index hasn't been built yet (corpus/index/ missing), `Retriever.ready`
is False and `search` returns []. The app then runs voice-only, which is the
behaviour while the corpus is being prepared.

Two things differ from sharp-folk's version:

  - `user` scopes retrieval to a named student. Chunks from a `student`
    source belonging to someone else are excluded outright; the named
    user's own work is boosted. Geddes-Ghost did this with a filename
    substring test against TF-IDF scores; here it is a multiplier on the
    FAISS similarity, applied before the top-k cut.
  - `search` re-ranks rather than taking FAISS order directly, because
    the weights only mean something if they can reorder the result.
"""

import json
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from config import CONTEXT_WEIGHTS, RETRIEVE_K

ROOT = Path(__file__).parent
INDEX = ROOT / "corpus" / "index"
CHUNKS_PATH = INDEX / "chunks.jsonl"
VECTORS_PATH = INDEX / "vectors.faiss"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Over-fetch this many times k before filtering and re-ranking, so the
# voice and user filters still have enough left to return k.
OVERFETCH = 6


def _name_matches(user: str, owner: str) -> bool:
    """True if `user` plausibly names the owner of a student source.

    Deliberately loose — students type their name differently each
    session ("Rob", "rob annable", "Rob A"). A false positive surfaces
    one of their own files; a false negative hides their work from them,
    which is the worse error.
    """
    if not user or not owner:
        return False
    u = user.lower().strip()
    o = owner.lower().strip()
    if u == o:
        return True
    u_parts = [p for p in u.split() if p]
    o_parts = [p for p in o.split() if p]
    if not u_parts or not o_parts:
        return False
    if u_parts[0] == o_parts[0]:
        return True
    return any(p in o_parts for p in u_parts)


class Retriever:
    def __init__(self) -> None:
        if not (CHUNKS_PATH.exists() and VECTORS_PATH.exists()):
            self.chunks: list[dict] | None = None
            self.index = None
            self.model: SentenceTransformer | None = None
            return
        with CHUNKS_PATH.open(encoding="utf-8") as f:
            self.chunks = [json.loads(line) for line in f]
        self.index = faiss.read_index(str(VECTORS_PATH))
        self.model = SentenceTransformer(EMBED_MODEL)

    @property
    def ready(self) -> bool:
        return self.chunks is not None

    def _weight(self, chunk: dict, user: str) -> float:
        """Score multiplier for a chunk, or 0.0 to exclude it."""
        kind = chunk.get("weight_class", "general")
        if kind == "student":
            owner = chunk.get("owner") or ""
            if not _name_matches(user, owner):
                return 0.0  # someone else's work — not this user's to see
            return CONTEXT_WEIGHTS["student"]
        return CONTEXT_WEIGHTS.get(kind, CONTEXT_WEIGHTS["general"])

    def search(
        self,
        query: str,
        k: int = RETRIEVE_K,
        voice: str = "geddes",
        user: str = "",
    ) -> list[dict]:
        """Return up to k chunks matching `query`, filtered to `voice` and `user`.

        A chunk's `voice` field is one of "geddes", "librarian", or "both".
        A request for voice="geddes" sees chunks tagged "geddes" or "both";
        a request for voice="librarian" sees "librarian" or "both".
        """
        if not self.ready:
            return []
        vec = self.model.encode([query], normalize_embeddings=True)
        vec = np.asarray(vec, dtype="float32")
        scores, idxs = self.index.search(vec, min(k * OVERFETCH, len(self.chunks)))

        scored: list[tuple[float, dict]] = []
        for score, i in zip(scores[0], idxs[0]):
            if i < 0:
                continue
            c = self.chunks[i]
            cv = c.get("voice", "both")
            if cv != "both" and cv != voice:
                continue
            w = self._weight(c, user)
            if w == 0.0:
                continue
            scored.append((float(score) * w, c))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        out = []
        for weighted, c in scored[:k]:
            out.append({**c, "score": round(weighted, 4)})
        return out


def format_for_prompt(chunks: list[dict]) -> str:
    if not chunks:
        return ""
    parts: list[str] = []
    for c in chunks:
        header = f"[{c['source_title']}"
        if c.get("source_year"):
            header += f", {c['source_year']}"
        if c.get("section_title"):
            header += f" — \"{c['section_title']}\""
        header += "]"
        parts.append(f"{header}\n{c['text']}")
    return "\n\n".join(parts)
