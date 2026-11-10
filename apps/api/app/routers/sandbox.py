import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.agent.runtime import Agent, get_agent
from app.agent.sandbox import autotest, sandbox_conversation
from app.auth.deps import Principal, require_role
from app.core.config import get_settings
from app.core.ratelimit import limit
from app.core.redis import get_redis
from app.llm import LLM, LLMError, get_llm

router = APIRouter(prefix="/sandbox", tags=["sandbox"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
AgentDep = Annotated[Agent, Depends(get_agent)]
RedisDep = Annotated[Redis, Depends(get_redis)]


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ChatOut(BaseModel):
    conversation_id: uuid.UUID
    reply: str | None
    human_mode: bool
    intent: str | None
    lang: str | None
    trace: list[dict[str, Any]]
    usage: list[dict[str, Any]]


class AutotestIn(BaseModel):
    count: int = Field(20, ge=1, le=30)


@router.post("/chat")
async def chat(body: ChatIn, principal: Member, agent: AgentDep, redis: RedisDep) -> ChatOut:
    per_hour = get_settings().sandbox_messages_per_hour
    await limit(redis, f"sandbox:chat:{principal.tenant_id}", per_hour, 3600)
    conversation_id = await sandbox_conversation(principal.tenant_id, body.session_id)
    turn = await agent.run(
        tenant_id=principal.tenant_id,
        conversation_id=conversation_id,
        text=body.message,
        sandbox=True,
    )
    return ChatOut(
        conversation_id=conversation_id,
        reply=turn.reply,
        human_mode=turn.human_mode,
        intent=turn.intent,
        lang=turn.lang,
        trace=turn.trace,
        usage=turn.usage,
    )


@router.post("/autotest")
async def run_autotest(
    principal: Member,
    agent: AgentDep,
    redis: RedisDep,
    llm: Annotated[LLM | None, Depends(get_llm)],
    body: AutotestIn | None = None,
) -> dict[str, Any]:
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "llm_unavailable")
    per_hour = get_settings().sandbox_autotests_per_hour
    await limit(redis, f"sandbox:autotest:{principal.tenant_id}", per_hour, 3600)
    try:
        return await autotest(agent, llm, principal.tenant_id, (body or AutotestIn()).count)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "llm_failed") from exc
