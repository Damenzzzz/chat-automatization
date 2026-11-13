import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.channels.types import ChannelError, OutgoingMessage
from app.llm.fake import FakeLLM
from app.routers.conversations import get_outbound, stream_changes
from tests.agent_helpers import make_agent, make_conversation
from tests.channel_helpers import make_channel
from tests.conftest import FakeSender, create_user, login


class FakeOutbound:
    def __init__(self, error: str | None = None) -> None:
        self.sent: list[tuple[uuid.UUID, str, OutgoingMessage]] = []
        self.error = error

    async def send(self, channel_id: uuid.UUID, customer: str, message: OutgoingMessage) -> None:
        if self.error:
            raise ChannelError(self.error)
        self.sent.append((channel_id, customer, message))


async def _dialog(
    engine: AsyncEngine, tenant_id: uuid.UUID, mode: str = "bot", channel: bool = True
) -> uuid.UUID:
    _, conversation_id = await make_conversation(engine, tenant_id, mode=mode)
    channel_id = await make_channel(engine, tenant_id) if channel else None
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE conversations SET last_message_at = now(), channel_id = :c WHERE id = :i"),
            {"i": conversation_id, "c": channel_id},
        )
        await conn.execute(
            text(
                "INSERT INTO messages (tenant_id, conversation_id, role, content)"
                " VALUES (:t, :i, 'customer', 'Есть пионы?')"
            ),
            {"t": tenant_id, "i": conversation_id},
        )
    return conversation_id


async def _bot_message(
    engine: AsyncEngine, tenant_id: uuid.UUID, conversation_id: uuid.UUID, trace: dict[str, Any]
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO messages (tenant_id, conversation_id, role, content, trace)"
                " VALUES (:t, :i, 'bot', 'Есть', CAST(:trace AS jsonb))"
            ),
            {"t": tenant_id, "i": conversation_id, "trace": json.dumps(trace)},
        )


async def test_list_filters_and_counts(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    by_bot = await _dialog(owner_engine, owner)
    waiting = await _dialog(owner_engine, owner, mode="human")
    with_lead = await _dialog(owner_engine, owner)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO leads (tenant_id, conversation_id) VALUES (:t, :c)"),
            {"t": owner, "c": with_lead},
        )

    everything = (await client.get("/conversations")).json()
    assert {i["id"] for i in everything["items"]} == {str(by_bot), str(waiting), str(with_lead)}
    assert everything["counts"] == {
        "all": 3,
        "bot": 2,
        "human": 1,
        "leads": 1,
        "waiting": 1,
        "mine": 0,
        "unassigned": 1,
    }

    human = (await client.get("/conversations", params={"filter": "human"})).json()
    assert [i["id"] for i in human["items"]] == [str(waiting)]
    assert human["items"][0]["waiting"] is True
    assert human["items"][0]["preview"] == "Есть пионы?"

    leads = (await client.get("/conversations", params={"filter": "leads"})).json()
    assert [i["id"] for i in leads["items"]] == [str(with_lead)]
    assert leads["items"][0]["lead_status"] == "new"

    bot = (await client.get("/conversations", params={"filter": "bot"})).json()
    assert {i["id"] for i in bot["items"]} == {str(by_bot), str(with_lead)}


async def test_list_hides_sandbox_and_other_shops(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine)
    foreign = await _dialog(owner_engine, other)
    sandbox = await _dialog(owner_engine, owner)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE conversations SET sandbox = true WHERE id = :i"), {"i": sandbox}
        )

    assert (await client.get("/conversations")).json()["items"] == []
    assert (await client.get(f"/conversations/{foreign}")).status_code == 404


async def test_list_pages_by_time(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    for _ in range(3):
        await _dialog(owner_engine, owner, channel=False)

    first = (await client.get("/conversations", params={"limit": 2})).json()
    assert len(first["items"]) == 2
    rest = (
        await client.get("/conversations", params={"limit": 2, "before": first["next_before"]})
    ).json()
    assert len(rest["items"]) == 1
    assert rest["next_before"] is None


async def test_detail_shows_trace_cards_and_hides_costs(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    conversation_id = await _dialog(owner_engine, owner)
    async with owner_engine.begin() as conn:
        product_id = await conn.scalar(
            text(
                "INSERT INTO products (tenant_id, name, sku, price, stock, images)"
                " VALUES (:t, 'Пионы', 'P-1', 15000, 3, ARRAY['http://a/x.jpg','https://a/y.jpg'])"
                " RETURNING id"
            ),
            {"t": owner},
        )
    await _bot_message(
        owner_engine,
        owner,
        conversation_id,
        {
            "lang": "ru",
            "intent": "product",
            "steps": [
                {"node": "retrieve", "query": "пионы", "found": ["P-1"]},
                {"node": "send", "delivered": True, "products": [str(product_id)]},
            ],
            "llm_calls": [{"model": "m", "cost_usd": "0.1"}],
        },
    )

    body = (await client.get(f"/conversations/{conversation_id}")).json()

    assert [m["role"] for m in body["messages"]] == ["customer", "bot"]
    bot = body["messages"][1]
    assert bot["intent"] == "product"
    assert bot["delivered"] is True
    assert bot["steps"][0]["found"] == ["P-1"]
    assert bot["cards"] == [
        {
            "id": str(product_id),
            "name": "Пионы",
            "sku": "P-1",
            "price": 15000,
            "stock": 3,
            "image": "https://a/y.jpg",
        }
    ]
    assert "llm_calls" not in bot
    assert "cost_usd" not in bot


async def test_takeover_and_release_switch_mode(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    conversation_id = await _dialog(owner_engine, owner)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE conversations SET paused_reason = 'rate_limit' WHERE id = :i"),
            {"i": conversation_id},
        )

    taken = await client.post(f"/conversations/{conversation_id}/takeover")
    assert taken.status_code == 200, taken.text
    assert taken.json()["mode"] == "human"
    assert taken.json()["paused_reason"] is None

    released = await client.post(f"/conversations/{conversation_id}/release")
    assert released.json()["mode"] == "bot"


@pytest.fixture
def outbound(app: FastAPI) -> FakeOutbound:
    fake = FakeOutbound()
    app.dependency_overrides[get_outbound] = lambda: fake
    return fake


async def test_reply_sends_saves_and_takes_over(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, outbound: FakeOutbound
) -> None:
    conversation_id = await _dialog(owner_engine, owner)

    response = await client.post(
        f"/conversations/{conversation_id}/reply", json={"text": "  Привезём завтра "}
    )

    assert response.status_code == 201, response.text
    assert response.json()["role"] == "manager"
    assert response.json()["delivered"] is True
    assert [m[2].text for m in outbound.sent] == ["Привезём завтра"]
    detail = (await client.get(f"/conversations/{conversation_id}")).json()
    assert detail["mode"] == "human"
    assert detail["waiting"] is False
    assert detail["messages"][-1]["content"] == "Привезём завтра"


async def test_failed_send_keeps_message_undelivered(
    client: AsyncClient, app: FastAPI, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    app.dependency_overrides[get_outbound] = lambda: FakeOutbound("окно 24 часа закрыто")
    conversation_id = await _dialog(owner_engine, owner)

    response = await client.post(f"/conversations/{conversation_id}/reply", json={"text": "Алло"})

    assert response.status_code == 201
    assert response.json()["delivered"] is False
    assert response.json()["steps"][0]["error"] == "окно 24 часа закрыто"


async def test_reply_requires_channel_and_text(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, outbound: FakeOutbound
) -> None:
    no_channel = await _dialog(owner_engine, owner, channel=False)
    response = await client.post(f"/conversations/{no_channel}/reply", json={"text": "Алло"})
    assert response.status_code == 409

    with_channel = await _dialog(owner_engine, owner)
    blank = await client.post(f"/conversations/{with_channel}/reply", json={"text": "   "})
    assert blank.status_code == 422
    assert outbound.sent == []


async def test_bot_remembers_manager_reply_after_release(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, outbound: FakeOutbound
) -> None:
    conversation_id = await _dialog(owner_engine, owner)
    llm = FakeLLM(
        [
            Understanding(lang="ru", intent="smalltalk", complexity="low"),
            "Здравствуйте",
            Understanding(lang="ru", intent="smalltalk", complexity="low"),
            "Да, завтра",
        ]
    )
    agent, _ = await make_agent(llm)
    await agent.run(tenant_id=owner, conversation_id=conversation_id, text="Привет", sandbox=True)

    await client.post(f"/conversations/{conversation_id}/reply", json={"text": "Привезём завтра"})
    await client.post(f"/conversations/{conversation_id}/release")
    await agent.run(tenant_id=owner, conversation_id=conversation_id, text="Точно?", sandbox=True)

    prompt = " ".join(str(m.text) for m in llm.calls[-1].messages)
    assert "Привезём завтра" in prompt


async def test_stream_reports_changed_conversation(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    conversation_id = await _dialog(owner_engine, owner)
    polls = 0

    async def disconnected() -> bool:
        nonlocal polls
        polls += 1
        return polls > 3

    stream = stream_changes(owner, disconnected, poll_seconds=0.01, max_seconds=5)
    assert await anext(stream) == "retry: 3000\n\n"
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE conversations SET mode = 'human' WHERE id = :i"), {"i": conversation_id}
        )
    event = await anext(stream)

    assert event.startswith("event: change")
    assert str(conversation_id) in event
    await stream.aclose()


async def test_endpoints_need_login(client: AsyncClient) -> None:
    assert (await client.get("/conversations")).status_code == 401
    assert (await client.get("/conversations/stream")).status_code == 401


async def test_manager_can_work_with_dialogs(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine, outbound: FakeOutbound
) -> None:
    tenant_id, _, phone = await create_user(owner_engine, role="manager")
    conversation_id = await _dialog(owner_engine, tenant_id)
    await login(client, sender, phone)

    assert (await client.post(f"/conversations/{conversation_id}/takeover")).status_code == 200
