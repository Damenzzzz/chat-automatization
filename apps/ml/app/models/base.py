from typing import Literal, Protocol

Kind = Literal["query", "document"]
EMBEDDING_DIM = 1024


class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: list[str], kind: Kind) -> list[list[float]]: ...


class Reranker(Protocol):
    name: str

    def score(self, query: str, documents: list[str]) -> list[float]: ...


def resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    import torch

    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
