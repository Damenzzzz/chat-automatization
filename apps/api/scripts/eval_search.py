import argparse
import asyncio
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, update

from app.catalog.reindex import reindex_tenant
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import tenant_session
from app.mlclient import get_ml_client
from app.models import KbChunk, Product
from app.search import search_products
from app.search.candidates import enable_iterative_scan, vector_products
from app.search.evaluation import aggregate, percentile, render_report, render_table, score
from app.search.types import ProductFilters
from app.seed import DEMO_TENANT_ID, seed_demo

ROOT = Path(__file__).resolve().parents[1]


def load_queries(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def ml_backends(wait: float = 1200) -> dict[str, str]:
    deadline = time.monotonic() + wait
    async with httpx.AsyncClient(base_url=get_settings().ml_url, timeout=10) as http:
        while True:
            try:
                health = (await http.get("/health")).json()
            except httpx.HTTPError:
                health = {"status": "unreachable"}
            if health.get("status") == "ok":
                return {
                    "embedder": health["embedder"]["model"],
                    "reranker": health["reranker"]["model"],
                }
            if health.get("status") == "error" or time.monotonic() > deadline:
                raise SystemExit(f"ML-сервис не готов: {health}")
            await asyncio.sleep(5)


async def reindex_demo() -> None:
    await seed_demo()
    async with tenant_session(DEMO_TENANT_ID) as session:
        await session.execute(update(Product).values(embedding_stale=True))
        await session.execute(update(KbChunk).values(embedding_stale=True))
    stats = await reindex_tenant(DEMO_TENANT_ID, get_ml_client())
    print(f"переиндексация: {stats.products} товаров, {stats.kb_chunks} кусков базы знаний")


async def vector_skus(query: str) -> list[str]:
    settings = get_settings()
    [vector] = await get_ml_client().embed([query], "query")
    async with tenant_session(DEMO_TENANT_ID) as session:
        await enable_iterative_scan(session, settings.search_ef_search)
        ids = await vector_products(session, DEMO_TENANT_ID, vector, ProductFilters(), 10)
        rows = await session.execute(select(Product.id, Product.sku).where(Product.id.in_(ids)))
        sku = {row.id: row.sku for row in rows}
    return [sku[i] or "" for i in ids]


async def run(
    queries: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[float]]:
    got: dict[str, list[list[str]]] = {"vector": [], "hybrid": [], "hybrid+rerank": []}
    latency: list[float] = []
    for i, item in enumerate(queries, start=1):
        got["vector"].append(await vector_skus(item["query"]))
        async with tenant_session(DEMO_TENANT_ID) as session:
            hybrid = await search_products(
                session, item["query"], limit=10, use_reranker=False, record=False
            )
            started = time.perf_counter()
            full = await search_products(session, item["query"], limit=10, record=False)
            latency.append((time.perf_counter() - started) * 1000)
        got["hybrid"].append([h.sku or "" for h in hybrid.items])
        got["hybrid+rerank"].append([h.sku or "" for h in full.items])
        print(f"\r{i}/{len(queries)}", end="", flush=True)
    print()
    metrics = {
        mode: aggregate(
            score(q["lang"], q["expected"], g) for q, g in zip(queries, lists, strict=True)
        )
        for mode, lists in got.items()
    }
    misses = [
        {"id": q["id"], "lang": q["lang"], "query": q["query"], "expected": q["expected"], "got": g}
        for q, g in zip(queries, got["hybrid+rerank"], strict=True)
        if not set(q["expected"]) & set(g[:5])
    ]
    return metrics, misses, latency


async def main() -> None:
    parser = argparse.ArgumentParser(description="Recall@5/10 и MRR поиска по демо-каталогу")
    parser.add_argument("--label", help="имя прогона; по умолчанию — модели из /health ML")
    parser.add_argument("--queries", type=Path, default=ROOT / "eval" / "queries.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--no-reindex", action="store_true")
    args = parser.parse_args()
    configure_logging("WARNING")

    backends = await ml_backends()
    label = args.label or backends["embedder"].split("/")[-1]
    if not args.no_reindex:
        await reindex_demo()
    queries = load_queries(args.queries)
    metrics, misses, latency = await run(queries)

    args.out.mkdir(parents=True, exist_ok=True)
    result = {
        "label": label,
        "date": args.date,
        **backends,
        "metrics": metrics,
        "latency": {"p50": percentile(latency, 0.5), "p95": percentile(latency, 0.95)},
        "misses": misses,
    }
    (args.out / f"{args.date}-{label}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    runs = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(args.out.glob(f"{args.date}-*.json"))
    ]
    (args.out / f"{args.date}.md").write_text(
        render_report(args.date, runs, len(queries)), encoding="utf-8"
    )
    print(render_table(runs))


if __name__ == "__main__":
    asyncio.run(main())
