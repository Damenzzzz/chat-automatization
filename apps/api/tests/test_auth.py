import asyncio

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from app.auth.tokens import decode_access_token
from app.core.config import get_settings
from tests.conftest import FakeSender, create_user, login, random_phone


async def test_full_code_cycle(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, user_id, phone = await create_user(owner_engine)

    response = await client.post("/auth/request-code", json={"phone": phone})
    assert response.status_code == 202
    code = sender.codes[phone]

    response = await client.post("/auth/verify", json={"phone": phone, "code": code})
    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "role": "owner",
    }

    set_cookie = " ".join(response.headers.get_list("set-cookie")).lower()
    assert set_cookie.count("httponly") == 3
    claims = decode_access_token(client.cookies[ACCESS_COOKIE], get_settings())
    assert claims.user_id == user_id and claims.tenant_id == tenant_id

    reuse = await client.post("/auth/verify", json={"phone": phone, "code": code})
    assert reuse.status_code == 400
    assert reuse.json()["detail"] == "code_expired"


async def test_wrong_code_limit(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    *_, phone = await create_user(owner_engine)
    await client.post("/auth/request-code", json={"phone": phone})
    wrong = "000000" if sender.codes[phone] != "000000" else "111111"

    statuses = [
        (await client.post("/auth/verify", json={"phone": phone, "code": wrong})).status_code
        for _ in range(6)
    ]
    assert statuses == [400] * 5 + [429]

    correct = await client.post("/auth/verify", json={"phone": phone, "code": sender.codes[phone]})
    assert correct.json()["detail"] == "code_expired"


async def test_request_code_rate_limit(client: AsyncClient) -> None:
    phone = random_phone()
    statuses = [
        (await client.post("/auth/request-code", json={"phone": phone})).status_code
        for _ in range(4)
    ]
    assert statuses == [202, 202, 202, 429]


async def test_expired_code(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine, redis: Redis
) -> None:
    *_, phone = await create_user(owner_engine)
    await client.post("/auth/request-code", json={"phone": phone})
    await redis.pexpire(f"otp:phone:{phone}:code", 1)
    await asyncio.sleep(0.01)

    response = await client.post("/auth/verify", json={"phone": phone, "code": sender.codes[phone]})
    assert response.status_code == 400
    assert response.json()["detail"] == "code_expired"


async def test_refresh_rotates_token(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    *_, phone = await create_user(owner_engine)
    await login(client, sender, phone)
    old_refresh = client.cookies[REFRESH_COOKIE]

    response = await client.post("/auth/refresh")
    assert response.status_code == 200
    new_refresh = client.cookies[REFRESH_COOKIE]
    assert new_refresh != old_refresh

    client.cookies.set(REFRESH_COOKIE, old_refresh, path="/auth")
    reused = await client.post("/auth/refresh")
    assert reused.status_code == 401


async def test_logout_revokes_refresh(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    *_, phone = await create_user(owner_engine)
    await login(client, sender, phone)
    refresh = client.cookies[REFRESH_COOKIE]

    assert (await client.post("/auth/logout")).status_code == 204
    client.cookies.set(REFRESH_COOKIE, refresh, path="/auth")
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_unknown_user_needs_signup(client: AsyncClient, sender: FakeSender) -> None:
    phone = random_phone()
    await client.post("/auth/request-code", json={"phone": phone})
    response = await client.post("/auth/verify", json={"phone": phone, "code": sender.codes[phone]})
    assert response.status_code == 409
    assert response.json()["detail"] == "signup_required"


async def test_logout_revokes_access_token(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    _, _, phone = await create_user(owner_engine)
    await login(client, sender, phone)
    stolen = client.cookies[ACCESS_COOKIE]
    assert (await client.get("/me")).status_code == 200

    await client.post("/auth/logout")
    client.cookies.set(ACCESS_COOKIE, stolen)

    assert (await client.get("/me")).status_code == 401


async def test_suspended_shop_is_locked_out(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, _, phone = await create_user(owner_engine)
    await login(client, sender, phone)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'suspended' WHERE id = :t"), {"t": tenant_id}
        )

    response = await client.get("/me")

    assert response.status_code == 403
    assert response.json()["detail"] == "shop_suspended"


async def test_code_requests_are_limited_per_ip(
    client: AsyncClient, sender: FakeSender, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "otp_ip_requests", 2)
    statuses = [
        (await client.post("/auth/request-code", json={"phone": random_phone()})).status_code
        for _ in range(3)
    ]
    assert statuses == [202, 202, 429]
