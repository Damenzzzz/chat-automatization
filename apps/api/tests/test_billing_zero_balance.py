import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.billing.alerts import (
    NOTIFY_OWNER,
    balance_alert,
    crossed_threshold,
    send_owner_message,
)
from app.billing.ledger import Charge
from app.channels.outbound import Outbound
from app.channels.registry import get_adapters
from app.db.session import tenant_session
from app.llm import LLMResponse, Usage
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation, nodes
from tests.billing_helpers import balance, charges, login_admin, topup
from tests.channel_helpers import RecordingAdapter, make_channel
from tests.conftest import FakeSender, RecordingQueue, create_user, login

SMALLTALK = Understanding(lang="ru", intent="smalltalk", complexity="low")


def _expensive_llm() -> FakeLLM:
    usage = Usage(input_tokens=10_000_000, output_tokens=0)
    return FakeLLM(
        [
            LLMResponse(text="", parsed=SMALLTALK, usage=usage, model="gemini-3.1-flash-lite"),
            LLMResponse(text="Здравствуйте!", usage=usage, model="gemini-3.5-flash-lite"),
        ]
    )


async def _conversation_state(engine: AsyncEngine, conversation_id: uuid.UUID) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT mode, paused_reason FROM conversations WHERE id = :c"),
                {"c": conversation_id},
            )
        ).one()


async def _charge_row(engine: AsyncEngine, tenant_id: uuid.UUID, amount: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO ledger (tenant_id, type, amount_kzt) VALUES (:t, 'charge', :a)"),
            {"t": tenant_id, "a": -amount},
        )


async def test_zero_balance_answers_with_template_without_llm(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    llm = FakeLLM([])
    agent, queue = await make_agent(llm=llm)

    turn = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="есть пионы?")

    assert llm.calls == []
    assert "Менеджер скоро вам ответит" in (turn.reply or "")
    assert turn.human_mode is True
    assert nodes(turn.trace) == ["ingest", "guard_in", "gate", "send", "meter"]
    state = await _conversation_state(owner_engine, conversation_id)
    assert state.mode == "human"
    assert state.paused_reason == "no_balance"
    assert await charges(owner_engine, tenant_id) == []
    assert await balance(owner_engine, tenant_id) == 0
    assert queue.jobs[-1][1][1] == "handoff"
    async with owner_engine.connect() as conn:
        unanswered = await conn.scalar(
            text("SELECT count(*) FROM unanswered WHERE tenant_id = :t"), {"t": tenant_id}
        )
    assert unanswered == 0


async def test_template_follows_customer_language(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    agent, _ = await make_agent(llm=FakeLLM([]))
    turn = await agent.run(
        tenant_id=tenant_id, conversation_id=conversation_id, text="ақ раушан гүлі бар ма?"
    )
    assert "Менеджер жақын арада" in (turn.reply or "")


async def test_template_reaches_customer_channel_and_next_message_goes_to_manager(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    channel_id = await make_channel(owner_engine, tenant_id)
    adapter = RecordingAdapter()
    agent, _ = await make_agent(llm=FakeLLM([]), channels=Outbound({"telegram": adapter}))
    common: dict[str, Any] = {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "channel_id": channel_id,
        "customer_external_id": "c1",
    }
    await agent.run(text="алло", **common)
    second = await agent.run(text="вы тут?", **common)

    assert len(adapter.sent) == 1
    assert second.reply is None
    assert nodes(second.trace) == ["ingest", "guard_in"]


async def test_balance_below_expected_price_switches_to_human_and_stays_non_negative(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 1000)
    await _charge_row(owner_engine, tenant_id, 500)
    await _charge_row(owner_engine, tenant_id, 497)
    assert await balance(owner_engine, tenant_id) == 3
    llm = FakeLLM([])
    agent, _ = await make_agent(llm=llm)

    turn = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="привет")

    assert turn.human_mode is True
    assert llm.calls == []
    assert await balance(owner_engine, tenant_id) == 3


async def test_reply_costing_more_than_balance_never_goes_negative(
    owner_engine: AsyncEngine,
) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 2)
    agent, _ = await make_agent(llm=_expensive_llm())

    first = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="привет")

    assert first.reply == "Здравствуйте!"
    assert await balance(owner_engine, tenant_id) == 0
    assert await charges(owner_engine, tenant_id) == [-2]

    second = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="ещё")
    assert second.human_mode is True
    assert "Менеджер" in (second.reply or "")
    assert await balance(owner_engine, tenant_id) == 0
    assert await charges(owner_engine, tenant_id) == [-2]


async def test_sandbox_works_with_empty_balance(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    agent, _ = await make_agent(llm=FakeLLM([SMALLTALK, "Здравствуйте!"]))
    turn = await agent.run(
        tenant_id=tenant_id, conversation_id=conversation_id, text="привет", sandbox=True
    )
    assert turn.reply == "Здравствуйте!"
    assert turn.human_mode is False
    assert "gate" not in nodes(turn.trace)


async def test_topup_returns_only_balance_paused_dialogs_to_bot(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, paused = await make_conversation(owner_engine, funds=0)
    _, manager = await make_conversation(owner_engine, tenant_id, mode="human")
    agent, _ = await make_agent(llm=FakeLLM([]))
    await agent.run(tenant_id=tenant_id, conversation_id=paused, text="алло")

    await login_admin(client, sender)
    response = await client.post(f"/admin/tenants/{tenant_id}/topup", json={"amount_kzt": 5000})

    assert response.json()["resumed_conversations"] == 1
    resumed = await _conversation_state(owner_engine, paused)
    assert resumed.mode == "bot"
    assert resumed.paused_reason is None
    assert (await _conversation_state(owner_engine, manager)).mode == "human"

    llm = FakeLLM([SMALLTALK, "С возвращением!"])
    agent_after, _ = await make_agent(llm=llm)
    turn = await agent_after.run(tenant_id=tenant_id, conversation_id=paused, text="вы тут?")
    assert turn.reply == "С возвращением!"
    assert turn.human_mode is False


@pytest.mark.parametrize(
    ("before", "after", "topup_kzt", "expected"),
    [
        (210, 200, 1000, 20),
        (210, 201, 1000, None),
        (200, 190, 1000, None),
        (60, 50, 1000, 5),
        (50, 40, 1000, None),
        (1, 0, 1000, 0),
        (300, 40, 1000, 5),
        (300, 0, 1000, 0),
        (0, 0, 1000, None),
        (5000, 4000, 5000, None),
    ],
)
def test_threshold_is_reported_once_when_crossed(
    before: int, after: int, topup_kzt: int, expected: int | None
) -> None:
    assert crossed_threshold(before, after, topup_kzt) == expected


def _charge(before: int, after: int) -> Charge:
    from decimal import Decimal

    return Charge(before - after, before - after, before, after, Decimal(0))


async def test_alert_is_stored_for_cabinet_and_uses_last_topup(owner_engine: AsyncEngine) -> None:
    tenant_id, _ = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 100_000)
    await topup(owner_engine, tenant_id, 1000)
    async with tenant_session(tenant_id) as session:
        assert await balance_alert(session, tenant_id, _charge(10_000, 9_000)) is None
        text_20 = await balance_alert(session, tenant_id, _charge(210, 200))
    assert text_20 is not None and "20%" in text_20 and "1 000 ₸" in text_20
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT kind, details FROM notifications WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).one()
    assert row.kind == "balance_low"
    assert row.details["threshold"] == 20


async def test_no_alert_without_any_topup(owner_engine: AsyncEngine) -> None:
    tenant_id, _ = await make_conversation(owner_engine, funds=0)
    async with tenant_session(tenant_id) as session:
        assert await balance_alert(session, tenant_id, _charge(210, 200)) is None


async def test_meter_raises_alert_when_reply_crosses_threshold(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 2)
    agent, queue = await make_agent(llm=_expensive_llm())

    await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="привет")

    owner_jobs = [args for name, args in queue.jobs if name == NOTIFY_OWNER]
    assert len(owner_jobs) == 1
    assert owner_jobs[0][0] == str(tenant_id)
    assert "закончился" in str(owner_jobs[0][1])
    async with owner_engine.connect() as conn:
        kind = await conn.scalar(
            text("SELECT kind FROM notifications WHERE tenant_id = :t"), {"t": tenant_id}
        )
    assert kind == "balance_zero"


async def test_owner_telegram_alert_goes_only_to_linked_owner(owner_engine: AsyncEngine) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    await create_user(owner_engine, tenant_id=tenant_id, role="manager")
    adapter = RecordingAdapter()
    adapters: Any = {"telegram": adapter}

    assert await send_owner_message(tenant_id, "мало денег", adapters) == 0

    await make_channel(owner_engine, tenant_id, credentials={"token": "t"})
    assert await send_owner_message(tenant_id, "мало денег", adapters) == 0

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET telegram_chat_id = '777' WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    assert await send_owner_message(tenant_id, "мало денег", adapters) == 1
    assert [(c, m.text) for c, m in adapter.sent] == [("777", "мало денег")]


async def test_failed_telegram_alert_does_not_raise(owner_engine: AsyncEngine) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    await make_channel(owner_engine, tenant_id, credentials={"token": "t"})
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET telegram_chat_id = '1' WHERE tenant_id = :t"), {"t": tenant_id}
        )
    adapters: Any = {"telegram": RecordingAdapter(fail=True)}
    assert await send_owner_message(tenant_id, "x", adapters) == 0


async def test_notifications_list_read_and_isolation(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    async with owner_engine.begin() as conn:
        for tenant, body in ((owner, "мой"), (other, "чужой")):
            await conn.execute(
                text("INSERT INTO notifications (tenant_id, kind, text) VALUES (:t, 'x', :b)"),
                {"t": tenant, "b": body},
            )

    [item] = (await client.get("/notifications")).json()
    assert item["text"] == "мой"
    assert item["read_at"] is None

    read = await client.post(f"/notifications/{item['id']}/read")
    assert read.json()["read_at"] is not None
    assert (await client.get("/notifications", params={"unread_only": True})).json() == []
    assert len((await client.get("/notifications")).json()) == 1


async def test_foreign_notification_cannot_be_marked_read(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    async with owner_engine.begin() as conn:
        foreign = await conn.scalar(
            text(
                "INSERT INTO notifications (tenant_id, kind, text) VALUES (:t, 'x', 'чужой')"
                " RETURNING id"
            ),
            {"t": other},
        )
    assert (await client.post(f"/notifications/{foreign}/read")).status_code == 404


def _start(token: str, chat: int = 4242) -> dict[str, Any]:
    return {
        "update_id": uuid.uuid4().int % 10**9,
        "message": {
            "message_id": 1,
            "date": 1793800000,
            "from": {"id": chat, "is_bot": False, "first_name": "Владелец"},
            "chat": {"id": chat, "type": "private"},
            "text": f"/start {token}",
        },
    }


async def test_owner_links_telegram_with_single_use_token(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, queue: RecordingQueue
) -> None:
    channel = await make_channel(owner_engine, owner, secret="s", credentials={"token": "t"})
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE channels SET name = '@pion_bot' WHERE id = :c"), {"c": channel}
        )

    link = await client.post("/me/telegram/link")
    assert link.status_code == 200, link.text
    url = link.json()["url"]
    assert url.startswith("https://t.me/pion_bot?start=owner_")
    token = url.split("start=")[1]

    headers = {"X-Telegram-Bot-Api-Secret-Token": "s"}
    hook = f"/webhooks/telegram/{channel}"
    assert (await client.post(hook, json=_start(token), headers=headers)).status_code == 200

    async with owner_engine.connect() as conn:
        chat = await conn.scalar(
            text("SELECT telegram_chat_id FROM users WHERE tenant_id = :t"), {"t": owner}
        )
    assert chat == "4242"
    assert [name for name, _ in queue.jobs] == [NOTIFY_OWNER]

    assert (
        await client.post(hook, json=_start(token, chat=666), headers=headers)
    ).status_code == 200
    async with owner_engine.connect() as conn:
        chat = await conn.scalar(
            text("SELECT telegram_chat_id FROM users WHERE tenant_id = :t"), {"t": owner}
        )
    assert chat == "4242"
    assert len(queue.jobs) == 1


async def test_link_token_of_one_shop_does_not_work_on_another_bot(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, queue: RecordingQueue
) -> None:
    await make_channel(owner_engine, owner, secret="s", credentials={"token": "t"})
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE channels SET name = '@a' WHERE tenant_id = :t"), {"t": owner}
        )
    token = (await client.post("/me/telegram/link")).json()["url"].split("start=")[1]

    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    other_channel = await make_channel(owner_engine, other, secret="z", credentials={"token": "t"})
    await client.post(
        f"/webhooks/telegram/{other_channel}",
        json=_start(token),
        headers={"X-Telegram-Bot-Api-Secret-Token": "z"},
    )
    async with owner_engine.connect() as conn:
        linked = await conn.scalar(
            text("SELECT count(telegram_chat_id) FROM users WHERE tenant_id IN (:a, :b)"),
            {"a": owner, "b": other},
        )
    assert linked == 0
    assert queue.jobs == []


async def test_link_requires_connected_bot(
    client: AsyncClient, owner: uuid.UUID, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    response = await client.post("/me/telegram/link")
    assert response.status_code == 409
    assert response.json()["detail"] == "telegram_not_connected"
    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)
    assert (await client.post("/me/telegram/link")).status_code == 409


def test_notify_owner_is_registered() -> None:
    from app.worker import WorkerSettings

    assert NOTIFY_OWNER in {getattr(f, "name", "") for f in WorkerSettings.functions}
    assert "telegram" in get_adapters()
