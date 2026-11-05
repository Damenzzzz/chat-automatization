import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.billing.pricing import DEFAULT_MARKUP, Pricing, load_pricing, reply_price_kzt, turn_cost
from app.cli import SATUSHY_TENANT_ID
from app.core.config import get_settings
from app.db.session import tenant_session
from app.llm.pricing import ModelPrice
from tests.billing_helpers import login_admin
from tests.conftest import FakeSender, create_user, login


def pricing(markup: str = "3", rate: str = "500") -> Pricing:
    return Pricing(Decimal(markup), Decimal(rate))


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        ("0.001", 2),
        ("0.002", 3),
        ("0.002001", 4),
        ("0.000001", 1),
        ("0", 1),
        ("0.0031", 5),
    ],
)
def test_reply_price_rounds_up_with_minimum(cost: str, expected: int) -> None:
    price = reply_price_kzt(Decimal(cost), pricing())
    assert price == expected
    assert isinstance(price, int)


def test_reply_price_uses_exact_decimals_not_floats() -> None:
    # во float 0.07 * 3 * 100 = 21.000000000000004 и округлилось бы до 22
    assert reply_price_kzt(Decimal("0.07"), pricing("3", "100")) == 21


def test_reply_price_depends_on_markup_and_rate() -> None:
    assert reply_price_kzt(Decimal("0.01"), pricing("4", "450")) == 18


def test_turn_cost_sums_all_calls_with_given_prices() -> None:
    entry = {"tokens_in": 1_000_000, "tokens_out": 0, "cached_tokens": 0}
    custom = Pricing(
        Decimal(3),
        Decimal(500),
        {"a": ModelPrice(Decimal(1), Decimal(0)), "b": ModelPrice(Decimal(2), Decimal(0))},
    )
    usage = [{**entry, "model": "a"}, {**entry, "model": "b"}, {**entry, "model": "unknown"}]
    assert turn_cost(usage, custom) == Decimal(3)
    assert turn_cost([], custom) == Decimal(0)


async def _clear_global_pricing(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM pricing_settings WHERE tenant_id = :t"), {"t": SATUSHY_TENANT_ID}
        )


@pytest.fixture
async def admin(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> AsyncIterator[uuid.UUID]:
    user_id = await login_admin(client, sender)
    await _clear_global_pricing(owner_engine)
    yield user_id
    await _clear_global_pricing(owner_engine)


async def _tenant(engine: AsyncEngine) -> uuid.UUID:
    async with engine.begin() as conn:
        value: uuid.UUID = await conn.scalar(
            text("INSERT INTO tenants (name) VALUES ('Цены') RETURNING id")
        )
    return value


async def _effective(tenant_id: uuid.UUID) -> Pricing:
    async with tenant_session(tenant_id) as session:
        return await load_pricing(session)


async def test_defaults_when_nothing_is_configured(
    owner_engine: AsyncEngine, admin: uuid.UUID
) -> None:
    result = await _effective(await _tenant(owner_engine))
    assert result.markup == DEFAULT_MARKUP == Decimal(3)
    assert result.kzt_per_usd == get_settings().pricing_kzt_per_usd
    assert "gemini-3.5-flash-lite" in result.model_prices


async def test_global_pricing_applies_to_every_shop_and_override_wins(
    client: AsyncClient, owner_engine: AsyncEngine, admin: uuid.UUID
) -> None:
    plain, special = await _tenant(owner_engine), await _tenant(owner_engine)
    saved = await client.put(
        "/admin/pricing",
        json={
            "markup": "4",
            "kzt_per_usd": "460.5",
            "model_prices": {"gemini-3.6-flash": {"input_per_m": "1.5", "output_per_m": "7.5"}},
        },
    )
    assert saved.status_code == 200, saved.text
    override = await client.put(f"/admin/tenants/{special}/pricing", json={"markup": "5"})
    assert override.status_code == 200, override.text

    general = await _effective(plain)
    assert general.markup == Decimal(4)
    assert general.kzt_per_usd == Decimal("460.5")
    assert general.model_prices["gemini-3.6-flash"].output_per_m == Decimal("7.5")
    assert general.model_prices["gemini-3.1-flash-lite"].input_per_m == Decimal("0.25")

    own = await _effective(special)
    assert own.markup == Decimal(5)
    assert own.kzt_per_usd == get_settings().pricing_kzt_per_usd
    assert (await _effective(plain)).markup == Decimal(4)


async def test_override_of_one_shop_is_not_visible_to_another(
    client: AsyncClient, owner_engine: AsyncEngine, admin: uuid.UUID
) -> None:
    a, b = await _tenant(owner_engine), await _tenant(owner_engine)
    await client.put(f"/admin/tenants/{a}/pricing", json={"markup": "7"})
    assert (await _effective(b)).markup == DEFAULT_MARKUP


@pytest.mark.parametrize("body", [{"markup": "2.9"}, {"kzt_per_usd": "0"}, {"kzt_per_usd": "-1"}])
async def test_invalid_pricing_is_rejected(
    client: AsyncClient, admin: uuid.UUID, body: dict[str, Any]
) -> None:
    assert (await client.put("/admin/pricing", json=body)).status_code == 422


async def test_database_refuses_markup_below_three(owner_engine: AsyncEngine) -> None:
    tenant_id = await _tenant(owner_engine)
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO pricing_settings (tenant_id, markup) VALUES (:t, 2)"),
                {"t": tenant_id},
            )


async def test_shop_owner_cannot_change_pricing(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, _, phone = await create_user(owner_engine)
    await login(client, sender, phone)
    assert (await client.get("/admin/pricing")).status_code == 403
    assert (await client.put("/admin/pricing", json={"markup": "3"})).status_code == 403
    response = await client.put(f"/admin/tenants/{tenant_id}/pricing", json={"markup": "3"})
    assert response.status_code == 403


async def test_pricing_change_is_audited(
    client: AsyncClient, owner_engine: AsyncEngine, admin: uuid.UUID
) -> None:
    tenant_id = await _tenant(owner_engine)
    await client.put(f"/admin/tenants/{tenant_id}/pricing", json={"markup": "6"})
    async with owner_engine.connect() as conn:
        actor = await conn.scalar(
            text("SELECT actor_id FROM audit_log WHERE tenant_id = :t AND action = :a"),
            {"t": tenant_id, "a": "pricing.update"},
        )
    assert actor == admin
