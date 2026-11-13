import argparse
import asyncio
import csv
import datetime as dt
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.catalog.reindex import reindex_tenant
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import tenant_session
from app.mlclient import get_ml_client
from app.models import KbChunk, Product, Tenant
from app.search import search_products
from app.search.candidates import enable_iterative_scan, vector_products
from app.search.evaluation import aggregate, percentile, render_report, render_table, score
from app.search.types import ProductFilters
from app.seed import DEMO_TENANT_ID, seed_demo

ROOT = Path(__file__).resolve().parents[1]
# Отдельный магазин без пользователей: войти в него нельзя, демо-каталог он не трогает.
MIXED_TENANT_ID = uuid.UUID("7e1a1700-0000-4000-8000-00000000e001")
CATALOGS = {
    "demo": (DEMO_TENANT_ID, "queries.jsonl", "демо-каталогу «Цветы Пион»"),
    "mixed": (
        MIXED_TENANT_ID,
        "queries_mixed.jsonl",
        "смешанному каталогу: автозапчасти, электроника, одежда и обувь, косметика",
    ),
}


async def seed_mixed() -> None:
    with (ROOT / "eval" / "catalogs" / "mixed_products.csv").open(encoding="utf-8") as f:
        products = [
            {
                "tenant_id": MIXED_TENANT_ID,
                "sku": row["sku"],
                "name": row["name"],
                "category": row["category"],
                "price": int(row["price"]),
                "stock": int(row["stock"]),
                "description": row["description"],
                "synonyms": row["synonyms"] or None,
            }
            for row in csv.DictReader(f)
        ]
    async with tenant_session(MIXED_TENANT_ID) as session:
        tenant = {"id": MIXED_TENANT_ID, "name": "Проверка поиска", "status": "onboarding"}
        await session.execute(
            insert(Tenant).values(tenant).on_conflict_do_nothing(index_elements=[Tenant.id])
        )
        stmt = insert(Product).values(products)
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_products_tenant_id_sku_norm",
                set_={
                    col: stmt.excluded[col]
                    for col in ("name", "category", "price", "stock", "description", "synonyms")
                },
            )
        )


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


async def reindex(tenant_id: uuid.UUID) -> None:
    if tenant_id == DEMO_TENANT_ID:
        await seed_demo()
    else:
        await seed_mixed()
    async with tenant_session(tenant_id) as session:
        await session.execute(update(Product).values(embedding_stale=True))
        await session.execute(update(KbChunk).values(embedding_stale=True))
    stats = await reindex_tenant(tenant_id, get_ml_client())
    print(f"переиндексация: {stats.products} товаров, {stats.kb_chunks} кусков базы знаний")


async def vector_skus(tenant_id: uuid.UUID, query: str) -> list[str]:
    settings = get_settings()
    [vector] = await get_ml_client().embed([query], "query")
    async with tenant_session(tenant_id) as session:
        await enable_iterative_scan(session, settings.search_ef_search)
        ids = await vector_products(session, tenant_id, vector, ProductFilters(), 10)
        rows = await session.execute(select(Product.id, Product.sku).where(Product.id.in_(ids)))
        sku = {row.id: row.sku for row in rows}
    return [sku[i] or "" for i in ids]


async def run(
    tenant_id: uuid.UUID,
    queries: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[float]]:
    got: dict[str, list[list[str]]] = {"vector": [], "hybrid": [], "hybrid+rerank": []}
    latency: list[float] = []
    for i, item in enumerate(queries, start=1):
        got["vector"].append(await vector_skus(tenant_id, item["query"]))
        async with tenant_session(tenant_id) as session:
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
    parser.add_argument("--catalog", choices=sorted(CATALOGS), default="demo")
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--no-reindex", action="store_true")
    args = parser.parse_args()
    configure_logging("WARNING")

    backends = await ml_backends()
    label = args.label or backends["embedder"].split("/")[-1]
    tenant_id, queries_file, about = CATALOGS[args.catalog]
    if not args.no_reindex:
        await reindex(tenant_id)
    queries_path = args.queries or ROOT / "eval" / queries_file
    queries = load_queries(queries_path)
    metrics, misses, latency = await run(tenant_id, queries)

    if args.catalog != "demo":
        args.out = args.out / args.catalog
    args.out.mkdir(parents=True, exist_ok=True)
    result = {
        "label": label,
        "date": args.date,
        "settings": {
            "search_candidates": get_settings().search_candidates,
            "search_rerank_top": get_settings().search_rerank_top,
            "search_rrf_k": get_settings().search_rrf_k,
        },
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
        render_report(args.date, runs, len(queries), f"`eval/{queries_path.name}`", about),
        encoding="utf-8",
    )
    print(render_table(runs))


if __name__ == "__main__":
    asyncio.run(main())
