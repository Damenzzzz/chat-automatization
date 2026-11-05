import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.channels.http import MAX_AUDIO_BYTES, ChannelHttp
from app.channels.outgoing import button_text, clip, split_text
from app.channels.types import (
    ChannelConfig,
    ChannelError,
    CheckResult,
    IncomingMessage,
    Media,
    OutgoingMessage,
    ProductCard,
)
from app.core.config import get_settings

GRAPH = "https://graph.facebook.com"
SIGNATURE_PREFIX = "sha256="
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
ATTACHMENTS = {
    "image": "фото",
    "video": "видео",
    "document": "файл",
    "sticker": "стикер",
    "location": "геолокацию",
    "contacts": "контакт",
}
CHECK_ERRORS = {
    190: "Токен недействителен или истёк: выпустите постоянный токен заново (шаг 5 инструкции).",
    100: "Phone number ID не найден или у токена нет к нему доступа: проверьте ID (шаг 4) "
    "и права токена (шаг 5).",
    10: "У токена нет прав: нужны whatsapp_business_messaging и whatsapp_business_management "
    "(шаг 5 инструкции).",
    200: "У токена нет прав: нужны whatsapp_business_messaging и whatsapp_business_management "
    "(шаг 5 инструкции).",
}


class GraphApiError(ChannelError):
    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(f"whatsapp: {message}")
        self.code = code


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix(SIGNATURE_PREFIX))


def _interactive_text(block: dict[str, Any]) -> str:
    reply = block.get("button_reply") or block.get("list_reply") or {}
    return button_text(str(reply.get("id", ""))) or str(reply.get("title", ""))


class WhatsAppAdapter:
    type = "whatsapp"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, **http: Any) -> None:
        self.http = ChannelHttp("whatsapp", transport=transport, **http)

    def _url(self, path: str) -> str:
        return f"{GRAPH}/{get_settings().whatsapp_graph_version}/{path}"

    async def _call(self, channel: ChannelConfig, method: str, path: str, **kwargs: Any) -> Any:
        token = channel.credentials["access_token"]
        response = await self.http.request(
            method, self._url(path), headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        try:
            body = response.json()
        except ValueError:
            raise ChannelError(f"whatsapp: неверный ответ (HTTP {response.status_code})") from None
        if response.is_error:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise GraphApiError(error.get("code"), str(error.get("message", response.status_code)))
        return body

    async def _message(self, channel: ChannelConfig, payload: dict[str, Any]) -> None:
        path = f"{quote(channel.credentials['phone_number_id'], safe='')}/messages"
        await self._call(channel, "POST", path, json={"messaging_product": "whatsapp", **payload})

    def parse(self, channel: ChannelConfig, payload: dict[str, Any]) -> list[IncomingMessage]:
        result = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                if metadata.get("phone_number_id") != channel.credentials.get("phone_number_id"):
                    continue
                names = {
                    c.get("wa_id"): c.get("profile", {}).get("name")
                    for c in value.get("contacts", [])
                }
                for message in value.get("messages", []):
                    parsed = self._parse_message(channel, message, names)
                    if parsed:
                        result.append(parsed)
        return result

    def _parse_message(
        self, channel: ChannelConfig, message: dict[str, Any], names: dict[Any, Any]
    ) -> IncomingMessage | None:
        kind = message.get("type")
        text, media = "", []
        if kind == "text":
            text = message.get("text", {}).get("body", "")
        elif kind == "audio":
            audio = message["audio"]
            media.append(Media(file_id=audio["id"], mime_type=audio.get("mime_type")))
        elif kind == "interactive":
            text = _interactive_text(message["interactive"])
        elif kind == "button":
            text = message.get("button", {}).get("text", "")
        elif kind in ATTACHMENTS:
            text = message.get(kind, {}).get("caption", "") if kind != "contacts" else ""
            text = text or f"[покупатель отправил {ATTACHMENTS[kind]}]"
        if not text and not media:
            return None
        return IncomingMessage(
            channel_id=channel.id,
            external_id=message["id"],
            customer_external_id=message["from"],
            text=text,
            media=media,
            received_at=datetime.fromtimestamp(int(message["timestamp"]), UTC),
            customer_name=names.get(message["from"]),
        )

    async def send(
        self, channel: ChannelConfig, customer_external_id: str, message: OutgoingMessage
    ) -> None:
        base = {"recipient_type": "individual", "to": customer_external_id}
        for chunk in split_text(message.text, TEXT_LIMIT):
            await self._message(
                channel, {**base, "type": "text", "text": {"body": chunk, "preview_url": False}}
            )
        for card in message.cards:
            await self._send_card(channel, base, card)

    async def _send_card(
        self, channel: ChannelConfig, base: dict[str, str], card: ProductCard
    ) -> None:
        if card.image_url:
            image = {"link": card.image_url, "caption": clip(card.caption, CAPTION_LIMIT)}
            await self._message(channel, {**base, "type": "image", "image": image})
            return
        body = {"body": clip(card.caption, TEXT_LIMIT), "preview_url": False}
        await self._message(channel, {**base, "type": "text", "text": body})

    async def download(self, channel: ChannelConfig, media: Media) -> bytes:
        info = await self._call(channel, "GET", quote(media.file_id, safe=""))
        if int(info.get("file_size") or 0) > MAX_AUDIO_BYTES:
            raise ChannelError("whatsapp: файл слишком большой")
        token = channel.credentials["access_token"]
        return await self.http.download(info["url"], headers={"Authorization": f"Bearer {token}"})

    async def acknowledge(self, channel: ChannelConfig, message: IncomingMessage) -> None:
        await self._message(channel, {"status": "read", "message_id": message.external_id})

    async def check(self, channel: ChannelConfig) -> CheckResult:
        path = quote(channel.credentials["phone_number_id"], safe="")
        try:
            info = await self._call(
                channel, "GET", path, params={"fields": "verified_name,display_phone_number"}
            )
        except GraphApiError as exc:
            known = CHECK_ERRORS.get(exc.code or 0)
            return CheckResult(ok=False, error=known or f"Meta ответила ошибкой: {exc}")
        except ChannelError as exc:
            return CheckResult(ok=False, error=f"Meta не отвечает, повторите позже ({exc})")
        name = info.get("verified_name") or info.get("display_phone_number")
        return CheckResult(ok=True, display_name=name)
