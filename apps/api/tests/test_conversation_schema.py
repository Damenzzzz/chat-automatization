from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_conversation_flow(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant_id = await conn.scalar(
            text("INSERT INTO tenants (name) VALUES ('Диалоги') RETURNING id")
        )
        customer_id = await conn.scalar(
            text(
                "INSERT INTO customers (tenant_id, channel, external_id) "
                "VALUES (:t, 'telegram', '42') RETURNING id"
            ),
            {"t": tenant_id},
        )
        conv = (
            await conn.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) "
                    "RETURNING id, mode, updated_at"
                ),
                {"t": tenant_id, "c": customer_id},
            )
        ).one()
        await conn.execute(
            text(
                "INSERT INTO messages (tenant_id, conversation_id, role, content) "
                "VALUES (:t, :c, 'customer', 'Есть пионы?')"
            ),
            {"t": tenant_id, "c": conv.id},
        )

    async with owner_engine.begin() as conn:
        updated_at = await conn.scalar(
            text("UPDATE conversations SET mode = 'human' WHERE id = :id RETURNING updated_at"),
            {"id": conv.id},
        )
        assert conv.mode == "bot"
        assert updated_at > conv.updated_at

        await conn.execute(text("DELETE FROM conversations WHERE id = :id"), {"id": conv.id})
        left = await conn.scalar(
            text("SELECT count(*) FROM messages WHERE conversation_id = :id"), {"id": conv.id}
        )
        assert left == 0
