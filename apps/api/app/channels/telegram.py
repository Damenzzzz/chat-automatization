import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.channels.http import MAX_AUDIO_BYTES, ChannelHttp
from app.channels.outgoing import button_text, clip, split_text
from app.channels.types import (
    Button,
    ChannelConfig,
    ChannelError,
    CheckResult,
    IncomingMessage,
    Media,
    OutgoingMessage,
    ProductCard,
)

API = "https://api.telegram.org"
TOKEN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
CALLBACK_PREFIX = "cb:"
ATTACHMENTS = {
    "photo": "фото",
    "video": "видео",
    "video_note": "видео",
    "document": "файл",
    "sticker": "стикер",
    "location": "геолокацию",
    "contact": "контакт",
}


class TelegramApiError(ChannelError):
    def __init__(self, code: int | None, description: str) -> None:
        super().__init__(f"telegram: {description}")
        self.code = code


def _keyboard(buttons: list[Button]) -> dict[str, Any]:
    rows = [[{"text": b.title, "callback_data": b.payload}] for b in buttons]
    return {"inline_keyboard": rows}


def _full_name(sender: dict[str, Any]) -> str | None:
    parts = [sender.get("first_name"), sender.get("last_name")]
    return " ".join(p for p in parts if p) or None


class TelegramAdapter:
    type = "telegram"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, **http: Any) -> None:
        self.http = ChannelHttp("telegram", transport=transport, **http)

    async def call(self, token: str, method: str, **payload: Any) -> Any:
        response = await self.http.request("POST", f"{API}/bot{token}/{method}", json=payload)
        try:
            body = response.json()
        except ValueError:
            raise ChannelError(f"telegram: неверный ответ (HTTP {response.status_code})") from None
        if not body.get("ok"):
            raise TelegramApiError(body.get("error_code"), str(body.get("description", "ошибка")))
        return body["result"]

    async def get_me(self, token: str) -> dict[str, Any]:
        me: dict[str, Any] = await self.call(token, "getMe")
        return me

    async def set_webhook(self, token: str, url: str, secret: str) -> None:
        await self.call(
            token,
            "setWebhook",
            url=url,
            secret_token=secret,
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
        )

    def parse(self, channel: ChannelConfig, payload: dict[str, Any]) -> list[IncomingMessage]:
        callback = payload.get("callback_query")
        if callback:
            return self._parse_callback(channel, callback)
        message = payload.get("message")
        if not message or message.get("chat", {}).get("type") != "private":
            return []
        sender = message.get("from", {})
        if sender.get("is_bot"):
            return []
        text = message.get("text") or message.get("caption") or ""
        audio = message.get("voice") or message.get("audio")
        media = []
        if audio:
            media.append(
                Media(
                    file_id=audio["file_id"],
                    mime_type=audio.get("mime_type"),
                    size=audio.get("file_size"),
                )
            )
        if text.startswith("/start"):
            text = "Здравствуйте"
        if not text and not media:
            kind = next((v for k, v in ATTACHMENTS.items() if k in message), None)
            if kind is None:
                return []
            text = f"[покупатель отправил {kind}]"
        return [
            IncomingMessage(
                channel_id=channel.id,
                external_id=str(payload["update_id"]),
                customer_external_id=str(message["chat"]["id"]),
                text=text,
                media=media,
                received_at=datetime.fromtimestamp(message["date"], UTC),
                customer_name=_full_name(sender),
            )
        ]

    def _parse_callback(
        self, channel: ChannelConfig, callback: dict[str, Any]
    ) -> list[IncomingMessage]:
        chat = callback.get("message", {}).get("chat", {})
        text = button_text(str(callback.get("data", "")))
        if chat.get("type") != "private" or text is None:
            return []
        return [
            IncomingMessage(
                channel_id=channel.id,
                external_id=f"{CALLBACK_PREFIX}{callback['id']}",
                customer_external_id=str(chat["id"]),
                text=text,
                received_at=datetime.now(UTC),
                customer_name=_full_name(callback.get("from", {})),
            )
        ]

    async def send(
        self, channel: ChannelConfig, customer_external_id: str, message: OutgoingMessage
    ) -> None:
        token = channel.credentials["token"]
        chunks = split_text(message.text, TEXT_LIMIT)
        for index, chunk in enumerate(chunks):
            extra = {}
            if message.buttons and index == len(chunks) - 1:
                extra["reply_markup"] = _keyboard(message.buttons)
            await self.call(token, "sendMessage", chat_id=customer_external_id, text=chunk, **extra)
        for card in message.cards:
            await self._send_card(token, customer_external_id, card)

    async def _send_card(self, token: str, chat_id: str, card: ProductCard) -> None:
        extra = {"reply_markup": _keyboard(card.buttons)} if card.buttons else {}
        if card.image_url:
            try:
                await self.call(
                    token,
                    "sendPhoto",
                    chat_id=chat_id,
                    photo=card.image_url,
                    caption=clip(card.caption, CAPTION_LIMIT),
                    **extra,
                )
                return
            except TelegramApiError as exc:
                if exc.code != 400:
                    raise
        await self.call(
            token, "sendMessage", chat_id=chat_id, text=clip(card.caption, TEXT_LIMIT), **extra
        )

    async def download(self, channel: ChannelConfig, media: Media) -> bytes:
        token = channel.credentials["token"]
        if media.size and media.size > MAX_AUDIO_BYTES:
            raise ChannelError("telegram: файл слишком большой")
        info = await self.call(token, "getFile", file_id=media.file_id)
        return await self.http.download(f"{API}/file/bot{token}/{info['file_path']}")

    async def typing(self, channel: ChannelConfig, customer_external_id: str) -> None:
        await self.call(
            channel.credentials["token"],
            "sendChatAction",
            chat_id=customer_external_id,
            action="typing",
        )

    async def acknowledge(self, channel: ChannelConfig, message: IncomingMessage) -> None:
        if message.external_id.startswith(CALLBACK_PREFIX):
            await self.call(
                channel.credentials["token"],
                "answerCallbackQuery",
                callback_query_id=message.external_id.removeprefix(CALLBACK_PREFIX),
            )

    async def check(self, channel: ChannelConfig) -> CheckResult:
        try:
            me = await self.get_me(channel.credentials["token"])
        except TelegramApiError as exc:
            if exc.code == 401:
                return CheckResult(ok=False, error="Токен бота недействителен: выпустите новый.")
            return CheckResult(ok=False, error=str(exc))
        except ChannelError as exc:
            return CheckResult(ok=False, error=str(exc))
        return CheckResult(ok=True, display_name=f"@{me.get('username')}")
