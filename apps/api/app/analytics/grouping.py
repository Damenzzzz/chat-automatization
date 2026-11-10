import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

import structlog

from app.mlclient import MLError

log = structlog.get_logger()

SPACES = re.compile(r"\s+")
Method = Literal["embeddings", "text"]


class Embeds(Protocol):
    async def embed(
        self, texts: list[str], kind: Literal["query", "document"]
    ) -> list[list[float]]: ...


@dataclass(frozen=True)
class Question:
    id: UUID
    text: str
    created_at: datetime


@dataclass
class Group:
    question: str
    ids: list[UUID] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    last_asked_at: datetime | None = None

    @property
    def count(self) -> int:
        return len(self.ids)

    def add(self, item: Question) -> None:
        self.ids.append(item.id)
        if item.text not in self.examples:
            self.examples.append(item.text)
        if self.last_asked_at is None or item.created_at > self.last_asked_at:
            self.last_asked_at = item.created_at


def normalize(value: str) -> str:
    return SPACES.sub(" ", value).strip().casefold()


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def group_by_vectors(
    questions: Sequence[Question], vectors: Sequence[Sequence[float]], threshold: float
) -> list[Group]:
    # сравниваем с первым вопросом группы: иначе цепочки А≈Б≈В склеят разные вопросы
    groups: list[tuple[Group, Sequence[float]]] = []
    for item, vector in zip(questions, vectors, strict=True):
        scored = [(_dot(vector, head), group) for group, head in groups]
        best = max(scored, key=lambda pair: pair[0], default=None)
        if best is not None and best[0] >= threshold:
            best[1].add(item)
            continue
        group = Group(item.text)
        group.add(item)
        groups.append((group, vector))
    return [group for group, _ in groups]


def group_by_text(questions: Sequence[Question]) -> list[Group]:
    groups: dict[str, Group] = {}
    for item in questions:
        groups.setdefault(normalize(item.text), Group(item.text)).add(item)
    return list(groups.values())


async def group_questions(
    questions: Sequence[Question], ml: Embeds, threshold: float
) -> tuple[list[Group], Method]:
    if not questions:
        return [], "embeddings"
    method: Method = "embeddings"
    try:
        vectors = await ml.embed([q.text for q in questions], "query")
        groups = await asyncio.to_thread(group_by_vectors, questions, vectors, threshold)
    except MLError as exc:
        log.warning("analytics.grouping_without_embeddings", error=str(exc))
        groups, method = group_by_text(questions), "text"
    groups.sort(key=lambda g: (-g.count, g.question))
    return groups, method
