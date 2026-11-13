import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.identity import IdentityIn
from app.cli import SATUSHY_TENANT_ID, create_admin
from tests.conftest import FakeSender, create_user, login, random_phone


async def _audit(engine: AsyncEngine, tenant_id: uuid.UUID) -> list[tuple[str, uuid.UUID]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT action, actor_id FROM audit_log WHERE tenant_id = :t ORDER BY created_at"),
            {"t": tenant_id},
        )
        return [(r.action, r.actor_id) for r in rows]


async def test_admin_impersonation_is_audited(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    phone = random_phone()
    admin_id = await create_admin(IdentityIn(phone=phone))
    shop_id, *_ = await create_user(owner_engine, tenant_name="Клиент")
    await login(client, sender, phone)

    response = await client.post(f"/admin/impersonate/{shop_id}")
    assert response.status_code == 200
    assert response.json()["tenant_name"] == "Клиент"

    me = (await client.get("/me")).json()
    assert me["tenant_id"] == str(shop_id)
    assert me["role"] == "owner"
    assert me["impersonated_by"] == str(admin_id)

    invite = await client.post("/team/invite", json={"phone": random_phone()})
    assert invite.status_code == 201
    assert (await client.delete("/admin/impersonate")).status_code == 204

    me = (await client.get("/me")).json()
    assert me["tenant_id"] == str(SATUSHY_TENANT_ID)
    assert me["role"] == "admin"

    assert await _audit(owner_engine, shop_id) == [
        ("impersonation.start", admin_id),
        ("POST /team/invite", admin_id),
        ("impersonation.stop", admin_id),
    ]


async def test_owner_cannot_impersonate(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    *_, phone = await create_user(owner_engine)
    other_id, *_ = await create_user(owner_engine)
    await login(client, sender, phone)

    assert (await client.post(f"/admin/impersonate/{other_id}")).status_code == 403
    assert await _audit(owner_engine, other_id) == []


async def test_impersonate_unknown_tenant(client: AsyncClient, sender: FakeSender) -> None:
    phone = random_phone()
    await create_admin(IdentityIn(phone=phone))
    await login(client, sender, phone)

    assert (await client.post(f"/admin/impersonate/{uuid.uuid4()}")).status_code == 404


async def test_create_admin_is_idempotent(database: None) -> None:
    email = f"admin-{uuid.uuid4().hex[:6]}@satushy.kz"
    assert await create_admin(IdentityIn(email=email)) == await create_admin(
        IdentityIn(email=email)
    )


async def test_lead_export_by_admin_is_audited(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    phone = random_phone()
    admin_id = await create_admin(IdentityIn(phone=phone))
    shop_id, *_ = await create_user(owner_engine)
    await login(client, sender, phone)
    await client.post(f"/admin/impersonate/{shop_id}")

    assert (await client.get("/leads/export")).status_code == 200
    assert ("GET /leads/export", admin_id) in await _audit(owner_engine, shop_id)
