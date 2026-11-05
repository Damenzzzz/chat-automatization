import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin

CHANNEL_TYPES = "('whatsapp', 'instagram', 'telegram', 'web')"


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('onboarding', 'active', 'suspended')", name="status"),
    )

    name: Mapped[str] = mapped_column(String(200))
    niche: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    plan: Mapped[str] = mapped_column(String(32), server_default="trial")
    status: Mapped[str] = mapped_column(String(32), server_default="onboarding")


class User(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'manager', 'admin')", name="role"),
        CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name="contact"),
        Index("uq_users_phone", "phone", unique=True),
        Index("uq_users_email", "email", unique=True),
    )

    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class BotProfile(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "bot_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version"),
        Index(
            "uq_bot_profiles_tenant_id_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    tone: Mapped[str | None] = mapped_column(Text)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    greeting: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)), server_default=text("'{ru,kk}'"))
    model_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    based_on: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Channel(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "channels"
    __table_args__ = (
        CheckConstraint(f"type IN {CHANNEL_TYPES}", name="type"),
        CheckConstraint("status IN ('pending', 'active', 'error', 'disabled')", name="status"),
        Index("uq_channels_public_key", "public_key", unique=True),
        Index("uq_channels_type_external_id", "type", "external_id", unique=True),
    )

    type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(200))
    credentials_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    webhook_secret: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    public_key: Mapped[str | None] = mapped_column(String(64))
    domain: Mapped[str | None] = mapped_column(String(253))
