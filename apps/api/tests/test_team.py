from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import FakeSender, create_user, login, random_phone


async def test_owner_invites_manager_who_can_login(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, owner_id, owner_phone = await create_user(owner_engine)
    await login(client, sender, owner_phone)

    manager_phone = random_phone()
    response = await client.post("/team/invite", json={"phone": manager_phone, "name": "Айгерим"})
    assert response.status_code == 201
    assert response.json()["role"] == "manager"

    team = (await client.get("/team")).json()
    assert team[0]["id"] == str(owner_id)
    assert {m["phone"] for m in team} == {owner_phone, manager_phone}

    session = (await login(client, sender, manager_phone)).json()
    assert session["tenant_id"] == str(tenant_id)
    assert session["role"] == "manager"
    assert (await client.get("/team")).status_code == 200


async def test_manager_cannot_invite_or_remove(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, owner_id, _ = await create_user(owner_engine)
    *_, manager_phone = await create_user(owner_engine, role="manager", tenant_id=tenant_id)
    await login(client, sender, manager_phone)

    invite = await client.post("/team/invite", json={"phone": random_phone()})
    assert invite.status_code == 403
    assert (await client.delete(f"/team/{owner_id}")).status_code == 403


async def test_remove_member(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, owner_id, owner_phone = await create_user(owner_engine)
    _, manager_id, manager_phone = await create_user(
        owner_engine, role="manager", tenant_id=tenant_id
    )
    await login(client, sender, owner_phone)

    assert (await client.delete(f"/team/{owner_id}")).status_code == 400
    assert (await client.delete(f"/team/{manager_id}")).status_code == 204
    assert {m["id"] for m in (await client.get("/team")).json()} == {str(owner_id)}

    await client.post("/auth/request-code", json={"phone": manager_phone})
    relogin = await client.post(
        "/auth/verify", json={"phone": manager_phone, "code": sender.codes[manager_phone]}
    )
    assert relogin.status_code == 409


async def test_cannot_touch_other_tenant_member(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    *_, owner_a_phone = await create_user(owner_engine)
    _, owner_b_id, owner_b_phone = await create_user(owner_engine)
    await login(client, sender, owner_a_phone)

    assert (await client.delete(f"/team/{owner_b_id}")).status_code == 404
    assert owner_b_phone not in {m["phone"] for m in (await client.get("/team")).json()}

    duplicate = await client.post("/team/invite", json={"phone": owner_b_phone})
    assert duplicate.status_code == 409
