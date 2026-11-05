import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channels.gateway import FLUSH, buffer_key, customer_key
from app.channels.types import (
    ChannelConfig,
    ChannelError,
    IncomingMessage,
    Media,
    OutgoingMessage,
    ProductCard,
)
from app.channels.whatsapp import WhatsAppAdapter, verify_signature
from app.core.config import get_settings
from app.core.crypto import decrypt_json
from tests.channel_helpers import make_channel
from tests.conftest import FakeSender, RecordingQueue, create_user, login

FIXTURES = Path(__file__).parent / "fixtures" / "channels"
APP_SECRET = "0123456789abcdef0123456789abcdef"
ACCESS_TOKEN = "EAAFakeAccessTokenForTestsOnly1234567890"
PHONE_ID = "106540352242922"
CREDENTIALS = {
    "phone_number_id": PHONE_ID,
    "waba_id": "102290129340398",
    "access_token": ACCESS_TOKEN,
    "app_secret": APP_SECRET,
}


CONFIG = ChannelConfig(
    id=uuid.uuid4(),
    tenant_id=uuid.uuid4(),
    type="whatsapp",
    status="active",
    credentials=CREDENTIALS,
)


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


class FakeGraph:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "lookaside.fbsbx.com":
            return httpx.Response(200, content=b"OGG-AUDIO")
        if request.method == "GET" and request.url.path.endswith("/1037543291543636"):
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1",
                    "mime_type": "audio/ogg",
                    "file_size": 1024,
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"verified_name": "Цветы Пион", "display_phone_number": "+7 700 123 45 67"},
            )
        return httpx.Response(200, json={"messages": [{"id": "wamid.OUT"}], "success": True})

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]


def adapter_for(fake: Callable[[httpx.Request], httpx.Response]) -> WhatsAppAdapter:
    async def no_sleep(_: float) -> None:
        return None

    return WhatsAppAdapter(httpx.MockTransport(fake), sleep=no_sleep)


def graph_error(code: int, message: str = "boom", status: int = 400) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


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


def test_parse_text_with_customer_name() -> None:
    [message] = WhatsAppAdapter().parse(CONFIG, fixture("whatsapp_text"))
    assert message.external_id == "wamid.TEXT1"
    assert message.customer_external_id == "77011112233"
    assert message.text == "Сколько стоят белые пионы?"
    assert message.customer_name == "Динара"


def test_parse_audio_as_media() -> None:
    [message] = WhatsAppAdapter().parse(CONFIG, fixture("whatsapp_audio"))
    assert message.text == ""
    assert message.media == [Media(file_id="1037543291543636", mime_type="audio/ogg; codecs=opus")]


def test_parse_interactive_button_and_list() -> None:
    [button] = WhatsAppAdapter().parse(CONFIG, fixture("whatsapp_button"))
    assert button.text == "PN-004 тапсырыс бергім келеді"
    [row] = WhatsAppAdapter().parse(CONFIG, fixture("whatsapp_list"))
    assert row.text == "Доставка завтра"


def test_parse_attachment_placeholder() -> None:
    [image] = WhatsAppAdapter().parse(CONFIG, fixture("whatsapp_image"))
    assert image.text == "[покупатель отправил фото]"


def test_parse_ignores_statuses_and_other_numbers() -> None:
    assert WhatsAppAdapter().parse(CONFIG, fixture("whatsapp_status")) == []
    assert WhatsAppAdapter().parse(CONFIG, fixture("whatsapp_other_number")) == []
    assert WhatsAppAdapter().parse(CONFIG, {}) == []


async def test_send_text_and_image_card_via_graph_api() -> None:
    fake = FakeGraph()
    card = ProductCard(title="П", caption="Пионы\n52 000 ₸", image_url="https://shop.kz/p.jpg")
    plain = ProductCard(title="Р", caption="Розы\n1 000 ₸")
    await adapter_for(fake).send(
        CONFIG, "77011112233", OutgoingMessage(text="Есть!", cards=[card, plain])
    )

    version = get_settings().whatsapp_graph_version
    assert str(fake.requests[0].url) == (
        f"https://graph.facebook.com/{version}/{PHONE_ID}/messages"
    )
    assert fake.requests[0].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    text_body, image_body, plain_body = fake.bodies()
    assert text_body == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "77011112233",
        "type": "text",
        "text": {"body": "Есть!", "preview_url": False},
    }
    assert image_body["type"] == "image"
    assert image_body["image"] == {
        "link": "https://shop.kz/p.jpg",
        "caption": "Пионы\n52 000 ₸",
    }
    assert plain_body["text"]["body"] == "Розы\n1 000 ₸"


async def test_graph_version_comes_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "whatsapp_graph_version", "v99.0")
    fake = FakeGraph()
    await adapter_for(fake).send(CONFIG, "1", OutgoingMessage(text="x"))
    assert "/v99.0/" in str(fake.requests[0].url)


async def test_long_text_and_caption_are_cut_to_limits() -> None:
    fake = FakeGraph()
    card = ProductCard(title="П", caption="о" * 2000, image_url="https://shop.kz/p.jpg")
    await adapter_for(fake).send(CONFIG, "1", OutgoingMessage(text="слово " * 1000, cards=[card]))
    bodies = fake.bodies()
    assert all(len(b["text"]["body"]) <= 4096 for b in bodies if b["type"] == "text")
    assert len(bodies[-1]["image"]["caption"]) <= 1024


async def test_mark_as_read() -> None:
    fake = FakeGraph()
    [message] = WhatsAppAdapter().parse(CONFIG, fixture("whatsapp_text"))
    await adapter_for(fake).acknowledge(CONFIG, message)
    assert fake.bodies() == [
        {"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.TEXT1"}
    ]


async def test_download_audio_in_two_steps() -> None:
    fake = FakeGraph()
    data = await adapter_for(fake).download(CONFIG, Media(file_id="1037543291543636"))
    assert data == b"OGG-AUDIO"
    assert fake.requests[1].url.host == "lookaside.fbsbx.com"
    assert fake.requests[1].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"


async def test_send_error_has_meta_message_but_no_token() -> None:
    def rejected(request: httpx.Request) -> httpx.Response:
        return graph_error(131047, "Re-engagement message")

    with pytest.raises(ChannelError) as caught:
        await adapter_for(rejected).send(CONFIG, "1", OutgoingMessage(text="x"))
    assert "Re-engagement" in str(caught.value)
    assert ACCESS_TOKEN not in str(caught.value)


async def test_check_returns_display_name() -> None:
    result = await adapter_for(FakeGraph()).check(CONFIG)
    assert result.ok and result.display_name == "Цветы Пион"


@pytest.mark.parametrize(
    ("code", "expected"),
    [(190, "Токен"), (100, "Phone number ID"), (200, "прав"), (368, "Meta ответила")],
)
async def test_check_explains_graph_errors(code: int, expected: str) -> None:
    result = await adapter_for(lambda _: graph_error(code)).check(CONFIG)
    assert not result.ok
    assert result.error is not None and expected in result.error


async def test_check_explains_network_failure() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route {request.url}")

    result = await adapter_for(down).check(CONFIG)
    assert not result.ok
    assert result.error is not None and "Meta не отвечает" in result.error


async def test_check_endpoint_activates_channel_and_stores_name(
    client: AsyncClient, owner: uuid.UUID, app: Any, connect: dict[str, str]
) -> None:
    from app.channels.registry import get_adapters

    app.dependency_overrides[get_adapters] = lambda: {"whatsapp": adapter_for(FakeGraph())}
    created = (await client.post("/channels/whatsapp", json=connect)).json()

    response = await client.post(f"/channels/{created['id']}/check")

    assert response.json() == {"ok": True, "display_name": "Цветы Пион", "error": None}
    [row] = (await client.get("/channels")).json()
    assert row["status"] == "active"
    assert row["name"] == "Цветы Пион"


async def test_check_endpoint_reports_error_and_keeps_it(
    client: AsyncClient, owner: uuid.UUID, app: Any, connect: dict[str, str]
) -> None:
    from app.channels.registry import get_adapters

    fake = adapter_for(lambda _: graph_error(190, "expired", 401))
    app.dependency_overrides[get_adapters] = lambda: {"whatsapp": fake}
    created = (await client.post("/channels/whatsapp", json=connect)).json()

    response = await client.post(f"/channels/{created['id']}/check")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    [row] = (await client.get("/channels")).json()
    assert row["status"] == "error"
    assert "Токен" in row["last_error"]


async def test_signed_webhook_queues_text_once(
    client: AsyncClient, channel: uuid.UUID, queue: RecordingQueue, redis: Any
) -> None:
    body = json.dumps(fixture("whatsapp_text")).encode()
    for _ in range(2):
        assert (await post_webhook(client, channel, body, signed(body))).status_code == 200

    assert [name for name, _ in queue.jobs] == [FLUSH]
    [raw] = await redis.lrange(buffer_key(channel, customer_key("77011112233")), 0, -1)
    assert IncomingMessage.model_validate_json(raw).text == "Сколько стоят белые пионы?"


async def test_delivery_status_webhook_queues_nothing(
    client: AsyncClient, channel: uuid.UUID, queue: RecordingQueue
) -> None:
    body = json.dumps(fixture("whatsapp_status")).encode()
    assert (await post_webhook(client, channel, body, signed(body))).status_code == 200
    assert queue.jobs == []
