import hashlib
import hmac
import uuid

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channels.whatsapp import verify_signature
from app.core.crypto import decrypt_json
from tests.channel_helpers import make_channel
from tests.conftest import FakeSender, RecordingQueue, create_user, login

APP_SECRET = "0123456789abcdef0123456789abcdef"
ACCESS_TOKEN = "EAAFakeAccessTokenForTestsOnly1234567890"
PHONE_ID = "106540352242922"
CREDENTIALS = {
    "phone_number_id": PHONE_ID,
    "waba_id": "102290129340398",
    "access_token": ACCESS_TOKEN,
    "app_secret": APP_SECRET,
}


@pytest.fixture
def connect() -> dict[str, str]:
    return {**CREDENTIALS, "phone_number_id": str(10**14 + uuid.uuid4().int % 10**14)}


def signed(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
async def channel(owner_engine: AsyncEngine, client: AsyncClient) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        tenant = await conn.scalar(text("INSERT INTO tenants (name) VALUES ('Т') RETURNING id"))
    return await make_channel(
        owner_engine,
        tenant,
        type_="whatsapp",
        secret="verify-me",
        credentials=CREDENTIALS,
    )


async def post_webhook(
    client: AsyncClient, channel_id: uuid.UUID, body: bytes, signature: str | None
) -> httpx.Response:
    headers = {"X-Hub-Signature-256": signature} if signature else {}
    return await client.post(f"/webhooks/whatsapp/{channel_id}", content=body, headers=headers)


def test_signature_matches_known_vector() -> None:
    body = b'{"object":"whatsapp_business_account"}'
    header = "sha256=" + hashlib.sha256(b"").hexdigest()
    assert verify_signature(APP_SECRET, body, signed(body))
    assert not verify_signature(APP_SECRET, body, header)
    assert not verify_signature(APP_SECRET, body, signed(body, "другой-секрет"))
    assert not verify_signature(APP_SECRET, body + b" ", signed(body))
    assert not verify_signature(APP_SECRET, body, signed(body).removeprefix("sha256="))
    assert not verify_signature(APP_SECRET, body, None)
    assert not verify_signature("", body, signed(body, ""))


async def test_webhook_accepts_correct_signature(client: AsyncClient, channel: uuid.UUID) -> None:
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    response = await post_webhook(client, channel, body, signed(body))
    assert response.status_code == 200


@pytest.mark.parametrize("bad", ["sha256=deadbeef", "deadbeef", None])
async def test_webhook_rejects_bad_signature(
    client: AsyncClient, channel: uuid.UUID, queue: RecordingQueue, bad: str | None
) -> None:
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    response = await post_webhook(client, channel, body, bad)
    assert response.status_code == 401
    assert queue.jobs == []


async def test_webhook_rejects_signature_of_other_channel_secret(
    client: AsyncClient, channel: uuid.UUID
) -> None:
    body = b"{}"
    response = await post_webhook(client, channel, body, signed(body, "secret-of-another-shop"))
    assert response.status_code == 401


async def test_webhook_rejects_tampered_body(client: AsyncClient, channel: uuid.UUID) -> None:
    signature = signed(b'{"entry":[]}')
    response = await post_webhook(client, channel, b'{"entry":[1]}', signature)
    assert response.status_code == 401


async def test_verify_handshake_returns_challenge(client: AsyncClient, channel: uuid.UUID) -> None:
    response = await client.get(
        f"/webhooks/whatsapp/{channel}",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-me",
            "hub.challenge": "1158201444",
        },
    )
    assert response.status_code == 200
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"},
        {"hub.challenge": "1"},
    ],
)
async def test_verify_handshake_rejects_wrong_token_or_mode(
    client: AsyncClient, channel: uuid.UUID, params: dict[str, str]
) -> None:
    response = await client.get(f"/webhooks/whatsapp/{channel}", params=params)
    assert response.status_code == 403
    assert "1" not in response.text.replace("verification_failed", "")


async def test_verify_token_of_one_channel_does_not_open_another(
    client: AsyncClient, channel: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await conn.scalar(text("INSERT INTO tenants (name) VALUES ('Б') RETURNING id"))
    other = await make_channel(
        owner_engine, tenant, type_="whatsapp", secret="other-token", credentials=CREDENTIALS
    )
    response = await client.get(
        f"/webhooks/whatsapp/{other}",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"},
    )
    assert response.status_code == 403


async def test_webhook_path_does_not_serve_other_channel_types(
    client: AsyncClient, owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        tenant = await conn.scalar(text("INSERT INTO tenants (name) VALUES ('В') RETURNING id"))
    telegram = await make_channel(owner_engine, tenant, type_="telegram")
    response = await client.get(f"/webhooks/whatsapp/{telegram}")
    assert response.status_code == 404


async def test_connect_encrypts_all_credentials(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, connect: dict[str, str]
) -> None:
    response = await client.post("/channels/whatsapp", json=connect)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["webhook_url"] == f"https://api.test/webhooks/whatsapp/{body['id']}"
    assert body["verify_token"]
    for secret in (ACCESS_TOKEN, APP_SECRET, connect["phone_number_id"]):
        assert secret not in response.text

    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT credentials_enc, external_id, name FROM channels WHERE id = :i"),
                {"i": body["id"]},
            )
        ).one()
    raw = bytes(row.credentials_enc)
    for secret in (ACCESS_TOKEN, APP_SECRET, connect["phone_number_id"], connect["waba_id"]):
        assert secret.encode() not in raw
    assert connect["phone_number_id"] not in row.external_id
    assert decrypt_json(raw) == connect


async def test_resaving_keys_keeps_verify_token_and_channel(
    client: AsyncClient, owner: uuid.UUID, connect: dict[str, str]
) -> None:
    first = (await client.post("/channels/whatsapp", json=connect)).json()
    second = (
        await client.post(
            "/channels/whatsapp", json={**connect, "access_token": ACCESS_TOKEN + "new"}
        )
    ).json()
    assert second["id"] == first["id"]
    assert second["verify_token"] == first["verify_token"]


async def test_number_of_other_shop_is_rejected(
    client: AsyncClient,
    owner: uuid.UUID,
    sender: FakeSender,
    owner_engine: AsyncEngine,
    connect: dict[str, str],
) -> None:
    assert (await client.post("/channels/whatsapp", json=connect)).status_code == 201
    _, _, phone = await create_user(owner_engine, tenant_name="Другой")
    await login(client, sender, phone)
    response = await client.post("/channels/whatsapp", json=connect)
    assert response.status_code == 409


@pytest.mark.parametrize(
    "patch",
    [
        {"phone_number_id": "../../me"},
        {"waba_id": "abc"},
        {"access_token": "short"},
        {"app_secret": "short"},
    ],
)
async def test_connect_validates_fields(
    client: AsyncClient, owner: uuid.UUID, connect: dict[str, str], patch: dict[str, str]
) -> None:
    response = await client.post("/channels/whatsapp", json={**connect, **patch})
    assert response.status_code == 422
