import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.guard import check_reply
from app.agent.prompt import ShopProfile
from app.llm import get_llm
from app.llm.fake import FakeLLM
from app.mlclient import get_ml_client
from tests.agent_helpers import make_agent, make_conversation
from tests.fake_ml import FakeML
from tests.test_conversations_api import _dialog


async def test_search_finds_dialog_by_message_and_name(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    first = await _dialog(owner_engine, owner)
    second = await _dialog(owner_engine, owner)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE customers SET name = 'Айгерим' WHERE id ="
                " (SELECT customer_id FROM conversations WHERE id = :c)"
            ),
            {"c": second},
        )

    by_text = (await client.get("/conversations", params={"q": "пионы"})).json()
    by_name = (await client.get("/conversations", params={"q": "айгер"})).json()
    nothing = (await client.get("/conversations", params={"q": "100%"})).json()

    assert {i["id"] for i in by_text["items"]} == {str(first), str(second)}
    assert [i["id"] for i in by_name["items"]] == [str(second)]
    assert nothing["items"] == []


async def test_customer_card_keeps_note_and_history(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    conversation_id = await _dialog(owner_engine, owner)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO leads (tenant_id, conversation_id, total_kzt) VALUES (:t, :c, 52000)"
            ),
            {"t": owner, "c": conversation_id},
        )

    saved = await client.patch(
        f"/conversations/{conversation_id}/customer", json={"note": " Заказывает оптом "}
    )
    customer = (await client.get(f"/conversations/{conversation_id}")).json()["customer"]

    assert saved.status_code == 200
    assert customer["note"] == "Заказывает оптом"
    assert customer["dialogs"] == 1
    assert [lead["total_kzt"] for lead in customer["leads"]] == [52000]


async def test_draft_is_written_by_model_and_checked(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, app: FastAPI
) -> None:
    conversation_id = await _dialog(owner_engine, owner)
    assert (await client.post(f"/conversations/{conversation_id}/draft")).status_code == 503

    app.dependency_overrides[get_ml_client] = FakeML
    app.dependency_overrides[get_llm] = lambda: FakeLLM(["Пионы стоят 99 000 ₸."])
    body = (await client.post(f"/conversations/{conversation_id}/draft")).json()

    assert body == {"text": "Пионы стоят 99 000 ₸.", "verified": False}


async def test_paused_shop_leaves_message_to_manager(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    paused = await client.patch("/shop", json={"bot_paused": True})
    assert paused.json()["bot_paused"] is True
    _, conversation_id = await make_conversation(owner_engine, owner)
    agent, _ = await make_agent(FakeLLM([]))

    turn = await agent.run(tenant_id=owner, conversation_id=conversation_id, text="есть пионы?")

    assert turn.human_mode is True
    assert turn.reply is None


async def test_shop_keeps_reply_templates(client: AsyncClient, owner: uuid.UUID) -> None:
    templates = [{"title": "Адрес", "text": "Абая 10, с 9 до 21."}]
    saved = await client.patch("/shop", json={"reply_templates": templates})
    assert saved.json()["reply_templates"] == templates
    assert (await client.get("/shop")).json()["reply_templates"] == templates


async def test_overview_counts_spend_and_funnel(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    conversation_id = await _dialog(owner_engine, owner)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO ledger (tenant_id, type, amount_kzt) VALUES (:t, 'charge', -120)"),
            {"t": owner},
        )
        await conn.execute(
            text(
                "INSERT INTO search_log (tenant_id, conversation_id, query, result_count)"
                " VALUES (:t, :c, 'пионы', 3)"
            ),
            {"t": owner, "c": conversation_id},
        )
        await conn.execute(
            text(
                "INSERT INTO leads (tenant_id, conversation_id, total_kzt, status)"
                " VALUES (:t, :c, 52000, 'done')"
            ),
            {"t": owner, "c": conversation_id},
        )

    current = (await client.get("/analytics/overview")).json()["current"]

    assert current["spent_kzt"] == 120
    assert current["found_dialogs"] == 1
    assert current["leads_done"] == 1


def test_guard_accepts_price_times_quantity() -> None:
    context = [{"type": "product", "sku_norm": "pn001", "price": 32000}]
    profile = ShopProfile(name="Цветы")
    ok = check_reply("5 букетов по 32 000 ₸ выйдут в 160 000 ₸.", context, profile)
    bad = check_reply("5 букетов по 32 000 ₸ выйдут в 150 000 ₸.", context, profile)
    assert ok.ok
    assert not bad.ok
