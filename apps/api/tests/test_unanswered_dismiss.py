import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import FakeSender, RecordingQueue, create_user, login
from tests.test_unanswered_answer import _question, _row


async def _kb_chunks(engine: AsyncEngine, tenant_id: uuid.UUID) -> int:
    async with engine.connect() as conn:
        value: int = await conn.scalar(
            text("SELECT count(*) FROM kb_chunks WHERE tenant_id = :t"), {"t": tenant_id}
        )
    return value


async def test_dismissed_group_leaves_list_without_knowledge(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, queue: RecordingQueue
) -> None:
    main = await _question(owner_engine, owner, "ок спасибо")
    similar = await _question(owner_engine, owner, "спасибо")
    separate = await _question(owner_engine, owner, "Работаете в воскресенье?")

    response = await client.post(
        f"/unanswered/{main}/dismiss", json={"also_resolve": [str(similar)]}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"resolved": 2}
    for question_id in (main, similar):
        row = await _row(owner_engine, question_id)
        assert row.resolved_at is not None
        assert row.answer == "уточню"
    assert (await _row(owner_engine, separate)).resolved_at is None
    assert await _kb_chunks(owner_engine, owner) == 0
    assert not [job for job in queue.jobs if job[0] == "reindex_embeddings"]


async def test_dismiss_twice_is_conflict(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    question_id = await _question(owner_engine, owner)
    url = f"/unanswered/{question_id}/dismiss"
    assert (await client.post(url, json={})).status_code == 200
    assert (await client.post(url, json={})).status_code == 409
    answer = await client.post(f"/unanswered/{question_id}/answer", json={"answer": "Да"})
    assert answer.status_code == 409


async def test_foreign_questions_are_untouched(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    foreign = await _question(owner_engine, other)

    assert (await client.post(f"/unanswered/{foreign}/dismiss", json={})).status_code == 404
    own = await _question(owner_engine, owner)
    mixed = await client.post(f"/unanswered/{own}/dismiss", json={"also_resolve": [str(foreign)]})
    assert mixed.json() == {"resolved": 1}
    assert (await _row(owner_engine, foreign)).resolved_at is None
    unknown = await client.post(f"/unanswered/{uuid.uuid4()}/dismiss", json={})
    assert unknown.status_code == 404


async def test_manager_can_dismiss(
    client: AsyncClient, owner: uuid.UUID, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    question_id = await _question(owner_engine, owner)
    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)
    response = await client.post(f"/unanswered/{question_id}/dismiss", json={})
    assert response.status_code == 200
