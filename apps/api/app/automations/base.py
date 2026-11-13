import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.period import timezone
from app.billing.alerts import send_owner_message
from app.channels.outbound import Outbound
from app.channels.types import ChannelAdapter
from app.core.config import get_settings
from app.models import Notification

Recipients = Literal["owner", "team"]
ROLES: dict[str, tuple[str, ...]] = {"owner": ("owner",), "team": ("owner", "manager")}


class PreviewItem(BaseModel):
    title: str
    detail: str | None = None
    href: str | None = None


class Preview(BaseModel):
    summary: str
    text: str | None = None
    items: list[PreviewItem] = []


@dataclass
class Outcome:
    status: Literal["ok", "empty"]
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Deps:
    redis: Any
    adapters: Mapping[str, ChannelAdapter]
    outbound: Outbound
    remember: Callable[[uuid.UUID, str], Awaitable[None]] | None = None


@dataclass
class Context:
    session: AsyncSession
    tenant_id: uuid.UUID
    now: datetime
    state: dict[str, Any]
    deps: Deps
    trigger: str = "schedule"

    @property
    def local(self) -> datetime:
        return self.now.astimezone(timezone())

    @property
    def manual(self) -> bool:
        return self.trigger == "manual"

    async def tell(self, text: str, recipients: str) -> int:
        return await send_owner_message(self.tenant_id, text, self.deps.adapters, ROLES[recipients])

    def note(self, kind: str, text: str, details: dict[str, Any] | None = None) -> None:
        self.session.add(
            Notification(tenant_id=self.tenant_id, kind=kind, text=text, details=details or {})
        )


def web_url(path: str) -> str:
    return get_settings().public_web_url.rstrip("/") + path


def plural(count: int, one: str, few: str, many: str) -> str:
    tail, tens = count % 10, count % 100
    if tail == 1 and tens != 11:
        return one
    if 2 <= tail <= 4 and not 12 <= tens <= 14:
        return few
    return many


class Service[S: BaseModel]:
    kind: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str]
    default_enabled: ClassVar[bool] = False
    settings_model: type[S]

    def due(
        self, settings: S, state: dict[str, Any], last_run_at: datetime | None, ctx_now: datetime
    ) -> bool:
        return True

    async def preview(self, ctx: Context, settings: S) -> Preview:
        raise NotImplementedError

    async def run(self, ctx: Context, settings: S) -> Outcome:
        raise NotImplementedError
