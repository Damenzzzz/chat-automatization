import asyncio
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.billing.ledger import charge_reply, estimated_reply_price, get_balance
from app.billing.pricing import Pricing as PricingValue
from app.billing.pricing import reply_price_kzt, turn_cost
from app.channels.outbound import Outbound
from app.db.session import tenant_session
from app.llm import LLMResponse, Usage
from app.llm.fake import FakeLLM
from app.models import Message
from tests.agent_helpers import make_agent, make_conversation
from tests.billing_helpers import balance, charges, topup
from tests.channel_helpers import RecordingAdapter, make_channel

SMALLTALK = Understanding(lang="ru", intent="smalltalk", complexity="low")
USAGE = [
    {
        "node": "respond",
        "model": "gemini-3.5-flash-lite",
        "tokens_in": 4000,
        "tokens_out": 200,
        "cached_tokens": 0,
    }
]


def _llm(reply: str = "Здравствуйте!") -> FakeLLM:
    usage = Usage(input_tokens=4000, output_tokens=200)
    return FakeLLM(
        [
            LLMResponse(text="", parsed=SMALLTALK, usage=usage, model="gemini-3.1-flash-lite"),
            LLMResponse(text=reply, usage=usage, model="gemini-3.5-flash-lite"),
        ]
    )


async def _ledger_row(engine: AsyncEngine, tenant_id: uuid.UUID) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT l.*, m.role AS message_role, m.cost_usd AS message_cost,"
                    " m.trace AS message_trace FROM ledger l"
                    " JOIN messages m ON m.id = l.message_id"
                    " WHERE l.tenant_id = :t AND l.type = 'charge'"
                ),
                {"t": tenant_id},
            )
        ).one()


async def test_bot_reply_is_charged_with_cost_and_message(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 1000)
    agent, _ = await make_agent(llm=_llm())

    turn = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="привет")

    row = await _ledger_row(owner_engine, tenant_id)
    assert row.message_role == "bot"
    assert row.cost_usd == row.message_cost
    assert row.cost_usd > 0
    assert row.model == "gemini-3.5-flash-lite"
    assert row.tokens_in == 8000
    assert row.tokens_out == 400
    expected = reply_price_kzt(row.cost_usd, PricingValue(Decimal(3), Decimal(454)))
    assert row.amount_kzt == -expected
    assert await balance(owner_engine, tenant_id) == 1000 - expected
    step = next(s for s in turn.trace if s["node"] == "meter")["charge"]
    assert step["charged_kzt"] == expected
    assert step["balance_kzt"] == 1000 - expected
    assert row.message_trace["steps"][-1]["charge"] == step


async def test_sandbox_never_charges(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 1000)
    agent, _ = await make_agent(llm=_llm())
    await agent.run(
        tenant_id=tenant_id, conversation_id=conversation_id, text="привет", sandbox=True
    )
    assert await charges(owner_engine, tenant_id) == []


async def test_reply_without_llm_calls_is_free(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 1000)
    agent, _ = await make_agent(llm=None)
    await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="привет")
    assert await charges(owner_engine, tenant_id) == []


async def test_undelivered_reply_is_not_charged(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    channel_id = await make_channel(owner_engine, tenant_id)
    await topup(owner_engine, tenant_id, 1000)
    outbound = Outbound({"telegram": RecordingAdapter(fail=True)})
    agent, _ = await make_agent(llm=_llm(), channels=outbound)
    await agent.run(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text="привет",
        channel_id=channel_id,
        customer_external_id="c1",
    )
    assert await charges(owner_engine, tenant_id) == []


async def _charge(tenant_id: uuid.UUID, conversation_id: uuid.UUID, cost: Decimal) -> Any:
    async with tenant_session(tenant_id) as session:
        message = Message(tenant_id=tenant_id, conversation_id=conversation_id, role="bot")
        session.add(message)
        await session.flush()
        return await charge_reply(session, tenant_id, message.id, USAGE, "m", cost)


async def test_charge_never_takes_balance_below_zero(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 2)

    charge = await _charge(tenant_id, conversation_id, Decimal("1"))

    assert charge.price_kzt == 1362
    assert charge.charged_kzt == 2
    assert charge.clipped
    assert await balance(owner_engine, tenant_id) == 0
    assert await charges(owner_engine, tenant_id) == [-2]


async def test_empty_balance_writes_no_ledger_row(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    charge = await _charge(tenant_id, conversation_id, Decimal("1"))
    assert charge.charged_kzt == 0
    assert await charges(owner_engine, tenant_id) == []
    assert await balance(owner_engine, tenant_id) == 0


async def test_concurrent_charges_cannot_overdraw(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 10)
    cost = Decimal("0.001")
    price = reply_price_kzt(cost, PricingValue(Decimal(3), Decimal(454)))
    assert price == 2

    await asyncio.gather(*(_charge(tenant_id, conversation_id, cost) for _ in range(12)))

    assert await balance(owner_engine, tenant_id) == 0
    assert sum(await charges(owner_engine, tenant_id)) == -10


async def test_balance_is_ledger_sum_within_tenant(owner_engine: AsyncEngine) -> None:
    tenant_a, _ = await make_conversation(owner_engine, funds=0)
    tenant_b, _ = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_a, 700)
    await topup(owner_engine, tenant_b, 50)
    async with tenant_session(tenant_a) as session:
        assert await get_balance(session) == 700


async def test_price_estimate_averages_recent_charges(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, funds=0)
    await topup(owner_engine, tenant_id, 1000)
    async with tenant_session(tenant_id) as session:
        assert await estimated_reply_price(session) == 1
    for cost in ("0.001", "0.01"):
        await _charge(tenant_id, conversation_id, Decimal(cost))
    async with tenant_session(tenant_id) as session:
        assert await estimated_reply_price(session) == 8


def test_turn_cost_matches_stored_cost_shape() -> None:
    assert turn_cost(USAGE, PricingValue(Decimal(3), Decimal(454))) == Decimal("0.0017")
