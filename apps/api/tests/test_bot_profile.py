import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.prompt import load_profile
from app.db.session import tenant_session


async def test_each_save_is_new_version(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    assert (await client.get("/bot-profile")).status_code == 404
    first = await client.put("/bot-profile", json={"tone": "строгий", "rules": {"a": "Без скидок"}})
    second = await client.put("/bot-profile", json={"tone": "тёплый", "greeting": "Сәлем!"})
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert second.json()["based_on"] == 1

    active = (await client.get("/bot-profile")).json()
    assert active["version"] == 2
    assert active["tone"] == "тёплый"
    versions = (await client.get("/bot-profile/versions")).json()
    assert [(v["version"], v["is_active"]) for v in versions] == [(2, True), (1, False)]

    async with tenant_session(owner) as session:
        profile = await load_profile(session, owner)
    assert (profile.version, profile.greeting) == (2, "Сәлем!")


async def test_rollback_to_previous_version(client: AsyncClient, owner: uuid.UUID) -> None:
    await client.put("/bot-profile", json={"tone": "v1", "rules": {"delivery": "2 000 ₸"}})
    await client.put("/bot-profile", json={"tone": "v2"})

    rolled = await client.post("/bot-profile/rollback")
    assert rolled.status_code == 200
    body = rolled.json()
    assert (body["version"], body["based_on"], body["tone"]) == (3, 1, "v1")
    assert body["rules"] == {"delivery": "2 000 ₸"}

    explicit = await client.post("/bot-profile/rollback", json={"version": 2})
    assert (explicit.json()["version"], explicit.json()["tone"]) == (4, "v2")
    versions = (await client.get("/bot-profile/versions")).json()
    assert sum(v["is_active"] for v in versions) == 1


async def test_rollback_without_previous_version(client: AsyncClient, owner: uuid.UUID) -> None:
    assert (await client.post("/bot-profile/rollback")).status_code == 409
    await client.put("/bot-profile", json={"tone": "один"})
    assert (await client.post("/bot-profile/rollback")).status_code == 409
    assert (await client.post("/bot-profile/rollback", json={"version": 7})).status_code == 409


async def test_bot_profile_requires_login(client: AsyncClient) -> None:
    assert (await client.get("/bot-profile")).status_code == 401


async def test_niches_cover_every_shop_category(client: AsyncClient) -> None:
    niches = (await client.get("/niches")).json()
    assert len(niches) >= 12
    assert len({n["key"] for n in niches}) == len(niches)
    for niche in niches:
        assert niche["tone"] and niche["greeting"] and niche["rules"]["handoff"]
        assert 2 <= len(niche["rules"]["custom"]) <= 4
        assert not set(niche["rules"]) & {"delivery", "payment", "discounts"}


async def test_preset_keeps_delivery_and_payment_of_the_shop(
    client: AsyncClient, owner: uuid.UUID
) -> None:
    rules = {"delivery": "По Алматы 2 000 ₸", "payment": "Kaspi", "custom": ["Старое правило"]}
    await client.put("/bot-profile", json={"tone": "строгий", "rules": rules, "languages": ["ru"]})

    applied = await client.post("/bot-profile/preset", json={"niche": "Автозапчасти"})
    assert applied.status_code == 200
    body = applied.json()
    assert (body["version"], body["based_on"], body["languages"]) == (2, 1, ["ru"])
    assert body["rules"]["delivery"] == "По Алматы 2 000 ₸"
    assert body["rules"]["payment"] == "Kaspi"
    assert "Старое правило" not in body["rules"]["custom"]
    assert "VIN" in body["rules"]["handoff"]

    rolled = (await client.post("/bot-profile/rollback")).json()
    assert rolled["tone"] == "строгий"


async def test_preset_for_new_shop_and_unknown_niche(client: AsyncClient, owner: uuid.UUID) -> None:
    assert (await client.post("/bot-profile/preset", json={"niche": "космос"})).status_code == 404
    created = await client.post("/bot-profile/preset", json={"niche": "clothing"})
    assert created.json()["version"] == 1
    assert created.json()["languages"] == ["ru", "kk"]
