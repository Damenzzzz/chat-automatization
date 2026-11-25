import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from app.core.config import get_settings

Reason = Literal["vector", "fts", "sku"]


class SearchML(Protocol):
    async def embed(
        self, texts: list[str], kind: Literal["query", "document"]
    ) -> list[list[float]]: ...

    async def rerank(self, query: str, documents: list[str]) -> list[float]: ...


@dataclass(frozen=True)
class ProductFilters:
    price_min: int | None = None
    price_max: int | None = None
    in_stock: bool = False
    category: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, False)}


@dataclass(frozen=True)
class ProductHit:
    id: uuid.UUID
    sku: str | None
    name: str
    category: str | None
    price: int | None
    stock: int | None
    reasons: tuple[Reason, ...]
    ranks: dict[str, int]
    rrf: float
    score: float | None = None
    description: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    exact: bool = False

    @property
    def weak(self) -> bool:
        """Реранкер почти уверен, что товар не про запрос (точный артикул не в счёт)."""
        if self.exact or self.score is None:
            return False
        return self.score < get_settings().search_weak_score

    @property
    def in_stock(self) -> bool:
        return self.stock is None or self.stock > 0


@dataclass(frozen=True)
class KbHit:
    id: uuid.UUID
    source: str
    title: str | None
    text: str
    reasons: tuple[Reason, ...]
    ranks: dict[str, int]
    rrf: float
    score: float | None = None


@dataclass
class SearchResult[T]:
    items: list[T]
    lang: str | None
    latency_ms: int
    candidates: dict[str, int] = field(default_factory=dict)
