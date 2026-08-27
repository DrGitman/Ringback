"""Pre-call retrieval: grounds the task string in real KB documents instead
of an agent's memory. Retrieval happens once, before dispatch — CALL-E has
no hook to query anything mid-call — so the briefing has to be generous (a
handful of chunks) and honest about gaps (below threshold means "say you
don't know," not "guess").

Two framings, same search underneath:

- build_briefing() — primary. Used when there's no student record to
  answer from (the "other" intent, or a record-backed intent with no
  student number). The reference material IS the answer.
- build_supplementary_briefing() — secondary. Used alongside a student
  record (proof_of_registration / subject_cancellation). The record is
  the answer for anything it covers; this is background for anything it
  doesn't — e.g. a proof-of-registration caller who also asks *where* the
  Cashier's Office is, which lives in fees-and-payment.md, not their
  record. The record always wins if the two ever disagree.
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

from .base import Hit, Retriever
from .chunker import Chunk, chunk_file
from .tfidf import TfidfRetriever

# Tuned against scripts/tune_threshold.py on the nine-file nust KB: known
# in-scope queries scored 0.106-0.220, known out-of-scope scored 0.000-0.091.
# 0.095 sits in that gap. Below this, the KB genuinely doesn't cover the
# question — inject nothing rather than a weak match. Re-run the tuning
# script and adjust this after any real change to the KB's size or content.
TFIDF_MIN_SCORE = 0.095

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


def _search(query: str, retriever: Retriever) -> Tuple[List[Hit], List[dict]]:
    hits = [h for h in retriever.search(query, k=4) if h.score >= TFIDF_MIN_SCORE]
    provenance = [
        {
            "chunk_id": h.chunk.id,
            "source": h.chunk.source,
            "heading": h.chunk.heading,
            "score": round(h.score, 3),
            "office": h.chunk.office,
        }
        for h in hits
    ]
    return hits, provenance


def _blocks(hits: List[Hit]) -> str:
    return "\n\n".join(f"[{h.chunk.heading}]\n{h.chunk.text}" for h in hits)


def build_briefing(
    query: str, retriever: Retriever, tenant: dict
) -> Tuple[str, List[dict], bool]:
    """Returns (briefing_text, provenance, no_kb_coverage). Below threshold
    means genuinely no coverage: empty briefing, empty provenance, True —
    the right outcome on a phone call is "I don't know" over a weak guess.
    """
    hits, provenance = _search(query, retriever)
    if not hits:
        return "", [], True

    briefing = (
        f"Reference information from official {tenant['short_name']} documents. "
        "You may use this to answer:\n"
        f"---\n{_blocks(hits)}\n---\n"
        "Answer only from this reference and the caller's own record. If the "
        "answer is not in the reference, say plainly that you don't have that "
        "information and that the right office will follow up. Never guess at "
        "dates, amounts, or requirements."
    )
    return briefing, provenance, False


def build_supplementary_briefing(
    query: str, retriever: Retriever, tenant: dict
) -> Tuple[str, List[dict], bool]:
    """Same search, background framing. No hit here is normal — it just
    means the record already covers the question — so the caller should
    treat a False/empty return as "nothing extra," not "coverage failed."
    """
    hits, provenance = _search(query, retriever)
    if not hits:
        return "", [], False

    briefing = (
        f"Additional background from official {tenant['short_name']} documents, in "
        "case they ask something their record doesn't cover:\n"
        f"---\n{_blocks(hits)}\n---\n"
        "Their record above always takes precedence over this if the two ever "
        "disagree. Do not use this to override or contradict what their record says."
    )
    return briefing, provenance, False
