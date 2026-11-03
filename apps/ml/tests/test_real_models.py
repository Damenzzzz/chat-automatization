import os

import pytest

from app.config import Settings
from app.hub import build_embedder, build_reranker

pytestmark = pytest.mark.skipif(
    os.environ.get("ML_REAL_MODELS") != "1", reason="настоящие модели: ML_REAL_MODELS=1"
)

DOCS = [
    "Букет из 15 розовых пионов в крафтовой упаковке",
    "Букет из 25 красных роз Freedom 60 см",
    "Тормозные колодки передние Toyota Camry 70",
]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.mark.parametrize("backend", ["qwen3", "bge-m3"])
def test_real_embedder_ranks_relevant_docs(backend: str) -> None:
    embedder = build_embedder(Settings(ml_embedder=backend), "cpu")
    docs = embedder.encode(DOCS, "document")
    ru, kk = embedder.encode(["есть розовые пионы?", "қызыл раушан гүлдері бар ма?"], "query")

    assert embedder.dim == 1024 and len(docs[0]) == 1024
    assert max(range(3), key=lambda i: _dot(ru, docs[i])) == 0
    assert max(range(3), key=lambda i: _dot(kk, docs[i])) == 1


@pytest.mark.parametrize("backend", ["qwen3", "bge-m3"])
def test_real_reranker_prefers_relevant_doc(backend: str) -> None:
    reranker = build_reranker(Settings(ml_reranker=backend), "cpu")
    scores = reranker.score("розовые пионы на день рождения", DOCS)

    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[0] > 0.5 > scores[2]
    assert scores[0] > scores[1] > scores[2]
