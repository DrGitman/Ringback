import pickle
import re
from pathlib import Path
from typing import List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from .base import Hit
from .chunker import Chunk

INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "kb" / ".index"

# Word-boundary tokenization splits "gferis@nust.na" into "gferis", "nust",
# "na" - so a chunk with a dozen @nust.na addresses racks up "nust" far more
# than a chunk that just mentions NUST in prose, and wins queries it has no
# real business winning. Mask contact details out of the text used for
# matching (never out of chunk.text itself, which is what's actually sent
# to CALL-E) so a directory-style KB file can't out-vote relevant prose on
# term frequency alone.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"\+?\d[\d ]{6,}\d")


def _mask_contact_details(text: str) -> str:
    return _PHONE_RE.sub(" ", _EMAIL_RE.sub(" ", text))


class TfidfRetriever:
    def __init__(self) -> None:
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.matrix = None
        self.chunks: List[Chunk] = []

    def build(self, chunks: List[Chunk]) -> None:
        self.chunks = chunks
        if not chunks:
            self.vectorizer = None
            self.matrix = None
            return
        corpus = [_mask_contact_details(f"{c.heading}\n{c.text}") for c in chunks]
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            sublinear_tf=True,
            strip_accents="unicode",
            lowercase=True,
            stop_words="english",
            min_df=1,
        )
        self.matrix = self.vectorizer.fit_transform(corpus)

    def search(self, query: str, k: int = 4) -> List[Hit]:
        if self.vectorizer is None or self.matrix is None:
            return []
        q = self.vectorizer.transform([_mask_contact_details(query)])
        scores = linear_kernel(q, self.matrix).flatten()
        top = scores.argsort()[::-1][:k]
        return [Hit(chunk=self.chunks[i], score=float(scores[i])) for i in top if scores[i] > 0]

    def save(self, tenant: str) -> None:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        with open(INDEX_DIR / f"{tenant}.pkl", "wb") as f:
            pickle.dump(
                {"vectorizer": self.vectorizer, "matrix": self.matrix, "chunks": self.chunks}, f
            )

    @classmethod
    def load(cls, tenant: str) -> Optional["TfidfRetriever"]:
        path = INDEX_DIR / f"{tenant}.pkl"
        if not path.exists():
            return None
        inst = cls()
        with open(path, "rb") as f:
            data = pickle.load(f)
        inst.vectorizer = data["vectorizer"]
        inst.matrix = data["matrix"]
        inst.chunks = data["chunks"]
        return inst
