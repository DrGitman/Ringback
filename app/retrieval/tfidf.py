import pickle
from pathlib import Path
from typing import List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from .base import Hit
from .chunker import Chunk

INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "kb" / ".index"


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
        corpus = [f"{c.heading}\n{c.text}" for c in chunks]
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
        q = self.vectorizer.transform([query])
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
