import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import worker
from app.automations import base, runner
from app.automations.base import Deps, plural
from app.automations.digest import Digest, DigestSettings
from app.automations.followup import FollowupSettings, quiet
from app.automations.runner import due_automations, execute
from app.channels.types import ChannelError, OutgoingMessage
from app.core.config import get_settings
from app.routers.automations import get_deps, get_light_deps
from tests.agent_helpers import make_conversation
from tests.channel_helpers import make_channel
from tests.conftest import FakeSender, create_user, login

ALMATY = ZoneInfo("Asia/Almaty")
NO_QUIET = {"quiet_from": 0, "quiet_to": 0}


class FakeOutbound:
    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, str, OutgoingMessage]] = []
        self.error: str | None = None

    async def send(self, channel_id: uuid.UUID, customer: str, message: OutgoingMessage) -> None:
        if self.error:
            raise ChannelError(self.error)
        self.sent.append((channel_id, customer, message))


@pytest.fixture
def told(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[str, ...]]]:
    messages: list[tuple[str, tuple[str, ...]]] = []

    async def fake_send(
        tenant_id: uuid.UUID, body: str, adapters: Any, roles: tuple[str, ...] = ("owner",)
    ) -> int:
        messages.append((body, roles))
        return 1

    monkeypatch.setattr(base, "send_owner_message", fake_send)
    return messages


@pytest.fixture
def outbound() -> FakeOutbound:
    return FakeOutbound()


@pytest.fixture
def deps(redis: Redis, outbound: FakeOutbound, app: FastAPI) -> Deps:
    remembered: list[tuple[uuid.UUID, str]] = []

    async def remember(conversation_id: uuid.UUID, body: str) -> None:
        remembered.append((conversation_id, body))

    made = Deps(redis, {}, outbound, remember)  # type: ignore[arg-type]
    made.remembered = remembered  # type: ignore[attr-defined]
    app.dependency_overrides[get_deps] = lambda: made
    app.dependency_overrides[get_light_deps] = lambda: made
    return made


async def _enable(engine: AsyncEngine, tenant_id: uuid.UUID, kind: str, **settings: Any) -> None:
    import json

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO automations (tenant_id, kind, enabled, settings)"
                " VALUES (:t, :k, true, cast(:s AS jsonb))"
                " ON CONFLICT (tenant_id, kind) DO UPDATE SET enabled = true,"
                " settings = excluded.settings"
            ),
            {"t": tenant_id, "k": kind, "s": json.dumps(settings)},
        )


async def _product(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    name: str,
    stock: int | None,
    category: str = "Букеты",
) -> uuid.UUID:
    async with engine.begin() as conn:
        product_id: uuid.UUID = await conn.scalar(
            text(
                "INSERT INTO products (tenant_id, name, price, stock, category)"
                " VALUES (:t, :n, 1000, :s, :c) RETURNING id"
            ),
            {"t": tenant_id, "n": name, "s": stock, "c": category},
        )
    return product_id


async def _silent_dialog(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    *,
    hours: float = 4,
    searched: bool = True,
    mode: str = "bot",
    channel: str = "telegram",
    now: datetime | None = None,
) -> uuid.UUID:
    moment = (now or datetime.now(UTC)) - timedelta(hours=hours)
    _, conversation_id = await make_conversation(engine, tenant_id, mode=mode)
    channel_id = await make_channel(engine, tenant_id, type_=channel)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE customers SET channel = :ch, name = 'Айгерим' WHERE id ="
                " (SELECT customer_id FROM conversations WHERE id = :i)"
            ),
            {"ch": channel, "i": conversation_id},
        )
        await conn.execute(
            text("UPDATE conversations SET channel_id = :c, last_message_at = :at WHERE id = :i"),
            {"c": channel_id, "i": conversation_id, "at": moment},
        )
        for role, shift in (("customer", 0), ("bot", 1)):
            await conn.execute(
                text(
                    "INSERT INTO messages (tenant_id, conversation_id, role, content, created_at)"
                    " VALUES (:t, :i, :r, 'Есть пионы?', :at)"
                ),
                {
                    "t": tenant_id,
                    "i": conversation_id,
                    "r": role,
                    "at": moment + timedelta(minutes=shift),
                },
            )
        if searched:
            await conn.execute(
                text(
                    "INSERT INTO search_log (tenant_id, conversation_id, query, kind, result_count,"
                    " created_at) VALUES (:t, :i, 'пионы', 'product', 3, :at)"
                ),
                {"t": tenant_id, "i": conversation_id, "at": moment},
            )
    return conversation_id


async def _due(tenant_id: uuid.UUID) -> list[str]:
    return sorted(kind for tenant, kind in await due_automations() if tenant == tenant_id)


async def _tick(deps: Deps, tenant_id: uuid.UUID) -> int:
    """То же, что делает cron воркера, но только для одного магазина: тесты делят базу."""
    runs = [await execute(tenant_id, kind, "schedule", deps) for kind in await _due(tenant_id)]
    return len([run for run in runs if run is not None])


async def _count(engine: AsyncEngine, sql: str, **params: Any) -> int:
    async with engine.connect() as conn:
        return int(await conn.scalar(text(sql), params) or 0)


async def test_services_are_listed_with_defaults(client: AsyncClient, owner: uuid.UUID) -> None:
    services = {item["kind"]: item for item in (await client.get("/automations")).json()}
    assert set(services) == {"digest", "stock", "followup", "lead_reminders"}
    assert [kind for kind, item in services.items() if item["enabled"]] == ["lead_reminders"]
    assert services["digest"]["settings"]["hour"] == 9
    assert services["followup"]["settings"]["mode"] == "approve"
    assert services["stock"]["last_run"] is None
    assert all(item["title"] and item["description"] for item in services.values())


async def test_owner_saves_settings_and_manager_cannot(
    client: AsyncClient, sender: FakeSender, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    saved = await client.put(
        "/automations/stock", json={"enabled": True, "settings": {"threshold": 10}}
    )
    assert saved.status_code == 200
    assert (saved.json()["enabled"], saved.json()["settings"]["threshold"]) == (True, 10)

    for wrong in ({"threshold": -1}, {"threshold": "много"}, {"recipients": "все"}):
        answer = await client.put("/automations/stock", json={"settings": wrong})
        assert (answer.status_code, answer.json()["detail"]) == (422, "settings_invalid")
    assert (await client.put("/automations/unknown", json={})).status_code == 422
    kept = {item["kind"]: item for item in (await client.get("/automations")).json()}
    assert kept["stock"]["settings"]["threshold"] == 10

    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)
    assert (await client.get("/automations")).status_code == 200
    assert (await client.put("/automations/stock", json={"enabled": False})).status_code == 403
    assert (await client.post("/automations/stock/run")).status_code == 403
    assert (await client.post("/automations/stock/preview")).status_code == 200


async def test_digest_preview_run_and_history(
    client: AsyncClient,
    owner: uuid.UUID,
    owner_engine: AsyncEngine,
    deps: Deps,
    told: list[tuple[str, tuple[str, ...]]],
) -> None:
    await _product(owner_engine, owner, "Пионы", 1)
    async with owner_engine.begin() as conn:
        await conn.execute(text("INSERT INTO leads (tenant_id) VALUES (:t)"), {"t": owner})

    preview = (await client.post("/automations/digest/preview")).json()
    assert "Тестовый магазин" in preview["text"]
    assert "новых заявок — 1" in preview["text"]
    assert "Товаров на исходе: 1" in preview["text"]
    short = await client.post(
        "/automations/digest/preview", json={"settings": {"sections": ["stock"]}}
    )
    assert "Диалогов" not in short.json()["text"]
    assert told == []
    assert await _count(owner_engine, "SELECT count(*) FROM notifications") == 0

    off = await client.post("/automations/digest/run")
    assert (off.status_code, off.json()["detail"]) == (409, "automation_disabled")
    assert told == []
    await client.put("/automations/digest", json={"enabled": True})
    run = await client.post("/automations/digest/run")
    assert run.status_code == 200
    assert (run.json()["status"], run.json()["trigger"]) == ("ok", "manual")
    assert [roles for _, roles in told] == [("owner",)]
    assert (
        await _count(owner_engine, "SELECT count(*) FROM notifications WHERE kind = 'digest'") == 1
    )

    history = (await client.get("/automations/digest/runs")).json()
    assert [item["id"] for item in history] == [run.json()["id"]]
    listed = {item["kind"]: item for item in (await client.get("/automations")).json()}
    assert listed["digest"]["last_run"]["id"] == run.json()["id"]


async def test_manual_runs_are_rate_limited(
    client: AsyncClient, owner: uuid.UUID, deps: Deps, told: list[Any]
) -> None:
    await client.put("/automations/stock", json={"enabled": True})
    codes = [(await client.post("/automations/stock/run")).status_code for _ in range(7)]
    assert codes == [200] * 6 + [429]


def test_digest_is_due_once_a_day_after_its_hour() -> None:
    digest, settings = Digest(), DigestSettings(hour=9, weekdays=[0, 1, 2, 3, 4])
    monday = datetime(2026, 11, 16, tzinfo=ALMATY)
    assert not digest.due(settings, {}, None, monday.replace(hour=8, minute=59))
    assert digest.due(settings, {}, None, monday.replace(hour=9))
    assert digest.due(settings, {"last_date": "2026-11-15"}, None, monday.replace(hour=18))
    assert not digest.due(settings, {"last_date": "2026-11-16"}, None, monday.replace(hour=18))
    assert not digest.due(settings, {}, None, monday.replace(day=21, hour=12))


async def test_scheduled_digest_is_sent_once_per_day(
    owner_engine: AsyncEngine, deps: Deps, told: list[Any]
) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    await _enable(owner_engine, tenant_id, "digest", hour=0)
    assert await _tick(deps, tenant_id) == 1
    assert await _tick(deps, tenant_id) == 0
    assert len(told) == 1


async def test_run_due_executes_every_due_service(
    owner_engine: AsyncEngine, deps: Deps, told: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    await _enable(owner_engine, tenant_id, "digest", hour=0)
    await _enable(owner_engine, tenant_id, "stock")

    async def only_this_shop() -> list[tuple[uuid.UUID, str]]:
        return [(tenant_id, kind) for kind in await _due(tenant_id)]

    monkeypatch.setattr(runner, "due_automations", only_this_shop)
    assert await runner.run_due(deps) == 1
    assert await runner.run_due(deps) == 0


async def test_stock_alerts_only_about_new_shortage(
    owner_engine: AsyncEngine, deps: Deps, told: list[tuple[str, tuple[str, ...]]]
) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    other, _, _ = await create_user(owner_engine)
    low = await _product(owner_engine, tenant_id, "Пионы белые", 2)
    await _product(owner_engine, tenant_id, "Розы", 40)
    await _product(owner_engine, tenant_id, "Без учёта", None)
    await _product(owner_engine, other, "Чужой товар", 0)
    await _enable(owner_engine, tenant_id, "stock", threshold=3)
    hour = timedelta(hours=1)
    start = datetime.now(UTC)

    first = await execute(tenant_id, "stock", "schedule", deps, now=start)
    assert first is not None and first.details == {"new": 1, "low": 1, "sent": 1}
    assert "Пионы белые" in told[0][0] and "Чужой товар" not in told[0][0]
    assert await execute(tenant_id, "stock", "schedule", deps, now=start + hour / 2) is None
    assert await execute(tenant_id, "stock", "schedule", deps, now=start + hour) is None
    assert len(told) == 1

    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE products SET stock = 50 WHERE id = :i"), {"i": low})
    assert await execute(tenant_id, "stock", "schedule", deps, now=start + 2 * hour) is None
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE products SET stock = 0 WHERE id = :i"), {"i": low})
    again = await execute(tenant_id, "stock", "schedule", deps, now=start + 3 * hour)
    assert again is not None and "нет в наличии" in told[1][0]


async def test_stock_preview_respects_settings_from_request(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, deps: Deps
) -> None:
    await _product(owner_engine, owner, "Пионы", 0, "Букеты")
    await _product(owner_engine, owner, "Ваза", 2, "Вазы")
    everything = (await client.post("/automations/stock/preview")).json()
    assert [item["title"] for item in everything["items"]] == ["Пионы", "Ваза"]
    only = await client.post(
        "/automations/stock/preview",
        json={"settings": {"categories": ["вазы"], "include_out_of_stock": False}},
    )
    assert [item["title"] for item in only.json()["items"]] == ["Ваза"]
    saved = {item["kind"]: item for item in (await client.get("/automations")).json()}
    assert saved["stock"]["settings"]["categories"] == []


async def test_new_lead_is_reminded_once_without_any_setup(
    owner_engine: AsyncEngine, deps: Deps, told: list[tuple[str, tuple[str, ...]]]
) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO leads (tenant_id, conversation_id, total_kzt, created_at)"
                " VALUES (:t, :c, 52000, now() - interval '3 hours')"
            ),
            {"t": tenant_id, "c": conversation_id},
        )
    assert await _due(tenant_id) == ["lead_reminders"]
    assert await _tick(deps, tenant_id) == 1
    assert await _tick(deps, tenant_id) == 0
    assert [roles for body, roles in told if "52 000 ₸" in body] == [("owner", "manager")]


async def test_worker_cron_runs_due_automations(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Deps] = []

    async def fake_run_due(deps: Deps) -> int:
        seen.append(deps)
        return 3

    async def remember(conversation_id: uuid.UUID, body: str) -> None:
        return None

    monkeypatch.setattr(worker, "run_due", fake_run_due)
    agent = type("Agent", (), {"remember_manager_reply": staticmethod(remember)})
    assert await worker.run_automations({"agent": agent}) == 3
    assert seen[0].remember is remember


async def test_lead_reminders_follow_settings_and_deadline(
    client: AsyncClient,
    owner: uuid.UUID,
    owner_engine: AsyncEngine,
    deps: Deps,
    told: list[tuple[str, tuple[str, ...]]],
) -> None:
    async with owner_engine.begin() as conn:
        lead_id = await conn.scalar(
            text(
                "INSERT INTO leads (tenant_id, total_kzt, created_at, status, remind_at) VALUES"
                " (:t, 7000, now() - interval '3 hours', 'in_progress',"
                " now() - interval '1 minute')"
                " RETURNING id"
            ),
            {"t": owner},
        )
        await conn.execute(
            text(
                "INSERT INTO leads (tenant_id, total_kzt, created_at)"
                " VALUES (:t, 9000, now() - interval '3 hours')"
            ),
            {"t": owner},
        )
    await client.put("/automations/lead_reminders", json={"settings": {"hours": 5}})
    assert await _tick(deps, owner) == 1
    assert len(told) == 1 and f"№{str(lead_id)[:8]}" in told[0][0]
    assert await _tick(deps, owner) == 0

    later = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await client.patch(f"/leads/{lead_id}", json={"remind_at": later})
    await client.put("/automations/lead_reminders", json={"settings": {"hours": 2}})
    assert await _tick(deps, owner) == 1
    assert len(told) == 3

    await client.put("/automations/lead_reminders", json={"enabled": False})
    assert await _due(owner) == []


async def test_suspended_shop_gets_no_automations(owner_engine: AsyncEngine, deps: Deps) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    await _enable(owner_engine, tenant_id, "digest", hour=0)
    assert await _due(tenant_id) == ["digest"]
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'suspended' WHERE id = :t"), {"t": tenant_id}
        )
    assert await _due(tenant_id) == []


def test_quiet_hours_wrap_over_midnight() -> None:
    night = FollowupSettings(quiet_from=21, quiet_to=9)
    day = datetime(2026, 11, 16, tzinfo=ALMATY)
    assert quiet(night, day.replace(hour=23))
    assert quiet(night, day.replace(hour=8, minute=59))
    assert not quiet(night, day.replace(hour=9))
    assert not quiet(night, day.replace(hour=20, minute=59))
    assert not quiet(FollowupSettings(quiet_from=0, quiet_to=0), day.replace(hour=3))


async def test_followup_picks_only_silent_interested_dialogs(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, deps: Deps
) -> None:
    wanted = await _silent_dialog(owner_engine, owner)
    await _silent_dialog(owner_engine, owner, hours=1)
    await _silent_dialog(owner_engine, owner, hours=30)
    await _silent_dialog(owner_engine, owner, searched=False)
    await _silent_dialog(owner_engine, owner, mode="human")
    await _silent_dialog(owner_engine, owner, channel="instagram")
    with_lead = await _silent_dialog(owner_engine, owner)
    other, _, _ = await create_user(owner_engine)
    await _silent_dialog(owner_engine, other)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO leads (tenant_id, conversation_id) VALUES (:t, :c)"),
            {"t": owner, "c": with_lead},
        )

    preview = (await client.post("/automations/followup/preview")).json()
    assert [item["href"] for item in preview["items"]] == [f"/dialogs?id={wanted}"]
    assert preview["items"][0]["title"] == "Айгерим"
    assert "Есть пионы" not in str(preview)


async def test_followup_waits_for_approval_then_sends(
    client: AsyncClient,
    owner: uuid.UUID,
    owner_engine: AsyncEngine,
    deps: Deps,
    outbound: FakeOutbound,
    told: list[Any],
) -> None:
    conversation_id = await _silent_dialog(owner_engine, owner)
    await client.put("/automations/followup", json={"enabled": True, "settings": NO_QUIET})

    assert await _tick(deps, owner) == 1
    assert await _tick(deps, owner) == 0
    assert outbound.sent == []
    pending = (await client.get("/followups", params={"status": "pending"})).json()
    assert [(item["conversation_id"], item["customer_name"]) for item in pending] == [
        (str(conversation_id), "Айгерим")
    ]
    listed = {item["kind"]: item for item in (await client.get("/automations")).json()}
    assert listed["followup"]["pending"] == 1

    text_ = "Здравствуйте, Айгерим! Пионы ещё в наличии — оформить?"
    sent = await client.post(f"/followups/{pending[0]['id']}/send", json={"text": text_})
    assert sent.json()["status"] == "sent"
    assert [message.text for _, _, message in outbound.sent] == [text_]
    assert deps.remembered == [(conversation_id, text_)]  # type: ignore[attr-defined]
    async with owner_engine.connect() as conn:
        last = (
            await conn.execute(
                text(
                    "SELECT role, content, trace FROM messages WHERE conversation_id = :i"
                    " ORDER BY created_at DESC LIMIT 1"
                ),
                {"i": conversation_id},
            )
        ).one()
    assert (last.role, last.content) == ("bot", text_)
    assert last.trace["steps"][0]["node"] == "followup"

    again = await client.post(f"/followups/{pending[0]['id']}/send")
    assert (again.status_code, again.json()["detail"]) == (409, "followup_decided")
    assert await _tick(deps, owner) == 0


async def test_followup_expires_when_customer_wrote_back(
    client: AsyncClient,
    owner: uuid.UUID,
    owner_engine: AsyncEngine,
    deps: Deps,
    outbound: FakeOutbound,
    told: list[Any],
) -> None:
    conversation_id = await _silent_dialog(owner_engine, owner)
    rejected_dialog = await _silent_dialog(owner_engine, owner)
    await client.put("/automations/followup", json={"enabled": True, "settings": NO_QUIET})
    await _tick(deps, owner)
    pending = {
        item["conversation_id"]: item["id"] for item in (await client.get("/followups")).json()
    }
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO messages (tenant_id, conversation_id, role, content)"
                " VALUES (:t, :i, 'customer', 'Да, беру')"
            ),
            {"t": owner, "i": conversation_id},
        )

    late = await client.post(f"/followups/{pending[str(conversation_id)]}/send")
    assert late.json()["status"] == "expired"
    assert outbound.sent == []
    rejected = await client.post(f"/followups/{pending[str(rejected_dialog)]}/reject")
    assert rejected.json()["status"] == "rejected"
    assert (await client.post(f"/followups/{uuid.uuid4()}/reject")).status_code == 404


async def test_followup_auto_mode_respects_pause_and_failures(
    client: AsyncClient,
    owner: uuid.UUID,
    owner_engine: AsyncEngine,
    deps: Deps,
    outbound: FakeOutbound,
    told: list[Any],
) -> None:
    await _silent_dialog(owner_engine, owner)
    await client.put(
        "/automations/followup", json={"enabled": True, "settings": {"mode": "auto", **NO_QUIET}}
    )
    await client.patch("/shop", json={"bot_paused": True})
    assert await _tick(deps, owner) == 0
    assert outbound.sent == []

    await client.patch("/shop", json={"bot_paused": False})
    outbound.error = "канал недоступен"
    assert await _tick(deps, owner) == 1
    failed = (await client.get("/followups")).json()
    assert [item["status"] for item in failed] == ["failed"]
    runs = (await client.get("/automations/followup/runs")).json()
    assert runs[0]["details"]["failed"] == 1


async def test_disabling_followup_rejects_waiting_messages(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, deps: Deps, told: list[Any]
) -> None:
    await _silent_dialog(owner_engine, owner)
    await client.put("/automations/followup", json={"enabled": True, "settings": NO_QUIET})
    await _tick(deps, owner)
    await client.put("/automations/followup", json={"enabled": False})
    assert [item["status"] for item in (await client.get("/followups")).json()] == ["rejected"]


async def test_followups_of_another_shop_are_invisible(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, deps: Deps, told: list[Any]
) -> None:
    other, _, _ = await create_user(owner_engine)
    await _silent_dialog(owner_engine, other)
    await _enable(owner_engine, other, "followup", **NO_QUIET)
    await _tick(deps, other)
    async with owner_engine.connect() as conn:
        foreign = await conn.scalar(
            text("SELECT id FROM followups WHERE tenant_id = :t"), {"t": other}
        )
    assert foreign is not None
    assert (await client.get("/followups")).json() == []
    assert (await client.post(f"/followups/{foreign}/send")).status_code == 404
    assert (await client.get("/automations/followup/runs")).json() == []


async def test_failed_run_is_recorded_without_details(
    client: AsyncClient, owner: uuid.UUID, deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> int:
        raise RuntimeError("секрет в тексте ошибки")

    monkeypatch.setattr(base, "send_owner_message", broken)
    await client.put("/automations/digest", json={"enabled": True})
    run = (await client.post("/automations/digest/run")).json()
    assert run["status"] == "failed"
    assert "секрет" not in str(run)


async def test_demo_shop_can_preview_but_not_change_or_run(
    client: AsyncClient, deps: Deps, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "demo_enabled", True)
    assert (await client.post("/demo/login")).status_code == 200
    assert (await client.get("/automations")).status_code == 200
    assert (await client.post("/automations/stock/preview")).status_code == 200
    for method, path in (
        ("PUT", "/automations/stock"),
        ("POST", "/automations/stock/run"),
        ("POST", f"/followups/{uuid.uuid4()}/send"),
        ("POST", "/leads/bulk"),
    ):
        answer = await client.request(method, path, json={})
        assert (answer.status_code, answer.json()["detail"]) == (403, "demo_read_only")


def test_plural_forms() -> None:
    assert [plural(n, "товар", "товара", "товаров") for n in (1, 2, 5, 11, 21, 112)] == [
        "товар",
        "товара",
        "товаров",
        "товаров",
        "товар",
        "товаров",
    ]


async def test_scheduled_digest_is_not_repeated_when_its_state_was_lost(
    owner_engine: AsyncEngine, deps: Deps, told: list[Any]
) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    await _enable(owner_engine, tenant_id, "digest", hour=0)
    assert await _tick(deps, tenant_id) == 1
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE automations SET state = '{}', last_run_at = NULL WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    assert await _tick(deps, tenant_id) == 0
    assert len(told) == 1


async def test_run_does_not_start_or_unlock_while_another_holds_the_lock(
    client: AsyncClient, owner: uuid.UUID, deps: Deps, redis: Redis, told: list[Any]
) -> None:
    await client.put("/automations/digest", json={"enabled": True})
    lock = f"automation:{owner}:digest"
    await redis.set(lock, "чужой запуск")
    busy = await client.post("/automations/digest/run")
    assert (busy.status_code, busy.json()["detail"]) == (409, "automation_busy")
    assert await execute(owner, "digest", "schedule", deps) is None
    assert await redis.get(lock) == "чужой запуск"
    assert told == []

    await redis.delete(lock)
    assert (await client.post("/automations/digest/run")).status_code == 200
    assert await redis.get(lock) is None


async def test_followup_is_never_sent_twice_or_during_pause(
    client: AsyncClient,
    owner: uuid.UUID,
    owner_engine: AsyncEngine,
    deps: Deps,
    outbound: FakeOutbound,
    told: list[Any],
) -> None:
    conversation_id = await _silent_dialog(owner_engine, owner)
    await client.put("/automations/followup", json={"enabled": True, "settings": NO_QUIET})
    await _tick(deps, owner)
    [pending] = (await client.get("/followups", params={"status": "pending"})).json()

    blank = await client.post(f"/followups/{pending['id']}/send", json={"text": " " * 12})
    assert blank.status_code == 422
    await client.patch("/shop", json={"bot_paused": True})
    paused = await client.post(f"/followups/{pending['id']}/send")
    assert (paused.status_code, paused.json()["detail"]) == (409, "bot_paused")
    assert outbound.sent == []
    await client.patch("/shop", json={"bot_paused": False})

    async def broken_memory(conversation: uuid.UUID, body: str) -> None:
        raise RuntimeError("память бота недоступна")

    deps.remember = broken_memory
    sent = await client.post(f"/followups/{pending['id']}/send")
    assert sent.json()["status"] == "sent"
    assert len(outbound.sent) == 1

    async with owner_engine.begin() as conn:
        again = await conn.scalar(
            text(
                "INSERT INTO followups (tenant_id, conversation_id, text)"
                " VALUES (:t, :c, 'Повторное напоминание') RETURNING id"
            ),
            {"t": owner, "c": conversation_id},
        )
    repeat = await client.post(f"/followups/{again}/send")
    assert repeat.json()["status"] == "expired"
    assert len(outbound.sent) == 1
