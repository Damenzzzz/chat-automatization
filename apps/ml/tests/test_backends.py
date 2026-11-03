from typing import Any

import pytest

from app import hub
from app.config import QUERY_TASK, Settings


class Capture:
    def __init__(self, name: str, **kwargs: Any) -> None:
        self.name, self.kwargs, self.dim = name, kwargs, 1024


@pytest.fixture(autouse=True)
def capture(monkeypatch: pytest.MonkeyPatch) -> None:
    for attr in ("SentenceTransformerEmbedder", "Qwen3Reranker", "CrossEncoderReranker"):
        monkeypatch.setattr(hub, attr, Capture)


def test_qwen3_backends() -> None:
    settings = Settings(ml_embedder="qwen3", ml_reranker="qwen3")
    embedder: Any = hub.build_embedder(settings, "cpu")
    reranker: Any = hub.build_reranker(settings, "cpu")

    assert embedder.name == "Qwen/Qwen3-Embedding-0.6B"
    assert embedder.kwargs["query_prompt"] == f"Instruct: {QUERY_TASK}\nQuery:"
    assert embedder.kwargs["padding_side"] == "left"
    assert reranker.name == "Qwen/Qwen3-Reranker-0.6B"
    assert reranker.kwargs["instruction"] == QUERY_TASK


def test_bge_m3_backends_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ML_EMBEDDER", "bge-m3")
    monkeypatch.setenv("ML_RERANKER", "bge-m3")
    settings = Settings()
    embedder: Any = hub.build_embedder(settings, "cpu")
    reranker: Any = hub.build_reranker(settings, "cpu")

    assert embedder.name == "BAAI/bge-m3"
    assert embedder.kwargs["query_prompt"] is None
    assert reranker.name == "BAAI/bge-reranker-v2-m3"
    assert reranker.kwargs["max_tokens"] == 512
