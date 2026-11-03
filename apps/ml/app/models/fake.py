import hashlib
import math
import random

from app.models.base import EMBEDDING_DIM, Kind


class FakeEmbedder:
    name = "fake-embedder"
    dim = EMBEDDING_DIM

    def encode(self, texts: list[str], kind: Kind) -> list[list[float]]:
        vectors = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(f"{kind}:{text}".encode()).digest()[:8], "big")
            rng = random.Random(seed)  # noqa: S311
            vec = [rng.gauss(0, 1) for _ in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in vec))
            vectors.append([v / norm for v in vec])
        return vectors


class FakeReranker:
    name = "fake-reranker"

    def score(self, query: str, documents: list[str]) -> list[float]:
        words = set(query.lower().split())
        return [len(words & set(doc.lower().split())) / (len(words) or 1) for doc in documents]
