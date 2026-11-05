import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.agent_helpers import make_conversation
from tests.conftest import FakeSender, create_user, login


async def test_shop_saves_links_and_progress(client: AsyncClient, owner: uuid.UUID) -> None:
    start = (await client.get("/shop")).json()
    assert start["status"] == "onboarding"
    assert start["onboarding_step"] == 1

    response = await client.patch(
        "/shop",
        json={
            "name": "Цветы Пион",
            "city": "Алматы",
            "links": {"instagram": "@pion", "kaspi": "https://kaspi.kz/shop/pion"},
            "onboarding_step": 3,
        },
    )

    assert response.status_code == 200, response.text
    body = (await client.get("/shop")).json()
    assert body["name"] == "Цветы Пион"
    assert body["links"]["instagram"] == "@pion"
    assert body["links"]["website"] is None
    assert body["onboarding_step"] == 3


async def test_finishing_setup_activates_shop(client: AsyncClient, owner: uuid.UUID) -> None:
    done = await client.patch("/shop", json={"onboarding_done": True})
    assert done.json()["status"] == "active"


async def test_shop_edit_is_for_owner_only(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    _, _, phone = await create_user(owner_engine, role="manager")
    await login(client, sender, phone)

    assert (await client.get("/shop")).status_code == 200
    assert (await client.patch("/shop", json={"city": "Астана"})).status_code == 403


async def test_leads_list_filter_and_status(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    _, conversation_id = await make_conversation(owner_engine, owner)
    async with owner_engine.begin() as conn:
        lead_id = await conn.scalar(
            text(
                "INSERT INTO leads (tenant_id, conversation_id, total_kzt, contact_phone)"
                " VALUES (:t, :c, 15000, '+77001112233') RETURNING id"
            ),
            {"t": owner, "c": conversation_id},
        )
        await conn.execute(
            text("INSERT INTO leads (tenant_id, status) VALUES (:t, 'done')"), {"t": owner}
        )

    fresh = (await client.get("/leads", params={"status": "new"})).json()["items"]
    assert [lead["id"] for lead in fresh] == [str(lead_id)]
    assert fresh[0]["channel"] == "web"
    assert fresh[0]["total_kzt"] == 15000

    changed = await client.patch(f"/leads/{lead_id}", json={"status": "in_progress"})
    assert changed.json()["status"] == "in_progress"
    assert (await client.patch(f"/leads/{lead_id}", json={"status": "x"})).status_code == 422
    assert (
        await client.patch(f"/leads/{uuid.uuid4()}", json={"status": "done"})
    ).status_code == 404


async def test_products_search_page_and_isolation(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine)
    async with owner_engine.begin() as conn:
        for name, sku in (("Пионы белые", "P-1"), ("Розы", "R-100%"), ("Тюльпаны", None)):
            await conn.execute(
                text("INSERT INTO products (tenant_id, name, sku, price) VALUES (:t, :n, :s, 100)"),
                {"t": owner, "n": name, "s": sku},
            )
        await conn.execute(
            text("INSERT INTO products (tenant_id, name) VALUES (:t, 'Пионы чужие')"), {"t": other}
        )
        await conn.execute(
            text("INSERT INTO products (tenant_id, name, is_active) VALUES (:t, 'Снятые', false)"),
            {"t": owner},
        )

    everything = (await client.get("/products", params={"limit": 2})).json()
    assert everything["total"] == 3
    assert [p["name"] for p in everything["items"]] == ["Пионы белые", "Розы"]
    assert everything["items"][0]["indexed"] is False
    assert "embedding" not in everything["items"][0]

    assert [
        p["name"] for p in (await client.get("/products", params={"q": "пион"})).json()["items"]
    ] == ["Пионы белые"]
    assert (await client.get("/products", params={"q": "%"})).json()["items"][0]["sku"] == "R-100%"
    assert (await client.get("/products", params={"offset": 2})).json()["items"][0][
        "name"
    ] == "Тюльпаны"
