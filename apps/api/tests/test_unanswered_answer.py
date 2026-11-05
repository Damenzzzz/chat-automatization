import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.catalog.reindex import reindex_tenant
from app.db.session import tenant_session
from app.llm.fake import FakeLLM
from app.search import search_kb
from tests.agent_helpers import make_agent, make_conversation
from tests.conftest import FakeSender, RecordingQueue, create_user, login
from tests.fake_ml import FakeML

QUESTION = "Можно ли оплатить букет через Kaspi Red?"
ANSWER = "Да, принимаем Kaspi Red на сумму от 30 000 ₸ при заказе онлайн."


async def _question(
    engine: AsyncEngine, tenant_id: uuid.UUID, value: str = QUESTION, bot_answer: str = "уточню"
) -> uuid.UUID:
    async with engine.begin() as conn:
        result: uuid.UUID = await conn.scalar(
            text(
                "INSERT INTO unanswered (tenant_id, question, answer) VALUES (:t, :q, :a)"
                " RETURNING id"
            ),
            {"t": tenant_id, "q": value, "a": bot_answer},
        )
    return result


async def _row(engine: AsyncEngine, question_id: uuid.UUID) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT answer, resolved_at FROM unanswered WHERE id = :i"),
                {"i": question_id},
            )
        ).one()


async def test_answer_becomes_searchable_knowledge(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, queue: RecordingQueue
) -> None:
    question_id = await _question(owner_engine, owner)

    response = await client.post(f"/unanswered/{question_id}/answer", json={"answer": ANSWER})

    assert response.status_code == 201, response.text
    assert response.json()["resolved"] == 1
    row = await _row(owner_engine, question_id)
    assert row.answer == ANSWER
    assert row.resolved_at is not None
    assert ("reindex_embeddings", (str(owner),)) in queue.jobs

    async with tenant_session(owner) as session:
        found = await search_kb(session, "оплата Kaspi Red", record=False)
    assert [hit.text for hit in found.items] == [ANSWER]
    assert found.items[0].title == QUESTION
    assert found.items[0].source == "unanswered"


async def test_answer_is_indexed_for_vector_search(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    question_id = await _question(owner_engine, owner)
    created = await client.post(f"/unanswered/{question_id}/answer", json={"answer": ANSWER})
    chunk_id = created.json()["kb_chunk_id"]

    async def stale() -> tuple[bool, bool]:
        async with owner_engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT embedding_stale, embedding IS NOT NULL AS has_vector"
                        " FROM kb_chunks WHERE id = :i"
                    ),
                    {"i": chunk_id},
                )
            ).one()
        return row.embedding_stale, row.has_vector

    assert await stale() == (True, False)
    stats = await reindex_tenant(owner, FakeML())
    assert stats.kb_chunks == 1
    assert await stale() == (False, True)
    ml = FakeML()
    async with tenant_session(owner) as session:
        found = await search_kb(session, "Kaspi Red букет", ml=ml, record=False)
    assert found.items[0].id == uuid.UUID(chunk_id)


async def test_bot_uses_answer_on_next_question(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    question_id = await _question(owner_engine, owner)
    await client.post(f"/unanswered/{question_id}/answer", json={"answer": ANSWER})
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO ledger (tenant_id, type, amount_kzt) VALUES (:t, 'topup', 5000)"),
            {"t": owner},
        )
    _, conversation_id = await make_conversation(owner_engine, owner)
    llm = FakeLLM(
        [
            Understanding(
                lang="ru", intent="policy", complexity="low", search_query="оплата Kaspi Red"
            ),
            "Да, Kaspi Red принимаем от 30 000 ₸.",
        ]
    )
    agent, _ = await make_agent(llm=llm, ml=FakeML())

    turn = await agent.run(tenant_id=owner, conversation_id=conversation_id, text="Есть Kaspi Red?")

    assert ANSWER in llm.calls[1].messages[-1].text
    assert turn.reply == "Да, Kaspi Red принимаем от 30 000 ₸."
    assert next(s for s in turn.trace if s["node"] == "guard_out")["ok"] is True


async def test_group_is_resolved_with_one_answer(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    main = await _question(owner_engine, owner)
    similar = await _question(owner_engine, owner, "Kaspi Red есть?")
    separate = await _question(owner_engine, owner, "Работаете в воскресенье?")

    response = await client.post(
        f"/unanswered/{main}/answer", json={"answer": ANSWER, "also_resolve": [str(similar)]}
    )

    assert response.json()["resolved"] == 2
    assert (await _row(owner_engine, similar)).resolved_at is not None
    assert (await _row(owner_engine, separate)).resolved_at is None
    async with owner_engine.connect() as conn:
        chunks = await conn.scalar(
            text("SELECT count(*) FROM kb_chunks WHERE tenant_id = :t"), {"t": owner}
        )
    assert chunks == 1


async def test_second_answer_is_refused(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    question_id = await _question(owner_engine, owner)
    url = f"/unanswered/{question_id}/answer"
    assert (await client.post(url, json={"answer": ANSWER})).status_code == 201
    again = await client.post(url, json={"answer": "другое"})
    assert again.status_code == 409
    assert (await _row(owner_engine, question_id)).answer == ANSWER


async def test_foreign_question_cannot_be_answered_or_resolved(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    foreign = await _question(owner_engine, other)
    response = await client.post(f"/unanswered/{foreign}/answer", json={"answer": ANSWER})
    assert response.status_code == 404

    own = await _question(owner_engine, owner)
    mixed = await client.post(
        f"/unanswered/{own}/answer", json={"answer": ANSWER, "also_resolve": [str(foreign)]}
    )
    assert mixed.json()["resolved"] == 1
    assert (await _row(owner_engine, foreign)).resolved_at is None


async def test_unknown_question_is_404(client: AsyncClient, owner: uuid.UUID) -> None:
    response = await client.post(f"/unanswered/{uuid.uuid4()}/answer", json={"answer": ANSWER})
    assert response.status_code == 404


@pytest.mark.parametrize("answer", ["", "   ", "я" * 4001])
async def test_invalid_answer_is_rejected(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, answer: str
) -> None:
    question_id = await _question(owner_engine, owner)
    response = await client.post(f"/unanswered/{question_id}/answer", json={"answer": answer})
    assert response.status_code == 422
    assert (await _row(owner_engine, question_id)).resolved_at is None


async def test_manager_can_answer(
    client: AsyncClient, owner: uuid.UUID, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    question_id = await _question(owner_engine, owner)
    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)
    response = await client.post(f"/unanswered/{question_id}/answer", json={"answer": ANSWER})
    assert response.status_code == 201
