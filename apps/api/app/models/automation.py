import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin

AUTOMATION_KINDS = ("digest", "stock", "followup", "lead_reminders")


class Automation(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "automations"
    __table_args__ = (
        CheckConstraint(f"kind IN {AUTOMATION_KINDS}", name="kind"),
        UniqueConstraint("tenant_id", "kind"),
    )

    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AutomationRun(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "automation_runs"
    __table_args__ = (
        CheckConstraint(f"kind IN {AUTOMATION_KINDS}", name="kind"),
        CheckConstraint("trigger IN ('schedule', 'manual')", name="trigger"),
        CheckConstraint("status IN ('ok', 'empty', 'failed')", name="status"),
        Index("ix_automation_runs_tenant_id_kind_created_at", "tenant_id", "kind", "created_at"),
    )

    kind: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))


class Followup(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "followups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'rejected', 'expired', 'failed')", name="status"
        ),
        Index("ix_followups_tenant_id_status_created_at", "tenant_id", "status", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
