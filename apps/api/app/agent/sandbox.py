import asyncio
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.agent.llmcall import call_llm
from app.agent.prompt import money
from app.agent.runtime import Agent
from app.core.config import get_settings
from app.db.session import tenant_session
from app.llm import LLM, LLMError, Message
from app.models import Conversation, Customer, KbChunk, Product

AUTOTEST_CONCURRENCY = 4


async def sandbox_conversation(tenant_id: uuid.UUID, session_id: str) -> uuid.UUID:
    external_id = f"sandbox:{session_id}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            insert(Customer)
            .values(tenant_id=tenant_id, channel="web", external_id=external_id, name="Песочница")
            .on_conflict_do_nothing(
                index_elements=[Customer.tenant_id, Customer.channel, Customer.external_id]
            )
        )
        customer_id = await session.scalar(
            select(Customer.id).where(
                Customer.channel == "web", Customer.external_id == external_id
            )
        )
        conversation_id = await session.scalar(
            select(Conversation.id)
            .where(Conversation.customer_id == customer_id, Conversation.sandbox)
            .order_by(Conversation.created_at.desc())
        )
        if conversation_id is None:
            conversation = Conversation(tenant_id=tenant_id, customer_id=customer_id, sandbox=True)
            session.add(conversation)
            await session.flush()
            conversation_id = conversation.id
    return conversation_id


class AutotestQuestion(BaseModel):
    question: str
    kind: Literal["product", "policy"]
    lang: Literal["ru", "kk"]
    expected: str = Field(
        description="что обязательно должно быть в верном ответе: товар, цена, факт"
    )


class AutotestPlan(BaseModel):
    questions: list[AutotestQuestion]


class Verdict(BaseModel):
    correct: bool
    reason: str


async def shop_facts(tenant_id: uuid.UUID, limit: int = 60) -> str:
    async with tenant_session(tenant_id) as session:
        products = list(
            await session.scalars(
                select(Product).where(Product.is_active).order_by(Product.name).limit(limit)
            )
        )
        chunks = list(await session.scalars(select(KbChunk).order_by(KbChunk.source).limit(30)))
    lines = ["Каталог:"]
    for p in products:
        price = money(p.price) if p.price is not None else "без цены"
        stock = "наличие не указано" if p.stock is None else f"остаток {p.stock}"
        lines.append(
            f"- {p.sku or '—'} {p.name} ({p.category or 'без категории'}): {price}, {stock}"
        )
    lines.append("База знаний:")
    lines += [f"- {c.title or c.source}: {c.text}" for c in chunks]
    return "\n".join(lines)


PLAN_PROMPT = """Ты готовишь автотест чат-бота магазина. По данным магазина составь {count} разных
вопросов, которые реально пишут покупатели: примерно 2/3 про товары (наличие, цена, подбор
под повод или бюджет), 1/3 про доставку, оплату, адрес, график. Примерно треть вопросов —
на казахском. Для каждого вопроса в expected напиши, что обязано быть в верном ответе
(конкретный товар, его цена из каталога, факт из базы знаний). Не придумывай данных, которых
нет ниже."""

JUDGE_PROMPT = """Ты проверяешь ответ чат-бота магазина. Ответ верный, если он отвечает на вопрос,
не противоречит данным магазина, называет только цены из каталога и написан на языке вопроса.
Ответ «уточню у менеджера» верен только если в данных действительно нет ответа.
Коротко объясни решение в reason."""


async def autotest(agent: Agent, llm: LLM, tenant_id: uuid.UUID, count: int = 20) -> dict[str, Any]:
    model = get_settings().llm_model_reply
    facts = await shop_facts(tenant_id)
    plan, plan_usage = await call_llm(
        llm,
        "autotest.plan",
        model,
        [Message("system", PLAN_PROMPT.format(count=count)), Message("user", facts)],
        schema=AutotestPlan,
    )
    if not isinstance(plan.parsed, AutotestPlan):
        raise LLMError("autotest: нет плана вопросов")
    questions = plan.parsed.questions[:count]
    run_id = uuid.uuid4().hex[:8]
    gate = asyncio.Semaphore(AUTOTEST_CONCURRENCY)

    async def check(index: int, q: AutotestQuestion) -> dict[str, Any]:
        async with gate:
            conversation_id = await sandbox_conversation(tenant_id, f"autotest-{run_id}-{index}")
            turn = await agent.run(
                tenant_id=tenant_id, conversation_id=conversation_id, text=q.question, sandbox=True
            )
            answer = turn.reply or ""
            try:
                verdict, usage = await call_llm(
                    llm,
                    "autotest.judge",
                    model,
                    [
                        Message("system", JUDGE_PROMPT),
                        Message(
                            "user",
                            f"{facts}\n\nВопрос: {q.question}\nОжидается: {q.expected}\n"
                            f"Ответ бота: {answer}",
                        ),
                    ],
                    schema=Verdict,
                )
                judged = verdict.parsed if isinstance(verdict.parsed, Verdict) else None
            except LLMError as exc:
                judged, usage = Verdict(correct=False, reason=f"судья недоступен: {exc}"), {}
            judged = judged or Verdict(correct=False, reason="судья не вернул оценку")
            return {
                "question": q.question,
                "kind": q.kind,
                "lang": q.lang,
                "expected": q.expected,
                "answer": answer,
                "intent": turn.intent,
                "correct": judged.correct,
                "reason": judged.reason,
                "usage": [*turn.usage, usage] if usage else turn.usage,
            }

    items = await asyncio.gather(*(check(i, q) for i, q in enumerate(questions)))
    return {
        "total": len(items),
        "correct": sum(1 for item in items if item["correct"]),
        "items": list(items),
        "plan_usage": plan_usage,
    }
