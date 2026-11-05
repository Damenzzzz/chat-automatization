import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.analytics.grouping import Question, group_by_text, group_by_vectors, group_questions
from app.mlclient import MLError, get_ml_client
from tests.analytics_helpers import at, dialog
from tests.conftest import create_user

DAY = date(2026, 10, 10)
RANGE = {"date_from": "2026-10-10", "date_to": "2026-10-16"}
NOW = datetime(2026, 10, 10, tzinfo=UTC)


def _question(value: str) -> Question:
    return Question(uuid.uuid4(), value, NOW)


class VectorML:
    """Вектор задан текстом вопроса, чтобы похожесть в тесте была явной."""

    def __init__(self, vectors: dict[str, list[float]], *, fail: bool = False) -> None:
        self.vectors = vectors
        self.fail = fail
        self.kinds: list[str] = []

    async def embed(self, texts: list[str], kind: Any) -> list[list[float]]:
        if self.fail:
            raise MLError("down")
        self.kinds.append(kind)
        return [self.vectors[t] for t in texts]

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.0] * len(documents)


async def _search(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    query: str,
    *,
    in_stock: bool | None = True,
    results: int = 3,
    kind: str = "product",
    moment: datetime | None = None,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO search_log (tenant_id, query, kind, result_count, has_in_stock,"
                " created_at) VALUES (:t, :q, :k, :r, :s, :at)"
            ),
            {
                "t": tenant_id,
                "q": query,
                "k": kind,
                "r": results,
                "s": in_stock,
                "at": moment or at(DAY),
            },
        )


async def _unanswered(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    question: str,
    *,
    conversation_id: uuid.UUID | None = None,
    resolved: bool = False,
    moment: datetime | None = None,
) -> uuid.UUID:
    async with engine.begin() as conn:
        value: uuid.UUID = await conn.scalar(
            text(
                "INSERT INTO unanswered (tenant_id, conversation_id, question, resolved_at,"
                " created_at) VALUES (:t, :c, :q, :r, :at) RETURNING id"
            ),
            {
                "t": tenant_id,
                "c": conversation_id,
                "q": question,
                "r": NOW if resolved else None,
                "at": moment or at(DAY),
            },
        )
    return value


async def test_top_queries_group_case_and_spaces_and_report_stock(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    for query in ("Белые пионы", "белые пионы ", "БЕЛЫЕ ПИОНЫ"):
        await _search(owner_engine, owner, query, in_stock=False)
    await _search(owner_engine, owner, "белые пионы", in_stock=True)
    await _search(owner_engine, owner, "тюльпаны", in_stock=False)
    await _search(owner_engine, owner, "кактус", in_stock=None, results=0)

    response = await client.get("/analytics/top_queries", params=RANGE)

    assert response.status_code == 200, response.text
    assert response.json() == [
        {"query": "белые пионы", "count": 4, "in_stock": True, "found": True},
        {"query": "кактус", "count": 1, "in_stock": None, "found": False},
        {"query": "тюльпаны", "count": 1, "in_stock": False, "found": True},
    ]


async def test_top_queries_respect_period_kind_limit_and_tenant(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    await _search(owner_engine, owner, "в периоде")
    await _search(owner_engine, owner, "ещё один")
    await _search(owner_engine, owner, "раньше", moment=at(date(2026, 10, 9)))
    await _search(owner_engine, owner, "доставка", kind="kb")
    await _search(owner_engine, other, "чужой")

    body = (await client.get("/analytics/top_queries", params=RANGE)).json()
    assert {item["query"] for item in body} == {"в периоде", "ещё один"}
    limited = await client.get("/analytics/top_queries", params={**RANGE, "limit": 1})
    assert len(limited.json()) == 1


def test_similar_vectors_group_and_different_stay_apart() -> None:
    a, b, c = _question("а"), _question("б"), _question("в")
    groups = group_by_vectors([a, b, c], [[1.0, 0.0], [0.9, 0.436], [0.0, 1.0]], 0.85)
    assert [g.ids for g in groups] == [[a.id, b.id], [c.id]]
    assert groups[0].question == "а"
    assert groups[0].examples == ["а", "б"]


def test_threshold_is_inclusive_boundary_not_chained() -> None:
    a, b, c = _question("а"), _question("б"), _question("в")
    vectors = [[1.0, 0.0], [0.9, 0.436], [0.62, 0.785]]
    groups = group_by_vectors([a, b, c], vectors, 0.85)
    assert [g.count for g in groups] == [2, 1]


def test_exact_threshold_joins_group() -> None:
    a, b = _question("а"), _question("б")
    assert len(group_by_vectors([a, b], [[1.0, 0.0], [0.85, 0.5268]], 0.85)) == 1


def test_text_fallback_groups_only_equal_questions() -> None:
    groups = group_by_text(
        [_question("Есть доставка?"), _question(" есть   ДОСТАВКА? "), _question("Есть скидка?")]
    )
    assert [g.count for g in groups] == [2, 1]


async def test_groups_sorted_by_count_and_empty_input_skips_ml() -> None:
    ml = VectorML({"а": [1.0, 0.0], "б": [0.0, 1.0], "в": [0.0, 1.0]})
    groups, method = await group_questions(
        [_question("а"), _question("б"), _question("в")], ml, 0.85
    )
    assert method == "embeddings"
    assert ml.kinds == ["query"]
    assert [g.question for g in groups] == ["б", "а"]
    assert groups[0].count == 2

    silent = VectorML({})
    assert await group_questions([], silent, 0.85) == ([], "embeddings")
    assert silent.kinds == []


@pytest.fixture
def similar_ml(app: FastAPI) -> VectorML:
    ml = VectorML(
        {
            "Доставляете в Астану?": [1.0, 0.0],
            "Есть доставка в Астану?": [0.95, 0.312],
            "Астанаға жеткізесіздер ме?": [0.9, 0.436],
            "Можно оплатить Kaspi?": [0.0, 1.0],
        }
    )
    app.dependency_overrides[get_ml_client] = lambda: ml
    return ml


async def test_unanswered_endpoint_groups_with_counter(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, similar_ml: VectorML
) -> None:
    ids = [
        await _unanswered(owner_engine, owner, "Доставляете в Астану?", moment=at(DAY, 12)),
        await _unanswered(owner_engine, owner, "Есть доставка в Астану?", moment=at(DAY, 11)),
        await _unanswered(owner_engine, owner, "Астанаға жеткізесіздер ме?", moment=at(DAY, 10)),
    ]
    kaspi = await _unanswered(owner_engine, owner, "Можно оплатить Kaspi?", moment=at(DAY, 9))

    response = await client.get("/analytics/unanswered", params=RANGE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grouped_by"] == "embeddings"
    assert body["total"] == 4
    assert [g["count"] for g in body["groups"]] == [3, 1]
    top = body["groups"][0]
    assert top["question"] == "Доставляете в Астану?"
    assert top["ids"] == [str(i) for i in ids]
    assert len(top["examples"]) == 3
    assert body["groups"][1]["ids"] == [str(kaspi)]


async def test_unanswered_falls_back_to_text_when_ml_is_down(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, app: FastAPI
) -> None:
    app.dependency_overrides[get_ml_client] = lambda: VectorML({}, fail=True)
    await _unanswered(owner_engine, owner, "Есть доставка?")
    await _unanswered(owner_engine, owner, "есть доставка?")
    response = await client.get("/analytics/unanswered", params=RANGE)
    assert response.status_code == 200
    assert response.json()["grouped_by"] == "text"
    assert [g["count"] for g in response.json()["groups"]] == [2]


async def test_unanswered_skips_resolved_sandbox_foreign_and_old(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, similar_ml: VectorML
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    sandbox = await dialog(owner_engine, owner, at(DAY), sandbox=True)
    await _unanswered(owner_engine, owner, "Можно оплатить Kaspi?", resolved=True)
    await _unanswered(owner_engine, owner, "Можно оплатить Kaspi?", conversation_id=sandbox)
    await _unanswered(owner_engine, other, "Можно оплатить Kaspi?")
    await _unanswered(owner_engine, owner, "Можно оплатить Kaspi?", moment=at(date(2026, 10, 1)))

    body = (await client.get("/analytics/unanswered", params=RANGE)).json()

    assert body["total"] == 0
    assert body["groups"] == []
