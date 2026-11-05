import io
import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.billing.invoice import Seller, render_invoice
from app.core.config import get_settings
from app.routers.billing import days_left
from tests.billing_helpers import balance, login_admin, topup
from tests.conftest import FakeSender, create_user, login

SELLER = {
    "billing_seller_name": "ИП Султанбек",
    "billing_seller_iin": "900101300123",
    "billing_seller_iik": "KZ123456789012345678",
    "billing_seller_bank": "АО «Kaspi Bank»",
    "billing_seller_bik": "CASPKZKA",
}


@pytest.fixture
def requisites(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in SELLER.items():
        monkeypatch.setattr(get_settings(), key, value)


async def _charge(engine: AsyncEngine, tenant_id: uuid.UUID, amount: int, age: str = "0") -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ledger (tenant_id, type, amount_kzt, created_at) VALUES"
                " (:t, 'charge', :a, now() - make_interval(days => :d))"
            ),
            {"t": tenant_id, "a": -amount, "d": int(age)},
        )


def _pdf_text(content: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


async def test_balance_shows_spend_and_forecast(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    await topup(owner_engine, owner, 5000)
    await topup(owner_engine, owner, 3000)
    await _charge(owner_engine, owner, 700)
    await _charge(owner_engine, owner, 700, age="6")
    await _charge(owner_engine, owner, 1000, age="8")

    body = (await client.get("/balance")).json()

    assert body == {
        "balance_kzt": 5600,
        "spent_7d_kzt": 1400,
        "replies_7d": 2,
        "days_left": 28,
        "last_topup_kzt": 3000,
    }


async def test_balance_of_empty_shop(client: AsyncClient, owner: uuid.UUID) -> None:
    assert (await client.get("/balance")).json() == {
        "balance_kzt": 0,
        "spent_7d_kzt": 0,
        "replies_7d": 0,
        "days_left": None,
        "last_topup_kzt": None,
    }


@pytest.mark.parametrize(
    ("current", "spent", "expected"),
    [(700, 700, 7), (100, 700, 1), (99, 700, 0), (5000, 0, None), (0, 700, 0), (-5, 700, 0)],
)
def test_days_left(current: int, spent: int, expected: int | None) -> None:
    assert days_left(current, spent) == expected


async def test_balance_is_isolated_between_shops(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    await topup(owner_engine, other, 999)
    assert (await client.get("/balance")).json()["balance_kzt"] == 0


async def test_admin_topup_without_invoice(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    admin_id = await login_admin(client, sender)

    response = await client.post(
        f"/admin/tenants/{tenant_id}/topup",
        json={"amount_kzt": 15000, "provider": "kaspi", "comment": "перевод Kaspi"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["balance_kzt"] == 15000
    assert await balance(owner_engine, tenant_id) == 15000
    async with owner_engine.connect() as conn:
        payment = (
            await conn.execute(
                text("SELECT status, provider, confirmed_by, paid_at FROM payments WHERE id = :i"),
                {"i": response.json()["payment_id"]},
            )
        ).one()
        audited = await conn.scalar(
            text("SELECT actor_id FROM audit_log WHERE tenant_id = :t AND action = :a"),
            {"t": tenant_id, "a": "billing.topup"},
        )
    assert payment.status == "paid"
    assert payment.provider == "kaspi"
    assert payment.confirmed_by == admin_id
    assert payment.paid_at is not None
    assert audited == admin_id


async def test_topup_requires_amount_or_invoice(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    await login_admin(client, sender)
    response = await client.post(f"/admin/tenants/{tenant_id}/topup", json={})
    assert response.status_code == 422


@pytest.mark.parametrize("amount", [0, -100])
async def test_topup_rejects_non_positive_amount(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine, amount: int
) -> None:
    tenant_id, _, _ = await create_user(owner_engine)
    await login_admin(client, sender)
    response = await client.post(f"/admin/tenants/{tenant_id}/topup", json={"amount_kzt": amount})
    assert response.status_code == 422
    assert await balance(owner_engine, tenant_id) == 0


async def test_shop_owner_cannot_topup_itself(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    response = await client.post(f"/admin/tenants/{owner}/topup", json={"amount_kzt": 100})
    assert response.status_code == 403
    assert await balance(owner_engine, owner) == 0


async def test_invoice_flow_is_paid_exactly_once(
    client: AsyncClient,
    sender: FakeSender,
    owner_engine: AsyncEngine,
    requisites: None,
) -> None:
    tenant_id, _, phone = await create_user(owner_engine, tenant_name="Цветы Пион")
    await login(client, sender, phone)
    response = await client.get("/billing/invoice", params={"amount_kzt": 50000})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    number = response.headers["content-disposition"].split('"')[1].removesuffix(".pdf")

    pdf = _pdf_text(response.content)
    assert number in pdf
    assert "Цветы Пион" in pdf
    assert "50 000 ₸" in pdf
    assert "ИП Султанбек" in pdf
    assert "KZ123456789012345678" in pdf
    assert "CASPKZKA" in pdf
    assert "Без НДС" in pdf
    assert await balance(owner_engine, tenant_id) == 0

    await login_admin(client, sender)
    url = f"/admin/tenants/{tenant_id}/topup"
    paid = await client.post(url, json={"invoice_no": number})
    assert paid.status_code == 201, paid.text
    assert paid.json()["amount_kzt"] == 50000
    assert await balance(owner_engine, tenant_id) == 50000

    again = await client.post(url, json={"invoice_no": number})
    assert again.status_code == 409
    assert again.json()["detail"] == "invoice_already_paid"
    assert await balance(owner_engine, tenant_id) == 50000


async def test_repeated_invoice_request_reuses_number(
    client: AsyncClient, owner: uuid.UUID, requisites: None
) -> None:
    first = await client.get("/billing/invoice", params={"amount_kzt": 50000})
    second = await client.get("/billing/invoice", params={"amount_kzt": 50000})
    other = await client.get("/billing/invoice", params={"amount_kzt": 70000})
    name = "content-disposition"
    assert first.headers[name] == second.headers[name]
    assert first.headers[name] != other.headers[name]


async def test_invoice_amount_mismatch_and_foreign_invoice(
    client: AsyncClient,
    sender: FakeSender,
    owner_engine: AsyncEngine,
    requisites: None,
) -> None:
    tenant_id, _, phone = await create_user(owner_engine)
    other_id, _, _ = await create_user(owner_engine, tenant_name="Чужой")
    await login(client, sender, phone)
    response = await client.get("/billing/invoice", params={"amount_kzt": 50000})
    number = response.headers["content-disposition"].split('"')[1].removesuffix(".pdf")
    await login_admin(client, sender)

    wrong = await client.post(
        f"/admin/tenants/{tenant_id}/topup", json={"invoice_no": number, "amount_kzt": 1}
    )
    assert wrong.status_code == 409
    assert wrong.json()["detail"] == "amount_mismatch"

    foreign = await client.post(f"/admin/tenants/{other_id}/topup", json={"invoice_no": number})
    assert foreign.status_code == 404
    assert await balance(owner_engine, other_id) == 0


async def test_invoice_without_requisites_is_refused(client: AsyncClient, owner: uuid.UUID) -> None:
    response = await client.get("/billing/invoice", params={"amount_kzt": 50000})
    assert response.status_code == 503
    assert response.json()["detail"] == "billing_requisites_not_configured"


@pytest.mark.parametrize("amount", [999, 100_000_001, 0])
async def test_invoice_amount_bounds(
    client: AsyncClient, owner: uuid.UUID, requisites: None, amount: int
) -> None:
    response = await client.get("/billing/invoice", params={"amount_kzt": amount})
    assert response.status_code == 422


async def test_manager_sees_balance_but_cannot_issue_invoice(
    client: AsyncClient,
    owner: uuid.UUID,
    sender: FakeSender,
    owner_engine: AsyncEngine,
    requisites: None,
) -> None:
    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)
    assert (await client.get("/balance")).status_code == 200
    response = await client.get("/billing/invoice", params={"amount_kzt": 50000})
    assert response.status_code == 403


def test_pdf_renders_kazakh_letters_and_tenge_sign() -> None:
    seller = Seller("ИП Әлібек", "1", "KZ1", "Банк", "BIK", "19", "859", "Алматы", "Без НДС")
    content = render_invoice(
        number="SAT-2026-000001",
        issued=date(2026, 11, 5),
        amount_kzt=1234567,
        buyer="«Гүлдер» ЖШС: ӘҒҚҢӨҰҮҺІ",
        seller=seller,
    )
    pdf = _pdf_text(content)
    assert "ӘҒҚҢӨҰҮҺІ" in pdf
    assert "1 234 567 ₸" in pdf
    assert "05.11.2026" in pdf
