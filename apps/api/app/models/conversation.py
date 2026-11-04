import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin
from app.models.tenant import CHANNEL_TYPES

LANGS = "('ru', 'kk', 'mixed')"


class Customer(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(f"channel IN {CHANNEL_TYPES}", name="channel"),
        CheckConstraint(f"lang IN {LANGS}", name="lang"),
        UniqueConstraint("tenant_id", "channel", "external_id"),
    )

    channel: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    lang: Mapped[str | None] = mapped_column(String(8))


class Conversation(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("mode IN ('bot', 'human')", name="mode"),
        CheckConstraint("status IN ('open', 'closed')", name="status"),
        Index("ix_conversations_tenant_id_last_message_at", "tenant_id", "last_message_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), index=True
    )
    mode: Mapped[str] = mapped_column(String(8), server_default="bot")
    status: Mapped[str] = mapped_column(String(8), server_default="open")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('customer', 'bot', 'manager', 'system')", name="role"),
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str | None] = mapped_column(Text)
    media: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    external_id: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(64))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class Lead(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint("status IN ('new', 'in_progress', 'done', 'cancelled')", name="status"),
        CheckConstraint("total_kzt >= 0", name="total_kzt"),
    )

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    items: Mapped[list[Any]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    total_kzt: Mapped[int | None] = mapped_column(BigInteger)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)
    delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_note: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="new")


class Unanswered(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "unanswered"

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchLog(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "search_log"
    __table_args__ = (
        CheckConstraint(f"lang IN {LANGS}", name="lang"),
        CheckConstraint("kind IN ('product', 'kb')", name="kind"),
        Index("ix_search_log_tenant_id_created_at", "tenant_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    query: Mapped[str] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String(8))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    results: Mapped[list[Any]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), server_default="product")
    result_count: Mapped[int] = mapped_column(Integer, server_default="0")
    has_in_stock: Mapped[bool | None] = mapped_column(Boolean)
