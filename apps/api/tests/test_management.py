import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.routers.conversations import clean_tags
from app.routers.leads import csv_cell
from tests.agent_helpers import make_conversation
from tests.conftest import FakeSender, create_user, login


async def _me(client: AsyncClient) -> str:
    return str((await client.get("/me")).json()["user_id"])


async def _lead(engine: AsyncEngine, tenant_id: uuid.UUID, **values: object) -> str:
    fields = {"tenant_id": tenant_id, **values}
    names = ", ".join(fields)
    marks = ", ".join(f":{name}" for name in fields)
    async with engine.begin() as conn:
        lead_id = await conn.scalar(
            text(f"INSERT INTO leads ({names}) VALUES ({marks}) RETURNING id"),  # noqa: S608
            fields,
        )
    return str(lead_id)


async def _dialog(engine: AsyncEngine, tenant_id: uuid.UUID, mode: str = "bot") -> uuid.UUID:
    _, conversation_id = await make_conversation(engine, tenant_id, mode=mode)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE conversations SET last_message_at = now() WHERE id = :i"),
            {"i": conversation_id},
        )
    return conversation_id


async def test_lead_gets_assignee_reminder_note_and_cancel_reason(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    lead_id = await _lead(owner_engine, owner, total_kzt=9000)
    me = await _me(client)
    remind = (datetime.now(UTC) + timedelta(hours=3)).isoformat()

    saved = await client.patch(
        f"/leads/{lead_id}",
        json={"assignee_id": me, "remind_at": remind, "note": "  Перезвонить  "},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert (body["assignee_id"], body["note"], body["status"]) == (me, "Перезвонить", "new")
    assert body["assignee_name"] and body["remind_at"] and body["number"] == lead_id[:8]

    early = await client.patch(f"/leads/{lead_id}", json={"cancel_reason": "price"})
    assert (early.status_code, early.json()["detail"]) == (409, "lead_not_cancelled")

    cancelled = await client.patch(
        f"/leads/{lead_id}", json={"status": "cancelled", "cancel_reason": "price"}
    )
    assert cancelled.json()["cancel_reason"] == "price"
    assert cancelled.json()["remind_at"] is None

    late = await client.patch(f"/leads/{lead_id}", json={"remind_at": remind})
    assert (late.status_code, late.json()["detail"]) == (409, "lead_closed")

    reopened = (await client.patch(f"/leads/{lead_id}", json={"status": "in_progress"})).json()
    assert reopened["cancel_reason"] is None
    assert reopened["note"] == "Перезвонить"
    naive = await client.patch(f"/leads/{lead_id}", json={"remind_at": "2026-12-01T10:00:00"})
    assert naive.status_code == 422


async def test_lead_cannot_be_assigned_to_stranger(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    lead_id = await _lead(owner_engine, owner)
    _, stranger, _ = await create_user(owner_engine)
    answer = await client.patch(f"/leads/{lead_id}", json={"assignee_id": str(stranger)})
    assert (answer.status_code, answer.json()["detail"]) == (422, "assignee_not_found")
    bulk = await client.post("/leads/bulk", json={"ids": [lead_id], "assignee_id": str(stranger)})
    assert bulk.status_code == 422


async def test_lead_filters_counts_and_search(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    me = await _me(client)
    past = datetime.now(UTC) - timedelta(hours=1)
    mine = await _lead(
        owner_engine, owner, assignee_id=me, remind_at=past, contact_name="Айгерим 100%"
    )
    free = await _lead(owner_engine, owner, contact_phone="+77001112233")
    await _lead(owner_engine, owner, status="done", assignee_id=me, remind_at=past)

    everything = (await client.get("/leads")).json()
    assert everything["counts"] == {
        "new": 2,
        "in_progress": 0,
        "done": 1,
        "cancelled": 0,
        "overdue": 1,
        "mine": 1,
    }

    async def ids(**params: str) -> list[str]:
        found = (await client.get("/leads", params=params)).json()["items"]
        return [item["id"] for item in found]

    assert await ids(assignee="me", status="new") == [mine]
    assert await ids(assignee="none") == [free]
    assert await ids(assignee=me, status="new") == [mine]
    assert await ids(due="true") == [mine]
    assert await ids(q="100%") == [mine]
    assert await ids(q="_") == []
    assert await ids(q="111-22") == [free]
    assert await ids(q=free[:6]) == [free]
    assert (await client.get("/leads", params={"assignee": "кто-то"})).status_code == 422


async def test_bulk_update_changes_only_own_shop(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine)
    foreign = await _lead(owner_engine, other)
    first = await _lead(owner_engine, owner, cancel_reason=None)
    second = await _lead(owner_engine, owner, status="cancelled", cancel_reason="price")

    done = await client.post(
        "/leads/bulk", json={"ids": [first, second, foreign], "status": "done"}
    )
    assert done.json() == {"updated": 2}
    rows = {item["id"]: item for item in (await client.get("/leads")).json()["items"]}
    assert rows[second]["status"] == "done"
    assert rows[second]["cancel_reason"] is None
    async with owner_engine.connect() as conn:
        untouched = await conn.scalar(
            text("SELECT status FROM leads WHERE id = :i"), {"i": foreign}
        )
    assert untouched == "new"

    empty = await client.post("/leads/bulk", json={"ids": [first]})
    assert (empty.status_code, empty.json()["detail"]) == (422, "nothing_to_update")
    assert (await client.post("/leads/bulk", json={"ids": [], "status": "done"})).status_code == 422


async def test_export_is_csv_for_owner_only(
    client: AsyncClient, sender: FakeSender, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    await _lead(
        owner_engine,
        owner,
        contact_name="=HYPERLINK(1)",
        contact_phone="+77001112233",
        total_kzt=15000,
        note="срочно; до обеда",
    )
    other, _, _ = await create_user(owner_engine)
    await _lead(owner_engine, other, contact_name="Чужой")

    answer = await client.get("/leads/export")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/csv")
    assert "attachment" in answer.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(answer.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 2
    line = dict(zip(rows[0], rows[1], strict=True))
    assert line["Имя"] == "'=HYPERLINK(1)"
    assert line["Телефон"] == "'+77001112233"
    assert line["Заметка"] == "срочно; до обеда"
    assert line["Статус"] == "Новая"

    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)
    assert (await client.get("/leads/export")).status_code == 403


def test_csv_cell_defuses_formulas() -> None:
    assert csv_cell("@SUM(A1)") == "'@SUM(A1)"
    assert csv_cell("-5") == "'-5"
    assert csv_cell("Айгерим") == "Айгерим"
    assert csv_cell(None) == ""
    assert csv_cell(15000) == "15000"


async def test_takeover_assigns_dialog_and_release_frees_it(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    conversation_id = await _dialog(owner_engine, owner)
    me = await _me(client)

    taken = (await client.post(f"/conversations/{conversation_id}/takeover")).json()
    assert (taken["assignee_id"], taken["mode"]) == (me, "human")
    counts = (await client.get("/conversations")).json()["counts"]
    assert (counts["mine"], counts["unassigned"]) == (1, 0)
    mine = (await client.get("/conversations", params={"filter": "mine"})).json()["items"]
    assert [item["id"] for item in mine] == [str(conversation_id)]

    released = (await client.post(f"/conversations/{conversation_id}/release")).json()
    assert released["assignee_id"] is None


async def test_dialog_is_handed_to_teammate_only(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    conversation_id = await _dialog(owner_engine, owner, mode="human")
    _, teammate, _ = await create_user(owner_engine, role="manager", tenant_id=owner)
    _, stranger, _ = await create_user(owner_engine)

    unassigned = (await client.get("/conversations", params={"filter": "unassigned"})).json()
    assert [item["id"] for item in unassigned["items"]] == [str(conversation_id)]

    handed = await client.patch(
        f"/conversations/{conversation_id}", json={"assignee_id": str(teammate)}
    )
    assert handed.json()["assignee_id"] == str(teammate)
    assert handed.json()["assignee_name"]
    refused = await client.patch(
        f"/conversations/{conversation_id}", json={"assignee_id": str(stranger)}
    )
    assert refused.status_code == 422
    cleared = await client.patch(f"/conversations/{conversation_id}", json={"assignee_id": None})
    assert cleared.json()["assignee_id"] is None


async def test_customer_tags_filter_dialogs_and_keep_note(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    tagged = await _dialog(owner_engine, owner)
    await _dialog(owner_engine, owner)
    await client.patch(f"/conversations/{tagged}/customer", json={"note": "Любит пионы"})

    saved = await client.patch(
        f"/conversations/{tagged}/customer", json={"tags": [" Опт ", "опт", "", "VIP  клиент"]}
    )
    assert saved.json()["tags"] == ["Опт", "VIP клиент"]
    assert saved.json()["note"] == "Любит пионы"

    found = (await client.get("/conversations", params={"tag": "Опт"})).json()["items"]
    assert [item["id"] for item in found] == [str(tagged)]
    assert found[0]["tags"] == ["Опт", "VIP клиент"]
    assert (await client.get("/conversations/tags")).json() == [
        {"tag": "VIP клиент", "count": 1},
        {"tag": "Опт", "count": 1},
    ]


def test_tags_are_trimmed_deduplicated_and_capped() -> None:
    assert clean_tags(["a" * 50]) == ["a" * 30]
    assert len(clean_tags([f"тег {n}" for n in range(30)])) == 10
