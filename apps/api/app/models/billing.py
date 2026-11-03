import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin


class Payment(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("provider IN ('invoice', 'kaspi', 'freedompay')", name="provider"),
        CheckConstraint("status IN ('pending', 'paid', 'cancelled', 'failed')", name="status"),
        CheckConstraint("amount_kzt > 0", name="amount_kzt"),
    )

    provider: Mapped[str] = mapped_column(String(16))
    amount_kzt: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    invoice_no: Mapped[str | None] = mapped_column(String(64), unique=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class LedgerEntry(IdMixin, TimestampMixin, Base):
    __tablename__ = "ledger"
    __table_args__ = (
        CheckConstraint("type IN ('topup', 'charge', 'refund')", name="type"),
        CheckConstraint("type <> 'charge' OR amount_kzt <= 0", name="charge_sign"),
        CheckConstraint("type <> 'topup' OR amount_kzt > 0", name="topup_sign"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    type: Mapped[str] = mapped_column(String(16))
    amount_kzt: Mapped[int] = mapped_column(BigInteger)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    model: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id"), index=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"), index=True)
    comment: Mapped[str | None] = mapped_column(Text)


class AuditLog(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "audit_log"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    ip: Mapped[str | None] = mapped_column(INET)
