import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channels.gateway import FLUSH
from app.channels.registry import get_adapters
from app.channels.telegram import TelegramAdapter
from app.channels.types import (
    Button,
    ChannelConfig,
    ChannelError,
    Media,
    OutgoingMessage,
    ProductCard,
)
from app.core import crypto
from app.core.config import get_settings
from app.core.crypto import decrypt_json
from tests.channel_helpers import make_channel
from tests.conftest import FakeSender, RecordingQueue, create_user, login

FIXTURES = Path(__file__).parent / "fixtures" / "channels"
TOKEN = "123456:AAFakeTokenForTestsOnly_abcdefgh"
CONFIG = ChannelConfig(
    id=uuid.uuid4(),
    tenant_id=uuid.uuid4(),
    type="telegram",
    status="active",
    credentials={"token": TOKEN},
)


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


class FakeTelegram:
    def __init__(self, *, fail_photo: bool = False) -> None:
        self.fail_photo = fail_photo
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.bot_id = uuid.uuid4().int % 10**12

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/file/bot" in path:
            return httpx.Response(200, content=b"OGG-AUDIO")
        method = path.rsplit("/", 1)[-1]
        payload = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        if method == "sendPhoto" and self.fail_photo:
            return httpx.Response(
                400, json={"ok": False, "error_code": 400, "description": "wrong type of file"}
            )
        results: dict[str, Any] = {
            "getMe": {"id": self.bot_id, "is_bot": True, "username": "pion_bot"},
            "getFile": {"file_path": "voice/file_1.oga"},
        }
        return httpx.Response(200, json={"ok": True, "result": results.get(method, True)})

    def named(self, method: str) -> list[dict[str, Any]]:
        return [p for m, p in self.calls if m == method]


def adapter_for(fake: Callable[[httpx.Request], httpx.Response]) -> TelegramAdapter:
    async def no_sleep(_: float) -> None:
        return None

    return TelegramAdapter(httpx.MockTransport(fake), sleep=no_sleep)


@pytest.fixture
def telegram(app: FastAPI) -> FakeTelegram:
    fake = FakeTelegram()
    app.dependency_overrides[get_adapters] = lambda: {"telegram": adapter_for(fake)}
    return fake


def test_parse_text_message() -> None:
    [message] = TelegramAdapter().parse(CONFIG, fixture("telegram_text"))
    assert message.external_id == "900100"
    assert message.customer_external_id == "5551"
    assert message.text == "Есть белые пионы?"
    assert message.customer_name == "Айгерим С"
    assert message.channel_id == CONFIG.id


def test_parse_voice_message() -> None:
    [message] = TelegramAdapter().parse(CONFIG, fixture("telegram_voice"))
    assert message.text == ""
    assert message.media == [Media(file_id="AwACAgIAAxkBAAIB", mime_type="audio/ogg", size=18432)]


def test_parse_button_press_uses_payload_text() -> None:
    [message] = TelegramAdapter().parse(CONFIG, fixture("telegram_callback"))
    assert message.external_id == "cb:4382bfdwdsb323b2d9"
    assert message.customer_external_id == "5551"
    assert message.text == "Хочу заказать PN-004"


def test_parse_ignores_groups_and_unknown_buttons() -> None:
    assert TelegramAdapter().parse(CONFIG, fixture("telegram_group")) == []
    payload = fixture("telegram_callback")
    payload["callback_query"]["data"] = "evil:payload"
    assert TelegramAdapter().parse(CONFIG, payload) == []
    assert TelegramAdapter().parse(CONFIG, {"update_id": 1}) == []


def test_parse_attachment_and_start_command() -> None:
    [photo] = TelegramAdapter().parse(CONFIG, fixture("telegram_photo"))
    assert photo.text == "[покупатель отправил фото]"
    payload = fixture("telegram_text")
    payload["message"]["text"] = "/start promo"
    [start] = TelegramAdapter().parse(CONFIG, payload)
    assert start.text == "Здравствуйте"


async def test_send_splits_long_text_and_sends_photo_card() -> None:
    fake = FakeTelegram()
    message = OutgoingMessage(
        text="слово " * 1000,
        cards=[
            ProductCard(
                title="Пионы",
                caption="Пионы\n52 000 ₸",
                image_url="https://shop.kz/p.jpg",
                buttons=[Button(title="Заказать", payload="order:ru:PN-1")],
            )
        ],
    )
    await adapter_for(fake).send(CONFIG, "5551", message)

    texts = fake.named("sendMessage")
    assert len(texts) == 2
    assert all(len(t["text"]) <= 4096 and t["chat_id"] == "5551" for t in texts)
    [photo] = fake.named("sendPhoto")
    assert photo["photo"] == "https://shop.kz/p.jpg"
    assert photo["caption"] == "Пионы\n52 000 ₸"
    assert photo["reply_markup"] == {
        "inline_keyboard": [[{"text": "Заказать", "callback_data": "order:ru:PN-1"}]]
    }
    assert all("parse_mode" not in p for _, p in fake.calls)


async def test_card_falls_back_to_text_when_photo_is_rejected() -> None:
    fake = FakeTelegram(fail_photo=True)
    card = ProductCard(title="П", caption="П\n1 ₸", image_url="https://shop.kz/x.webp")
    await adapter_for(fake).send(CONFIG, "5551", OutgoingMessage(cards=[card]))
    assert [t["text"] for t in fake.named("sendMessage")] == ["П\n1 ₸"]


async def test_card_without_image_is_text() -> None:
    fake = FakeTelegram()
    card = ProductCard(title="П", caption="П\n1 ₸")
    await adapter_for(fake).send(CONFIG, "5551", OutgoingMessage(cards=[card]))
    assert fake.named("sendPhoto") == []
    assert len(fake.named("sendMessage")) == 1


async def test_network_errors_never_contain_token() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(ChannelError) as caught:
        await adapter_for(down).send(CONFIG, "1", OutgoingMessage(text="x"))
    assert TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None

    def broken_file(request: httpx.Request) -> httpx.Response:
        if "/file/bot" in request.url.path:
            raise httpx.ReadTimeout(f"timeout {request.url}")
        return FakeTelegram()(request)

    with pytest.raises(ChannelError) as caught:
        await adapter_for(broken_file).download(CONFIG, Media(file_id="f"))
    assert TOKEN not in str(caught.value)


async def test_retries_rate_limit_then_succeeds() -> None:
    attempts = []

    def limited(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, json={"ok": False})
        return httpx.Response(200, json={"ok": True, "result": True})

    await adapter_for(limited).send(CONFIG, "1", OutgoingMessage(text="x"))
    assert len(attempts) == 2


async def test_download_voice_and_reject_oversized() -> None:
    adapter = adapter_for(FakeTelegram())
    assert await adapter.download(CONFIG, Media(file_id="f")) == b"OGG-AUDIO"
    with pytest.raises(ChannelError):
        await adapter.download(CONFIG, Media(file_id="f", size=26 * 1024 * 1024))


async def test_button_press_is_acknowledged() -> None:
    fake = FakeTelegram()
    adapter = adapter_for(fake)
    [press] = adapter.parse(CONFIG, fixture("telegram_callback"))
    await adapter.acknowledge(CONFIG, press)
    assert fake.named("answerCallbackQuery") == [{"callback_query_id": "4382bfdwdsb323b2d9"}]
    [plain] = adapter.parse(CONFIG, fixture("telegram_text"))
    await adapter.acknowledge(CONFIG, plain)
    assert len(fake.calls) == 1


async def test_connect_sets_webhook_and_encrypts_token(
    client: AsyncClient, owner: uuid.UUID, telegram: FakeTelegram, owner_engine: AsyncEngine
) -> None:
    response = await client.post("/channels/telegram", json={"token": TOKEN})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "@pion_bot"
    assert body["status"] == "active"
    assert TOKEN not in response.text

    [hook] = telegram.named("setWebhook")
    assert hook["url"] == f"https://api.test/webhooks/telegram/{body['id']}"
    assert hook["allowed_updates"] == ["message", "callback_query"]

    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT credentials_enc, webhook_secret FROM channels WHERE id = :i"),
                {"i": body["id"]},
            )
        ).one()
    assert hook["secret_token"] == row.webhook_secret
    assert TOKEN.encode() not in bytes(row.credentials_enc)
    assert decrypt_json(bytes(row.credentials_enc)) == {"token": TOKEN}


async def test_reconnect_updates_same_channel_with_new_secret(
    client: AsyncClient, owner: uuid.UUID, telegram: FakeTelegram
) -> None:
    first = await client.post("/channels/telegram", json={"token": TOKEN})
    second = await client.post("/channels/telegram", json={"token": TOKEN})
    assert first.json()["id"] == second.json()["id"]
    secrets = [h["secret_token"] for h in telegram.named("setWebhook")]
    assert secrets[0] != secrets[1]
    assert len((await client.get("/channels")).json()) == 1


async def test_other_shop_cannot_take_connected_bot(
    client: AsyncClient,
    owner: uuid.UUID,
    telegram: FakeTelegram,
    sender: FakeSender,
    owner_engine: AsyncEngine,
) -> None:
    assert (await client.post("/channels/telegram", json={"token": TOKEN})).status_code == 201
    _, _, phone = await create_user(owner_engine, tenant_name="Другой")
    await login(client, sender, phone)
    response = await client.post("/channels/telegram", json={"token": TOKEN})
    assert response.status_code == 409
    assert response.json()["detail"] == "channel_in_use"
    assert len(telegram.named("setWebhook")) == 1


@pytest.mark.parametrize("token", ["nope", "123:short", "123:AAAAAAAAAAAAAAAAAAAAAAAA/../x"])
async def test_connect_rejects_malformed_token(
    client: AsyncClient, owner: uuid.UUID, telegram: FakeTelegram, token: str
) -> None:
    response = await client.post("/channels/telegram", json={"token": token})
    assert response.status_code == 400
    assert telegram.calls == []


async def test_connect_requires_https_public_url(
    client: AsyncClient,
    owner: uuid.UUID,
    telegram: FakeTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "public_api_url", "http://localhost:8100")
    response = await client.post("/channels/telegram", json={"token": TOKEN})
    assert response.status_code == 400
    assert response.json()["detail"] == "public_url_not_https"


async def test_token_rejected_by_telegram_creates_no_channel(
    client: AsyncClient, owner: uuid.UUID, app: FastAPI
) -> None:
    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
        )

    app.dependency_overrides[get_adapters] = lambda: {"telegram": adapter_for(unauthorized)}
    response = await client.post("/channels/telegram", json={"token": TOKEN})
    assert response.status_code == 400
    assert (await client.get("/channels")).json() == []


async def test_placeholder_fernet_key_gives_clear_error(
    client: AsyncClient,
    owner: uuid.UUID,
    telegram: FakeTelegram,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "fernet_key", SecretStr("change-me"))
    crypto._fernet.cache_clear()
    try:
        response = await client.post("/channels/telegram", json={"token": TOKEN})
    finally:
        crypto._fernet.cache_clear()
    assert response.status_code == 503
    assert response.json()["detail"] == "encryption_not_configured"


async def test_manager_cannot_manage_channels(
    client: AsyncClient,
    owner: uuid.UUID,
    sender: FakeSender,
    owner_engine: AsyncEngine,
    telegram: FakeTelegram,
) -> None:
    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)
    assert (await client.get("/channels")).status_code == 403
    assert (await client.post("/channels/telegram", json={"token": TOKEN})).status_code == 403


async def test_check_reports_bad_token(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, app: FastAPI
) -> None:
    channel_id = await make_channel(owner_engine, owner, credentials={"token": TOKEN})

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
        )

    app.dependency_overrides[get_adapters] = lambda: {"telegram": adapter_for(unauthorized)}
    response = await client.post(f"/channels/{channel_id}/check")
    assert response.json()["ok"] is False
    assert "Токен" in response.json()["error"]
    [row] = (await client.get("/channels")).json()
    assert row["status"] == "error"


async def test_check_is_scoped_to_tenant(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, telegram: FakeTelegram
) -> None:
    other = await owner_engine.connect()
    tenant = await other.scalar(text("INSERT INTO tenants (name) VALUES ('Чужой') RETURNING id"))
    await other.commit()
    await other.close()
    channel_id = await make_channel(owner_engine, tenant, credentials={"token": TOKEN})
    assert (await client.post(f"/channels/{channel_id}/check")).status_code == 404
    assert telegram.calls == []


async def _hook(
    client: AsyncClient, channel_id: uuid.UUID, payload: Any, secret: str | None = "s3cret"
) -> httpx.Response:
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
    return await client.post(f"/webhooks/telegram/{channel_id}", json=payload, headers=headers)


@pytest.fixture
async def channel(owner_engine: AsyncEngine, client: AsyncClient) -> uuid.UUID:
    async with owner_engine.begin() as conn:
        tenant = await conn.scalar(text("INSERT INTO tenants (name) VALUES ('Т') RETURNING id"))
    return await make_channel(owner_engine, tenant, secret="s3cret", credentials={"token": TOKEN})


async def test_webhook_rejects_wrong_or_missing_secret(
    client: AsyncClient, channel: uuid.UUID, queue: RecordingQueue
) -> None:
    payload = fixture("telegram_text")
    assert (await _hook(client, channel, payload, "wrong")).status_code == 401
    assert (await _hook(client, channel, payload, None)).status_code == 401
    assert queue.jobs == []


async def test_webhook_unknown_channel_is_404(client: AsyncClient) -> None:
    response = await _hook(client, uuid.uuid4(), fixture("telegram_text"))
    assert response.status_code == 404


async def test_webhook_queues_message_and_dedups_retries(
    client: AsyncClient, channel: uuid.UUID, queue: RecordingQueue
) -> None:
    payload = fixture("telegram_text")
    assert (await _hook(client, channel, payload)).status_code == 200
    assert (await _hook(client, channel, payload)).status_code == 200
    assert [name for name, _ in queue.jobs] == [FLUSH]


async def test_webhook_acknowledges_garbage_without_queueing(
    client: AsyncClient, channel: uuid.UUID, queue: RecordingQueue
) -> None:
    response = await client.post(
        f"/webhooks/telegram/{channel}",
        content=b"not json",
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert response.status_code == 200
    assert queue.jobs == []


async def test_webhook_rejects_oversized_body(client: AsyncClient, channel: uuid.UUID) -> None:
    response = await client.post(
        f"/webhooks/telegram/{channel}",
        content=b"x" * (2 * 1024 * 1024 + 1),
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert response.status_code == 413


async def test_disabled_channel_acknowledges_but_does_not_queue(
    client: AsyncClient, owner_engine: AsyncEngine, channel: uuid.UUID, queue: RecordingQueue
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE channels SET status = 'disabled' WHERE id = :c"), {"c": channel}
        )
    assert (await _hook(client, channel, fixture("telegram_text"))).status_code == 200
    assert queue.jobs == []
