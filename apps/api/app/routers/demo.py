import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.agent.runtime import Agent, get_agent
from app.agent.sandbox import sandbox_conversation
from app.auth.deps import get_refresh_store
from app.auth.tokens import RefreshStore
from app.core.config import get_settings
from app.core.queue import Queue, get_queue
from app.core.redis import get_redis
from app.demo.service import demo_owner, ensure_demo_shop, mentioned_products
from app.routers.auth import SessionOut, start_session
from app.seed import DEMO_TENANT_ID

router = APIRouter(prefix="/demo", tags=["demo"])

RedisDep = Annotated[Redis, Depends(get_redis)]
AgentDep = Annotated[Agent, Depends(get_agent)]
QueueDep = Annotated[Queue, Depends(get_queue)]

LOGIN_PER_MINUTE = 10
CHAT_PER_MINUTE = 12
CHAT_PER_HOUR = 60


class DemoStatus(BaseModel):
    enabled: bool
    shop_name: str = "Цветы Пион"


class DemoChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class DemoCard(BaseModel):
    id: uuid.UUID
    name: str
    sku: str | None
    price: int | None
    stock: int | None
    category: str | None


class DemoChatOut(BaseModel):
    reply: str | None
    lang: str | None
    intent: str | None
    human_mode: bool
    cards: list[DemoCard]


def require_demo() -> None:
    if not get_settings().demo_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demo_disabled")


async def limit(redis: Redis, key: str, count: int, window: int) -> None:
    bucket = f"ratelimit:demo:{key}:{int(time.time() // window)}"
    pipe = redis.pipeline(transaction=True)
    pipe.incr(bucket)
    pipe.expire(bucket, window * 2)
    hits, _ = await pipe.execute()
    if hits > count:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too_many_requests",
            headers={"Retry-After": str(window)},
        )


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("")
async def demo_status() -> DemoStatus:
    return DemoStatus(enabled=get_settings().demo_enabled)


@router.post("/login", dependencies=[Depends(require_demo)])
async def demo_login(
    request: Request,
    response: Response,
    redis: RedisDep,
    queue: QueueDep,
    store: Annotated[RefreshStore, Depends(get_refresh_store)],
) -> SessionOut:
    await limit(redis, f"login:{client_ip(request)}", LOGIN_PER_MINUTE, 60)
    await ensure_demo_shop(queue)
    return await start_session(response, await demo_owner(), store)


@router.post("/chat", dependencies=[Depends(require_demo)])
async def demo_chat(
    body: DemoChatIn, request: Request, redis: RedisDep, queue: QueueDep, agent: AgentDep
) -> DemoChatOut:
    ip = client_ip(request)
    await limit(redis, f"chat:{ip}", CHAT_PER_MINUTE, 60)
    await limit(redis, f"chat-hour:{ip}", CHAT_PER_HOUR, 3600)
    await ensure_demo_shop(queue)
    conversation_id = await sandbox_conversation(DEMO_TENANT_ID, f"landing-{body.session_id}")
    turn = await agent.run(
        tenant_id=DEMO_TENANT_ID,
        conversation_id=conversation_id,
        text=body.message,
        sandbox=True,
    )
    cards = await mentioned_products(turn.reply) if turn.reply else []
    return DemoChatOut(
        reply=turn.reply,
        lang=turn.lang,
        intent=turn.intent,
        human_mode=turn.human_mode,
        cards=[DemoCard(**card.__dict__) for card in cards],
    )
