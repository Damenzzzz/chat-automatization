import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

import structlog
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import MAX_RETRIES, MAX_TOOL_HOPS
from app.agent.guard import check_reply
from app.agent.llmcall import call_llm
from app.agent.prompt import load_profile
from app.agent.respond import FALLBACK, ai_message, build_messages, pick_model, tool_message
from app.agent.session import new_session
from app.agent.state import ChatState, step
from app.agent.tools import TOOLS, ToolBox, merge_context
from app.agent.understand import (
    MAX_INPUT_CHARS,
    Understanding,
    heuristic,
    is_injection,
    merge_slots,
    router_messages,
)
from app.billing.alerts import NOTIFY_OWNER, balance_alert
from app.billing.ledger import charge_reply, estimated_reply_price, get_balance, reply_cost
from app.channels.outgoing import mentioned_products, product_card
from app.channels.types import ChannelError, Media, OutgoingMessage, ProductCard
from app.core.config import get_settings
from app.core.queue import Queue
from app.db.session import tenant_session
from app.llm import LLM, LLMError, ToolCall
from app.mlclient import MLError, Transcript
from app.models import Conversation, Message, Product, Unanswered
from app.search.lang import detect_lang
from app.search.types import SearchML

log = structlog.get_logger()


VOICE_PLACEHOLDER = "[голосовое сообщение]"
PAUSE_REPLY = {
    "ru": "Спасибо за сообщение! Менеджер скоро вам ответит.",
    "kk": "Хабарламаңызға рақмет! Менеджер жақын арада жауап береді.",
}
PAUSE_REASONS = {
    "no_balance": "баланс магазина закончился",
    "rate_limit": "покупатель превысил лимит ответов бота в час",
}


class AgentML(SearchML, Protocol):
    async def transcribe(self, audio: bytes, mime_type: str | None = None) -> Transcript: ...


class ChannelPort(Protocol):
    async def send(
        self, channel_id: uuid.UUID, customer_external_id: str, message: OutgoingMessage
    ) -> None: ...

    async def download(self, channel_id: uuid.UUID, media: Media) -> bytes: ...


@dataclass
class AgentDeps:
    llm: LLM | None
    ml: AgentML
    queue: Queue
    channels: ChannelPort | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def last_human(state: ChatState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


class AgentNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    def tenant(self, state: ChatState) -> uuid.UUID:
        return uuid.UUID(state["tenant_id"])

    async def ingest(self, state: ChatState) -> dict[str, Any]:
        conversation_id = uuid.UUID(state["conversation_id"])
        text = last_human(state)
        external_id = state.get("external_id")
        duplicate: str | None = None
        async with tenant_session(self.tenant(state)) as session:
            mode = await session.scalar(
                select(Conversation.mode).where(Conversation.id == conversation_id)
            )
            message = None
            if external_id:
                message = await session.scalar(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation_id,
                        Message.role == "customer",
                        Message.external_id == external_id,
                    )
                    .limit(1)
                )
            if message is not None:
                duplicate = await self.repeated(session, message)
            else:
                message = Message(
                    tenant_id=self.tenant(state),
                    conversation_id=conversation_id,
                    role="customer",
                    content=text or None,
                    media={"items": state["media"]} if state.get("media") else None,
                    external_id=external_id,
                )
                session.add(message)
                await session.flush()
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(last_message_at=func.now())
                )
        if duplicate:
            log.warning("agent.turn_repeated", conversation_id=str(conversation_id), was=duplicate)
            return {
                "duplicate": duplicate,
                "human_mode": mode == "human",
                "customer_message_id": str(message.id),
            }
        fresh: dict[str, Any] = {"slots": {}} if new_session(state.get("messages", [])) else {}
        return {
            **fresh,
            "duplicate": None,
            "human_mode": mode == "human",
            "customer_message_id": str(message.id),
            "voice_failed": False,
            "send_failed": False,
            "paused": None,
            "context": [],
            "tool_hops": 0,
            "retries": 0,
            "check_ok": False,
            "check_errors": [],
            "usage": [],
            "reply": None,
            "flagged": False,
            "started_at": time.time(),
            "trace": [{"node": "ingest", "mode": mode}],
        }

    async def repeated(self, session: AsyncSession, message: Message) -> str | None:
        recorded = await session.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == message.conversation_id,
                Message.role == "bot",
                Message.created_at > message.created_at,
            )
            .limit(1)
        )
        if recorded:
            return "done"
        return "sent" if (message.trace or {}).get("answered") else None

    async def mark_answered(self, state: ChatState) -> None:
        message_id = state.get("customer_message_id")
        if not message_id:
            return
        async with tenant_session(self.tenant(state)) as session:
            await session.execute(
                update(Message)
                .where(Message.id == uuid.UUID(message_id))
                .values(trace={"answered": True})
            )

    async def recognize(self, state: ChatState, item: dict[str, Any]) -> dict[str, Any]:
        channels, channel_id = self.deps.channels, state.get("channel_id")
        if channels is None or not channel_id:
            return {**item, "error": "канал недоступен"}
        try:
            audio = await channels.download(uuid.UUID(channel_id), Media.model_validate(item))
            result = await self.deps.ml.transcribe(audio, item.get("mime_type"))
        except (ChannelError, MLError) as exc:
            log.warning("agent.transcribe_failed", channel_id=channel_id, error=str(exc))
            return {**item, "error": str(exc)}
        return {
            **item,
            "transcript": result.text.strip(),
            "language": result.language,
            "language_probability": result.language_probability,
            "duration": result.duration,
            "asr_model": result.model,
        }

    async def transcribe(self, state: ChatState) -> dict[str, Any]:
        items = [await self.recognize(state, item) for item in state.get("media", [])]
        spoken = [i["transcript"] for i in items if i.get("transcript")]
        last = next(m for m in reversed(state["messages"]) if isinstance(m, HumanMessage))
        typed = str(last.content)
        heard = "\n".join(part for part in (typed, *spoken) if part)
        failed = not spoken
        async with tenant_session(self.tenant(state)) as session:
            await session.execute(
                update(Message)
                .where(Message.id == uuid.UUID(state["customer_message_id"]))
                .values(content=heard or None, media={"items": items})
            )
        return {
            "messages": [
                HumanMessage(
                    id=last.id,
                    content=heard or VOICE_PLACEHOLDER,
                    additional_kwargs=last.additional_kwargs,
                )
            ],
            "voice_failed": failed,
            "trace": step(
                state,
                "transcribe",
                recognized=len(spoken),
                total=len(items),
                languages=[i.get("language") for i in items],
                failed=failed,
            ),
        }

    async def guard_in(self, state: ChatState) -> dict[str, Any]:
        text = last_human(state)
        flagged = is_injection(text) or len(text) > MAX_INPUT_CHARS
        return {
            "flagged": flagged,
            "trace": step(
                state, "guard_in", human_mode=bool(state.get("human_mode")), flagged=flagged
            ),
        }

    async def bot_replies_last_hour(self, session: AsyncSession, state: ChatState) -> int:
        customer = (
            select(Conversation.customer_id)
            .where(Conversation.id == uuid.UUID(state["conversation_id"]))
            .scalar_subquery()
        )
        count = await session.scalar(
            select(func.count(Message.id))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.customer_id == customer,
                Message.role == "bot",
                Message.created_at >= func.now() - timedelta(hours=1),
            )
        )
        return int(count or 0)

    async def pause_reason(self, state: ChatState) -> str | None:
        async with tenant_session(self.tenant(state)) as session:
            balance = await get_balance(session)
            if balance <= 0 or balance < await estimated_reply_price(session):
                return "no_balance"
            replies = await self.bot_replies_last_hour(session, state)
        return "rate_limit" if replies >= get_settings().bot_replies_per_hour else None

    async def gate(self, state: ChatState) -> dict[str, Any]:
        reason = await self.pause_reason(state)
        if reason is None:
            return {"paused": None, "trace": step(state, "gate", ok=True)}
        await self.toolbox(state).handoff(PAUSE_REASONS[reason])
        async with tenant_session(self.tenant(state)) as session:
            await session.execute(
                update(Conversation)
                .where(Conversation.id == uuid.UUID(state["conversation_id"]))
                .values(paused_reason=reason)
            )
        lang = detect_lang(last_human(state)) or "ru"
        return {
            "messages": [AIMessage(PAUSE_REPLY["kk" if lang == "kk" else "ru"])],
            "paused": reason,
            "human_mode": True,
            "intent": None,
            "lang": lang,
            "trace": step(state, "gate", ok=False, reason=reason),
        }

    async def understand(self, state: ChatState) -> dict[str, Any]:
        text = last_human(state)[:MAX_INPUT_CHARS]
        usage = list(state.get("usage", []))
        source = "llm"
        if state.get("flagged"):
            result = heuristic(text).model_copy(update={"intent": "offtopic"})
            source = "guard"
        elif self.deps.llm is None:
            result, source = heuristic(text), "heuristic"
        else:
            try:
                response, entry = await call_llm(
                    self.deps.llm,
                    "understand",
                    get_settings().llm_model_router,
                    router_messages(state.get("messages", []), text),
                    schema=Understanding,
                )
                usage.append(entry)
                if not isinstance(response.parsed, Understanding):
                    raise LLMError("understand: нет structured output")
                result = response.parsed
            except LLMError as exc:
                log.warning("agent.understand_failed", error=str(exc))
                result, source = heuristic(text), "heuristic"
        slots = merge_slots(state.get("slots"), result.slots)
        return {
            "lang": result.lang,
            "intent": result.intent,
            "complexity": result.complexity,
            "slots": slots,
            "search_query": result.search_query or text,
            "usage": usage,
            "trace": step(
                state,
                "understand",
                source=source,
                lang=result.lang,
                intent=result.intent,
                complexity=result.complexity,
                slots=slots,
            ),
        }

    def toolbox(self, state: ChatState) -> ToolBox:
        return ToolBox(
            tenant_id=self.tenant(state),
            conversation_id=uuid.UUID(state["conversation_id"]),
            ml=self.deps.ml,
            queue=self.deps.queue,
            sandbox=bool(state.get("sandbox")),
            lang=state.get("lang"),
        )

    async def retrieve(self, state: ChatState) -> dict[str, Any]:
        box, slots = self.toolbox(state), state.get("slots", {})
        context = list(state.get("context", []))
        if slots.get("sku"):
            context = merge_context(context, (await box.get_product(str(slots["sku"]))).context)
        query = state.get("search_query") or last_human(state)
        found = await box.search_products(query, budget_max=slots.get("budget_max"))
        context = merge_context(context, found.context)
        skus = [c.get("sku") for c in context if c["type"] == "product"]
        return {
            "context": context,
            "trace": step(
                state, "retrieve", query=query, budget_max=slots.get("budget_max"), found=skus
            ),
        }

    async def kb(self, state: ChatState) -> dict[str, Any]:
        query = state.get("search_query") or last_human(state)
        found = await self.toolbox(state).search_kb(query)
        context = merge_context(list(state.get("context", [])), found.context)
        sources = [c["source"] for c in found.context]
        return {"context": context, "trace": step(state, "kb", query=query, found=sources)}

    async def order(self, state: ChatState) -> dict[str, Any]:
        slots = state.get("slots", {})
        context = list(state.get("context", []))
        if slots.get("sku"):
            found = await self.toolbox(state).get_product(str(slots["sku"]))
            context = merge_context(context, found.context)
        return {
            "context": context,
            "trace": step(
                state, "order", sku=slots.get("sku"), delivery_time=slots.get("delivery_time")
            ),
        }

    async def handoff(self, state: ChatState) -> dict[str, Any]:
        await self.toolbox(state).handoff("покупатель попросил менеджера")
        return {"human_mode": True, "trace": step(state, "handoff", reason="intent=human")}

    def notes(self, state: ChatState, retry: bool) -> list[str]:
        notes = []
        intent, context = state.get("intent"), state.get("context", [])
        if state.get("flagged") or intent == "offtopic":
            notes.append(
                "Вопрос не о магазине. Вежливо откажи одной фразой и предложи помочь с выбором"
                " товара или заказом."
            )
        if state.get("voice_failed"):
            notes.append(
                "Голосовое сообщение покупателя не удалось разобрать:"
                " вежливо попроси написать текстом или записать ещё раз."
            )
        if state.get("human_mode"):
            notes.append("Диалог передан менеджеру: скажи, что менеджер скоро подключится.")
        if intent == "product" and not any(c["type"] == "product" for c in context):
            notes.append(
                "В каталоге ничего не нашлось. Не выдумывай товары: предложи уточнить запрос"
                " или позвать менеджера."
            )
        if intent == "policy" and not any(c["type"] == "kb" for c in context):
            notes.append("В базе знаний ответа нет. Не выдумывай: предложи уточнить у менеджера.")
        if state.get("tool_hops", 0) >= MAX_TOOL_HOPS:
            notes.append("Инструменты больше недоступны: ответь по уже найденным данным.")
        if retry:
            notes.append(
                "Прошлый вариант ответа не прошёл проверку: "
                + "; ".join(state.get("check_errors", []))
                + ". Перепиши ответ, используя только цены и артикулы из данных выше."
            )
        return notes

    async def respond(self, state: ChatState) -> dict[str, Any]:
        lang = state.get("lang", "ru")
        retry = bool(state.get("check_errors")) and state.get("retries", 0) < MAX_RETRIES
        retries = state.get("retries", 0) + (1 if retry else 0)
        if self.deps.llm is None:
            return {
                "messages": [AIMessage(FALLBACK.get(lang, FALLBACK["ru"]))],
                "retries": retries,
                "trace": step(state, "respond", source="no_llm"),
            }
        async with tenant_session(self.tenant(state)) as session:
            profile = await load_profile(session, self.tenant(state))
        history = state.get("messages", [])
        model = pick_model(get_settings(), state.get("complexity"), history)
        hops = state.get("tool_hops", 0)
        prompt = build_messages(
            profile,
            history,
            lang=lang,
            intent=state.get("intent"),
            slots=state.get("slots"),
            context=state.get("context", []),
            notes=self.notes(state, retry),
        )
        usage = list(state.get("usage", []))
        try:
            response, entry = await call_llm(
                self.deps.llm,
                "respond",
                model,
                prompt,
                tools=TOOLS if hops < MAX_TOOL_HOPS else None,
            )
        except LLMError as exc:
            log.warning("agent.respond_failed", error=str(exc))
            return {
                "messages": [AIMessage("")],
                "retries": retries,
                "trace": step(state, "respond", model=model, error=str(exc)),
            }
        usage.append(entry)
        message = ai_message(response)
        return {
            "messages": [message],
            "retries": retries,
            "usage": usage,
            "trace": step(
                state,
                "respond",
                model=model,
                retry=retry,
                profile_version=profile.version,
                tool_calls=[c["name"] for c in message.tool_calls],
            ),
        }

    async def tools(self, state: ChatState) -> dict[str, Any]:
        last = state["messages"][-1]
        box = self.toolbox(state)
        context = list(state.get("context", []))
        human_mode = bool(state.get("human_mode"))
        replies, calls = [], []
        for call in getattr(last, "tool_calls", []):
            outcome = await box.run(ToolCall(call["name"], dict(call["args"])))
            replies.append(tool_message(call["id"], call["name"], outcome.result))
            context = merge_context(context, outcome.context)
            human_mode = human_mode or outcome.human_mode
            calls.append(
                {"name": call["name"], "args": call["args"], "ok": "error" not in outcome.result}
            )
        hops = state.get("tool_hops", 0) + 1
        return {
            "messages": replies,
            "context": context,
            "human_mode": human_mode,
            "tool_hops": hops,
            "trace": step(state, "tools", hop=hops, calls=calls),
        }

    async def guard_out(self, state: ChatState) -> dict[str, Any]:
        last = state["messages"][-1]
        reply = str(last.content or "") if isinstance(last, AIMessage) else ""
        async with tenant_session(self.tenant(state)) as session:
            profile = await load_profile(session, self.tenant(state))
        result = check_reply(
            reply, state.get("context", []), profile, last_human(state), state.get("slots", {})
        )
        trace = step(
            state,
            "guard_out",
            ok=result.ok,
            amounts=result.amounts,
            skus=result.skus,
            errors=result.errors,
        )
        if result.ok:
            return {"check_ok": True, "check_errors": [], "trace": trace}
        update: dict[str, Any] = {"check_ok": False, "check_errors": result.errors, "trace": trace}
        if last.id:
            update["messages"] = [RemoveMessage(id=last.id)]
        return update

    async def fallback(self, state: ChatState) -> dict[str, Any]:
        lang = state.get("lang", "ru")
        await self.toolbox(state).handoff("ответ не прошёл проверку цен")
        return {
            "messages": [AIMessage(FALLBACK.get(lang, FALLBACK["ru"]))],
            "human_mode": True,
            "trace": step(state, "fallback", errors=state.get("check_errors", [])),
        }

    async def cards(self, state: ChatState, reply: str) -> list[ProductCard]:
        ids = mentioned_products(reply, state.get("context", []))
        if not ids:
            return []
        async with tenant_session(self.tenant(state)) as session:
            rows = await session.scalars(
                select(Product).where(
                    Product.id.in_([uuid.UUID(i) for i in ids]), Product.is_active
                )
            )
            products = {str(p.id): p for p in rows}
        return [
            product_card(
                name=p.name,
                sku=p.sku,
                price=p.price,
                images=p.images,
                lang=state.get("lang"),
            )
            for p in (products[i] for i in ids if i in products)
        ]

    async def send(self, state: ChatState) -> dict[str, Any]:
        reply = str(state["messages"][-1].content)
        channels, channel_id = self.deps.channels, state.get("channel_id")
        customer = state.get("customer_external_id")
        if state.get("sandbox") or channels is None or not channel_id or not customer:
            return {"reply": reply, "trace": step(state, "send", delivered=False)}
        message = OutgoingMessage(text=reply, cards=await self.cards(state, reply))
        try:
            await channels.send(uuid.UUID(channel_id), customer, message)
        except ChannelError as exc:
            log.warning("agent.send_failed", channel_id=channel_id, error=str(exc))
            trace = step(state, "send", delivered=False, error=str(exc))
            return {"reply": reply, "send_failed": True, "trace": trace}
        await self.mark_answered(state)
        trace = step(
            state,
            "send",
            delivered=True,
            cards=len(message.cards),
            products=mentioned_products(reply, state.get("context", [])),
        )
        return {"reply": reply, "trace": trace}

    def unanswered(self, state: ChatState) -> bool:
        if state.get("paused"):
            return False
        if any(t["node"] in ("fallback",) for t in state.get("trace", [])):
            return True
        if any(t.get("source") == "no_llm" for t in state.get("trace", [])):
            return True
        found = any(c["type"] in ("product", "kb") for c in state.get("context", []))
        return state.get("intent") in ("product", "policy") and not found

    def billable(self, state: ChatState) -> bool:
        skip = state.get("sandbox") or state.get("send_failed")
        return bool(state.get("usage")) and not skip

    async def meter(self, state: ChatState) -> dict[str, Any]:
        usage = state.get("usage", [])
        unanswered = self.unanswered(state)
        trace = step(state, "meter", unanswered=unanswered, sandbox=bool(state.get("sandbox")))
        replies = [u for u in usage if u["node"] == "respond"]
        latency = round((time.time() - state.get("started_at", time.time())) * 1000)
        conversation_id = uuid.UUID(state["conversation_id"])
        reply = state.get("reply")
        model = replies[-1]["model"] if replies else None
        alert: str | None = None
        async with tenant_session(self.tenant(state)) as session:
            cost = await reply_cost(session, usage)
            message = Message(
                tenant_id=self.tenant(state),
                conversation_id=conversation_id,
                role="bot",
                content=reply,
                model=model,
                tokens_in=sum(u["tokens_in"] for u in usage),
                tokens_out=sum(u["tokens_out"] for u in usage),
                cached_tokens=sum(u["cached_tokens"] for u in usage),
                cost_usd=cost,
                latency_ms=latency,
                trace={
                    "lang": state.get("lang"),
                    "intent": state.get("intent"),
                    "steps": trace,
                    "llm_calls": usage,
                },
            )
            session.add(message)
            await session.flush()
            if self.billable(state):
                charge = await charge_reply(
                    session, self.tenant(state), message.id, usage, model, cost
                )
                charged = {
                    "price_kzt": charge.price_kzt,
                    "charged_kzt": charge.charged_kzt,
                    "balance_kzt": charge.balance_after,
                }
                trace = [*trace[:-1], {**trace[-1], "charge": charged}]
                message.trace = {**(message.trace or {}), "steps": trace}
                alert = await balance_alert(session, self.tenant(state), charge)
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(last_message_at=func.now())
            )
            if unanswered:
                session.add(
                    Unanswered(
                        tenant_id=self.tenant(state),
                        conversation_id=conversation_id,
                        question=last_human(state),
                        answer=reply,
                    )
                )
        if alert:
            await self.deps.queue.enqueue(NOTIFY_OWNER, state["tenant_id"], alert)
        return {"trace": trace}
