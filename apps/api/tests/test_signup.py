import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import FakeSender, login, random_phone

SIGNUP = {"name": "Цветы Лотос", "city": "Астана", "niche": "цветы"}


async def test_first_login_creates_tenant_and_owner(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    phone = random_phone()
    await client.post("/auth/request-code", json={"phone": phone})
    code = sender.codes[phone]

    pending = await client.post("/auth/verify", json={"phone": phone, "code": code})
    assert pending.status_code == 409

    response = await client.post(
        "/auth/verify", json={"phone": phone, "code": code, "signup": SIGNUP}
    )
    assert response.status_code == 200
    session = response.json()
    assert session["role"] == "owner"

    async with owner_engine.connect() as conn:
        tenant = (
            await conn.execute(
                text("SELECT name, city, niche, status FROM tenants WHERE id = :id"),
                {"id": session["tenant_id"]},
            )
        ).one()
        owner_phone = await conn.scalar(
            text("SELECT phone FROM users WHERE id = :id"), {"id": session["user_id"]}
        )
    assert tuple(tenant) == ("Цветы Лотос", "Астана", "цветы", "onboarding")
    assert owner_phone == phone

    again = await login(client, sender, phone)
    assert again.json() == session


async def test_signup_by_email(client: AsyncClient, sender: FakeSender) -> None:
    email = f"shop-{uuid.uuid4().hex[:8]}@mail.kz"
    await client.post("/auth/request-code", json={"email": email.upper()})
    response = await client.post(
        "/auth/verify",
        json={"email": email, "code": sender.codes[email], "signup": {"name": "Ромашка"}},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "owner"


async def test_signup_with_wrong_code_creates_nothing(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    phone = random_phone()
    await client.post("/auth/request-code", json={"phone": phone})
    wrong = "000000" if sender.codes[phone] != "000000" else "111111"

    response = await client.post(
        "/auth/verify", json={"phone": phone, "code": wrong, "signup": SIGNUP}
    )
    assert response.status_code == 400
    async with owner_engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM users WHERE phone = :p"), {"p": phone})
    assert count == 0
