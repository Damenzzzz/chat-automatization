import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.analytics.overview import change_percent
from app.analytics.period import Period, PeriodError, resolve_period
from tests.analytics_helpers import at, dialog, lead
from tests.conftest import FakeSender, create_user, login

DAY = date(2026, 10, 10)
RANGE = {"date_from": "2026-10-10", "date_to": "2026-10-16"}


async def _overview(client: AsyncClient) -> dict[str, dict[str, object]]:
    response = await client.get("/analytics/overview", params=RANGE)
    assert response.status_code == 200, response.text
    body: dict[str, dict[str, object]] = response.json()
    return body


def test_previous_period_has_same_length_right_before() -> None:
    period = Period(date(2026, 10, 10), date(2026, 10, 16))
    previous = period.previous()
    assert previous == Period(date(2026, 10, 3), date(2026, 10, 9))
    assert previous.days == period.days == 7


def test_period_bounds_use_almaty_midnight() -> None:
    period = Period(date(2026, 10, 10), date(2026, 10, 10))
    assert period.start.isoformat() == "2026-10-10T00:00:00+05:00"
    assert period.end.isoformat() == "2026-10-11T00:00:00+05:00"


def test_resolve_period_defaults_and_limits() -> None:
    assert resolve_period(None, date(2026, 10, 16)).first == date(2026, 10, 10)
    with pytest.raises(PeriodError):
        resolve_period(date(2026, 10, 17), date(2026, 10, 16))
    with pytest.raises(PeriodError):
        resolve_period(date(2025, 1, 1), date(2026, 10, 16))


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        (15, 10, 50.0),
        (5, 10, -50.0),
        (10, 10, 0.0),
        (10, 0, None),
        (None, 10, None),
        (0, 10, -100.0),
    ],
)
def test_change_percent(
    current: float | None, previous: float | None, expected: float | None
) -> None:
    assert change_percent(current, previous) == expected


async def test_overview_counts_and_compares_with_previous_period(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    bot_one = await dialog(owner_engine, owner, at(DAY), latency=1000)
    await dialog(owner_engine, owner, at(DAY + timedelta(days=1)), latency=3000)
    await dialog(owner_engine, owner, at(DAY + timedelta(days=2)), mode="human", latency=2000)
    await dialog(owner_engine, owner, at(DAY + timedelta(days=3)), manager=True, latency=2000)
    await lead(owner_engine, owner, bot_one, at(DAY), 52000)
    await lead(owner_engine, owner, None, at(DAY), 8000)
    await lead(owner_engine, owner, bot_one, at(DAY), 999, status="cancelled")

    old = await dialog(owner_engine, owner, at(DAY - timedelta(days=2)), latency=4000)
    await dialog(owner_engine, owner, at(DAY - timedelta(days=3)), mode="human", latency=None)
    await lead(owner_engine, owner, old, at(DAY - timedelta(days=2)), 30000)

    body = await _overview(client)

    assert body["current"] == {
        "date_from": "2026-10-10",
        "date_to": "2026-10-16",
        "dialogs": 4,
        "bot_resolved": 2,
        "bot_resolved_share": 0.5,
        "leads": 2,
        "leads_total_kzt": 60000,
        "avg_response_ms": 2000,
        "spent_kzt": 0,
        "found_dialogs": 0,
        "leads_done": 0,
    }
    assert body["previous"]["dialogs"] == 2
    assert body["previous"]["bot_resolved_share"] == 0.5
    assert body["previous"]["leads_total_kzt"] == 30000
    assert body["previous"]["avg_response_ms"] == 4000
    assert body["change_percent"]["dialogs"] == 100.0
    assert body["change_percent"]["leads_total_kzt"] == 100.0
    assert body["change_percent"]["avg_response_ms"] == -50.0


async def test_dialog_with_many_messages_counts_once(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    from sqlalchemy import text

    conversation = await dialog(owner_engine, owner, at(DAY))
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO messages (tenant_id, conversation_id, role, content, created_at)"
                " VALUES (:t, :c, 'customer', 'ещё', :at)"
            ),
            {"t": owner, "c": conversation, "at": at(DAY, 14)},
        )
    assert (await _overview(client))["current"]["dialogs"] == 1


async def test_sandbox_is_excluded_everywhere(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    conversation = await dialog(owner_engine, owner, at(DAY), sandbox=True)
    await lead(owner_engine, owner, conversation, at(DAY), 5000)
    current = (await _overview(client))["current"]
    assert current["dialogs"] == 0
    assert current["leads"] == 0
    assert current["avg_response_ms"] is None
    days = (await client.get("/analytics/dialogs_by_day", params=RANGE)).json()
    assert sum(d["dialogs"] for d in days) == 0


async def test_empty_period_has_no_division_by_zero(client: AsyncClient, owner: uuid.UUID) -> None:
    body = await _overview(client)
    assert body["current"]["dialogs"] == 0
    assert body["current"]["bot_resolved_share"] is None
    assert body["current"]["avg_response_ms"] is None
    assert body["change_percent"]["dialogs"] is None


async def test_analytics_is_isolated_between_shops(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    await dialog(owner_engine, other, at(DAY))
    await lead(owner_engine, other, None, at(DAY), 777)
    current = (await _overview(client))["current"]
    assert current["dialogs"] == 0
    assert current["leads_total_kzt"] == 0


async def test_dialogs_by_day_fills_gaps_and_uses_local_days(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    await dialog(owner_engine, owner, at(DAY, 23))
    await dialog(owner_engine, owner, at(DAY + timedelta(days=1), 1))
    await dialog(owner_engine, owner, at(DAY + timedelta(days=1), 2))
    response = await client.get(
        "/analytics/dialogs_by_day", params={"date_from": "2026-10-10", "date_to": "2026-10-12"}
    )
    assert response.json() == [
        {"day": "2026-10-10", "dialogs": 1},
        {"day": "2026-10-11", "dialogs": 2},
        {"day": "2026-10-12", "dialogs": 0},
    ]


async def test_period_boundaries_are_inclusive_of_local_days(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    await dialog(owner_engine, owner, at(DAY, 0))
    await dialog(owner_engine, owner, at(date(2026, 10, 16), 23))
    await dialog(owner_engine, owner, at(date(2026, 10, 17), 0))
    assert (await _overview(client))["current"]["dialogs"] == 2


async def test_invalid_period_is_rejected(client: AsyncClient, owner: uuid.UUID) -> None:
    response = await client.get(
        "/analytics/overview", params={"date_from": "2026-10-16", "date_to": "2026-10-10"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "period_invalid"


async def test_manager_can_read_but_anonymous_cannot(
    client: AsyncClient, owner: uuid.UUID, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)
    assert (await client.get("/analytics/overview")).status_code == 200
    client.cookies.clear()
    assert (await client.get("/analytics/overview")).status_code == 401
