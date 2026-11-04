import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.embedding_text import kb_text
from app.core.config import get_settings
from app.mlclient import MLError, get_ml_client
from app.models import KbChunk
from app.search.candidates import enable_iterative_scan, fts_kb, vector_kb
from app.search.fusion import rrf
from app.search.lang import detect_lang
from app.search.log import record_search
from app.search.products import current_tenant, log, rerank
from app.search.types import KbHit, SearchML, SearchResult


async def search_kb(
    session: AsyncSession,
    query: str,
    *,
    ml: SearchML | None = None,
    limit: int = 3,
    lang: str | None = None,
    conversation_id: uuid.UUID | None = None,
    record: bool = True,
) -> SearchResult[KbHit]:
    started = time.perf_counter()
    settings = get_settings()
    ml = ml or get_ml_client()
    tenant_id = await current_tenant(session)
    lists: dict[str, list[uuid.UUID]] = {}
    try:
        [vector] = await ml.embed([query], "query")
    except MLError as exc:
        log.warning("search.embed_failed", error=str(exc))
    else:
        await enable_iterative_scan(session, settings.search_ef_search)
        lists["vector"] = await vector_kb(session, tenant_id, vector, settings.search_candidates)
    lists["fts"] = await fts_kb(session, tenant_id, query, settings.search_candidates)
    fused = rrf(lists, settings.search_rrf_k)[: settings.search_rerank_top]

    rows = await session.scalars(select(KbChunk).where(KbChunk.id.in_([f.id for f in fused])))
    chunks = {c.id: c for c in rows}
    pool = [f for f in fused if f.id in chunks]
    scores = await rerank(ml, query, [kb_text(chunks[f.id].title, chunks[f.id].text) for f in pool])
    ranked = [(f, scores[i] if scores else None) for i, f in enumerate(pool)]
    if scores:
        ranked.sort(key=lambda item: -(item[1] or 0.0))
    items = [
        KbHit(
            id=f.id,
            source=chunks[f.id].source,
            title=chunks[f.id].title,
            text=chunks[f.id].text,
            reasons=tuple(r for r in ("vector", "fts") if r in f.ranks),
            ranks=dict(f.ranks),
            rrf=f.score,
            score=score,
        )
        for f, score in ranked[:limit]
    ]
    lang = lang or detect_lang(query)
    latency_ms = round((time.perf_counter() - started) * 1000)
    if record:
        await record_search(
            session,
            tenant_id,
            kind="kb",
            query=query,
            lang=lang,
            items=items,
            latency_ms=latency_ms,
            conversation_id=conversation_id,
        )
    return SearchResult(
        items=items,
        lang=lang,
        latency_ms=latency_ms,
        candidates={name: len(ids) for name, ids in lists.items()},
    )
