import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.ratelimit import limit
from app.db.session import tenant_session
from app.demo.activity import DEMO_PREFIX
from app.mlclient import get_ml_client
from app.models import Conversation, Customer, Lead
from app.seed import DEMO_TENANT_ID
from tests.conftest import RecordingQueue, random_phone
from tests.fake_ml import FakeML


@pytest.fixture
def demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "demo_enabled", True)


async def demo_customers() -> int:
    async with tenant_session(DEMO_TENANT_ID) as session:
        value = await session.scalar(
            select(func.count(Customer.id)).where(Customer.external_id.startswith(DEMO_PREFIX))
        )
    return int(value or 0)


async def test_demo_disabled(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "demo_enabled", False)
    assert (await client.get("/demo")).json()["enabled"] is False
    response = await client.post("/demo/login")
    assert response.status_code == 404
    assert response.json()["detail"] == "demo_disabled"


@pytest.mark.usefixtures("demo_on")
async def test_demo_login_opens_filled_shop(client: AsyncClient, queue: RecordingQueue) -> None:
    response = await client.post("/demo/login")
    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(DEMO_TENANT_ID)
    assert response.json()["role"] == "owner"

    me = (await client.get("/me")).json()
    assert me["tenant_name"] == "Цветы Пион"

    overview = (await client.get("/analytics/overview")).json()["current"]
    assert overview["dialogs"] > 10
    assert overview["leads"] > 0

    conversations = (await client.get("/conversations")).json()
    assert conversations["counts"]["waiting"] >= 1

    async with tenant_session(DEMO_TENANT_ID) as session:
        leads = await session.scalar(select(func.count(Lead.id)))
        demo_conversations = await session.scalar(
            select(func.count(Conversation.id))
            .join(Customer, Customer.id == Conversation.customer_id)
            .where(Customer.external_id.startswith(DEMO_PREFIX))
        )
    assert leads and demo_conversations

    before = await demo_customers()
    assert (await client.post("/demo/login")).status_code == 200
    assert await demo_customers() == before


@pytest.mark.usefixtures("demo_on")
async def test_demo_chat_runs_sandbox(client: AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_ml_client] = FakeML
    response = await client.post(
        "/demo/chat", json={"message": "Есть розовые пионы?", "session_id": "landing-test-1"}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"reply", "lang", "intent", "human_mode", "cards"}

    async with tenant_session(DEMO_TENANT_ID) as session:
        sandbox = await session.scalar(
            select(Conversation.sandbox)
            .join(Customer, Customer.id == Conversation.customer_id)
            .where(Customer.external_id == "sandbox:landing-landing-test-1")
        )
    assert sandbox is True


async def test_demo_chat_rejects_bad_session(client: AsyncClient, demo_on: None) -> None:
    response = await client.post("/demo/chat", json={"message": "привет", "session_id": "x y"})
    assert response.status_code == 422


async def test_limit_blocks_after_count(redis: Redis) -> None:
    key = f"test:{random_phone()}"
    await limit(redis, key, 2, 60)
    await limit(redis, key, 2, 60)
    with pytest.raises(HTTPException) as exc:
        await limit(redis, key, 2, 60)
    assert exc.value.status_code == 429


@pytest.mark.parametrize(("enabled", "shown"), [(True, True), (False, False)])
async def test_request_code_shows_code_in_demo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, enabled: bool, shown: bool
) -> None:
    monkeypatch.setattr(get_settings(), "demo_enabled", enabled)
    response = await client.post("/auth/request-code", json={"phone": random_phone()})
    assert response.status_code == 202
    code = response.json().get("demo_code")
    assert (code is not None and len(code) == 6) is shown


async def test_request_code_hides_code_in_prod(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "env", "prod")
    response = await client.post("/auth/request-code", json={"phone": random_phone()})
    assert response.status_code == 202
    assert response.json().get("demo_code") is None


@pytest.mark.usefixtures("demo_on")
async def test_demo_owner_cannot_change_shop(client: AsyncClient, queue: RecordingQueue) -> None:
    await client.post("/demo/login")

    for method, path in [("PUT", "/bot-profile"), ("PATCH", "/shop"), ("POST", "/team/invite")]:
        response = await client.request(method, path, json={})
        assert response.status_code == 403
        assert response.json()["detail"] == "demo_read_only"

    chat = await client.post("/sandbox/chat", json={"message": "привет", "session_id": "demo-1"})
    assert chat.status_code == 200
