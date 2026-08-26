"""Pre-call retrieval: grounds the "other" intent's task string in real KB
documents instead of an agent's memory. Retrieval happens once, before
dispatch — CALL-E has no hook to query anything mid-call — so the
briefing has to be generous (a handful of chunks) and honest about gaps
(below threshold means "say you don't know," not "guess").
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

from .base import Hit, Retriever
from .chunker import Chunk, chunk_file
from .tfidf import TfidfRetriever

# Tuned against scripts/tune_threshold.py. Below this, the KB genuinely
# doesn't cover the question — inject nothing rather than a weak match.
TFIDF_MIN_SCORE = 0.12

KB_ROOT = Path(__file__).resolve().parent.parent.parent / "kb"


def _load_chunks(tenant_id: str) -> List[Chunk]:
    folder = KB_ROOT / tenant_id
    chunks: List[Chunk] = []
    if folder.exists():
        for md in sorted(folder.glob("*.md")):
            chunks.extend(chunk_file(md, tenant_id))
    return chunks


@lru_cache
def get_retriever(tenant_id: str) -> Retriever:
    loaded = TfidfRetriever.load(tenant_id)
    if loaded is not None:
        return loaded
    retriever = TfidfRetriever()
    retriever.build(_load_chunks(tenant_id))
    return retriever


def build_briefing(
    query: str, retriever: Retriever, tenant: dict
) -> Tuple[str, List[dict], bool]:
    """Returns (briefing_text, provenance, no_kb_coverage).

    provenance is a list of {chunk_id, source, heading, score, office},
    suitable for storing on the case and rendering on the dashboard so a
    grounded answer is provably grounded, not just claimed to be.
    """
    hits: List[Hit] = retriever.search(query, k=4)
    strong = [h for h in hits if h.score >= TFIDF_MIN_SCORE]

    if not strong:
        return "", [], True

    blocks = []
    provenance = []
    for h in strong:
        blocks.append(f"[{h.chunk.heading}]\n{h.chunk.text}")
        provenance.append(
            {
                "chunk_id": h.chunk.id,
                "source": h.chunk.source,
                "heading": h.chunk.heading,
                "score": round(h.score, 3),
                "office": h.chunk.office,
            }
        )

    briefing = (
        f"Reference information from official {tenant['short_name']} documents. "
        "You may use this to answer:\n"
        "---\n" + "\n\n".join(blocks) + "\n---\n"
        "Answer only from this reference and the caller's own record. If the "
        "answer is not in the reference, say plainly that you don't have that "
        "information and that the right office will follow up. Never guess at "
        "dates, amounts, or requirements."
    )
    return briefing, provenance, False
