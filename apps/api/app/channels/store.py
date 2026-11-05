import uuid
from typing import Any

from sqlalchemy import text

from app.channels.types import ChannelConfig
from app.core.crypto import decrypt_json
from app.db.session import get_sessionmaker


def _config(row: Any) -> ChannelConfig:
    return ChannelConfig(
        id=row.id,
        tenant_id=row.tenant_id,
        type=row.type,
        status=row.status,
        webhook_secret=row.webhook_secret,
        domain=row.domain,
        credentials=decrypt_json(row.credentials_enc) if row.credentials_enc else {},
    )


async def load_channel(channel_id: uuid.UUID) -> ChannelConfig | None:
    async with get_sessionmaker()() as session:
        row = (
            await session.execute(text("SELECT * FROM channel_lookup(:p)"), {"p": channel_id})
        ).first()
    return _config(row) if row else None


async def load_channel_by_key(public_key: str) -> ChannelConfig | None:
    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                text("SELECT * FROM channel_by_public_key(:p)"), {"p": public_key}
            )
        ).first()
    return _config(row) if row else None
