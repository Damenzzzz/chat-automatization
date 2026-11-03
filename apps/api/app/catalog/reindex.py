import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from sqlalchemy import CursorResult, or_, select, text, update

from app.catalog.embedding_text import kb_text, product_text
from app.db.session import get_sessionmaker, tenant_session
from app.models import KbChunk, Product

log = structlog.get_logger()

BATCH_SIZE = 64


class Embeds(Protocol):
    async def embed(self, texts: list[str], kind: Any) -> list[list[float]]: ...


@dataclass
class ReindexStats:
    products: int = 0
    kb_chunks: int = 0
    skipped: int = 0


def _product_text(p: Product) -> str:
    return product_text(p.name, p.category, p.description, p.attributes, p.synonyms)


def _kb_text(c: KbChunk) -> str:
    return kb_text(c.title, c.text)


async def _reindex_model(
    tenant_id: uuid.UUID,
    model: type[Product] | type[KbChunk],
    to_text: Callable[[Any], str],
    ml: Embeds,
    stats: ReindexStats,
) -> int:
    done = 0
    last_id: uuid.UUID | None = None
    while True:
        async with tenant_session(tenant_id) as session:
            query = select(model).where(or_(model.embedding_stale, model.embedding.is_(None)))
            if last_id is not None:
                query = query.where(model.id > last_id)
            rows: list[Any] = list(
                await session.scalars(query.order_by(model.id).limit(BATCH_SIZE))
            )
            snapshot = [(r.id, r.updated_at, to_text(r)) for r in rows]
        if not snapshot:
            return done
        last_id = snapshot[-1][0]

        vectors = await ml.embed([t for *_, t in snapshot], "document")
        async with tenant_session(tenant_id) as session:
            for (row_id, updated_at, _), vector in zip(snapshot, vectors, strict=True):
                result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
                    update(model)
                    .where(model.id == row_id, model.updated_at == updated_at)
                    .values(embedding=vector, embedding_stale=False)
                )
                if result.rowcount:
                    done += 1
                else:
                    stats.skipped += 1


async def reindex_tenant(tenant_id: uuid.UUID, ml: Embeds) -> ReindexStats:
    stats = ReindexStats()
    stats.products = await _reindex_model(tenant_id, Product, _product_text, ml, stats)
    stats.kb_chunks = await _reindex_model(tenant_id, KbChunk, _kb_text, ml, stats)
    log.info("catalog.reindex.done", tenant_id=str(tenant_id), **vars(stats))
    return stats


async def tenants_needing_reindex() -> list[uuid.UUID]:
    async with get_sessionmaker()() as session:
        rows = await session.scalars(text("SELECT * FROM tenants_needing_reindex()"))
        return list(rows)
