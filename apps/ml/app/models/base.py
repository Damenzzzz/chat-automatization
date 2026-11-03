from typing import Any, Literal, Protocol

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


def resolve_dtype(requested: str, device: str) -> Any:
    import torch

    if requested == "auto":
        requested = "float32" if device == "cpu" else "bfloat16"
    return getattr(torch, requested)
