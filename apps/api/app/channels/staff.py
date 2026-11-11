import uuid
from collections.abc import Mapping
from typing import Any

from app.agent.prompt import money
from app.billing.alerts import send_owner_message
from app.channels.types import ChannelAdapter
from app.core.config import get_settings

WAITING_TTL = 600
STAFF_ROLES = ("owner", "manager")


def staff_text(event: str, payload: Mapping[str, Any]) -> str | None:
    web = get_settings().public_web_url.rstrip("/")
    dialog = f"{web}/dialogs?id={payload.get('conversation_id')}"
    if event == "lead.created":
        return f"Новая заявка на {money(int(payload.get('total_kzt') or 0))}.\n{web}/leads"
    if event == "lead.stale":
        total = money(int(payload.get("total_kzt") or 0))
        return (
            f"Заявка на {total} ждёт ответа уже {payload.get('hours')} ч.\n{web}/leads?status=new"
        )
    if event == "handoff":
        reason = str(payload.get("reason") or "").strip()[:200]
        return f"Бот передал диалог менеджеру{': ' + reason if reason else ''}.\n{dialog}"
    if event == "customer_message":
        return f"Покупатель ждёт ответа менеджера.\n{dialog}"
    if event == "turn_failed":
        return f"Бот не смог ответить покупателю, диалог ждёт менеджера.\n{dialog}"
    return None


async def notify_staff(
    redis: Any,
    tenant_id: uuid.UUID,
    event: str,
    payload: Mapping[str, Any],
    adapters: Mapping[str, ChannelAdapter],
) -> int:
    text = staff_text(event, payload)
    if text is None:
        return 0
    if event == "customer_message":
        key = f"notify:waiting:{payload.get('conversation_id')}"
        if not await redis.set(key, "1", nx=True, ex=WAITING_TTL):
            return 0
    return await send_owner_message(tenant_id, text, adapters, roles=STAFF_ROLES)
