"""Оценки реранкера для запросов из каталога и мимо него: где ставить порог релевантности."""

import argparse
import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any

from app.core.logging import configure_logging
from app.db.session import tenant_session
from app.search import search_kb, search_products
from app.search.evaluation import threshold_rows
from app.seed import DEMO_TENANT_ID
from scripts.eval_search import ROOT, load_queries, ml_backends, reindex

GRID = (0.001, 0.003, 0.01, 0.02, 0.03, 0.05, 0.1, 0.2, 0.3, 0.5)


async def product_scores(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in queries:
        async with tenant_session(DEMO_TENANT_ID) as session:
            found = await search_products(session, item["query"], limit=5, record=False)
        expected = set(item.get("expected", []))
        relevant = [h.score for h in found.items if h.sku in expected and h.score is not None]
        rows.append(
            {
                "query": item["query"],
                "lang": item["lang"],
                "positive": bool(expected),
                "relevant": max(relevant) if relevant else None,
                "top": max((h.score or 0.0 for h in found.items), default=0.0),
                "got": [h.sku for h in found.items],
            }
        )
    return rows


async def kb_scores(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in queries:
        async with tenant_session(DEMO_TENANT_ID) as session:
            found = await search_kb(session, item["query"], limit=3, record=False)
        expected = set(item["expected"])
        relevant = [h.score for h in found.items if h.source in expected and h.score is not None]
        rows.append(
            {
                "query": item["query"],
                "lang": item["lang"],
                "positive": bool(expected),
                "relevant": max(relevant) if relevant else None,
                "top": max((h.score or 0.0 for h in found.items), default=0.0),
                "got": [h.source for h in found.items],
            }
        )
    return rows


def table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Порог | Оставлено нужных | Отсечено лишних (запросы мимо) |",
        "| ---: | ---: | ---: |",
    ]
    for t, kept, rejected in threshold_rows(rows, GRID):
        lines.append(f"| {t:g} | {kept:.0%} | {rejected:.0%} |")
    return lines


def scores_list(rows: list[dict[str, Any]], positive: bool) -> list[str]:
    out = []
    for r in rows:
        if r["positive"] != positive:
            continue
        value = r["relevant"] if positive else r["top"]
        shown = "нет в топе" if value is None else f"{value:.4f}"
        out.append(f"- [{r['lang']}] «{r['query']}»: {shown} ({', '.join(r['got'][:3])})")
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--no-reindex", action="store_true")
    args = parser.parse_args()
    configure_logging("WARNING")

    backends = await ml_backends()
    if not args.no_reindex:
        await reindex(DEMO_TENANT_ID)
    products = await product_scores(
        load_queries(ROOT / "eval" / "queries.jsonl")
        + load_queries(ROOT / "eval" / "queries_negative.jsonl")
    )
    articles = await kb_scores(load_queries(ROOT / "eval" / "kb_queries.jsonl"))

    report = [
        f"# Порог релевантности — {args.date}",
        "",
        f"Модели: {backends['embedder']}, реранкер {backends['reranker']}."
        " Каталог «Цветы Пион», полный конвейер поиска.",
        "Нужные — запросы `eval/queries.jsonl` (оценка лучшего ожидаемого товара в топ-5),"
        " лишние — `eval/queries_negative.jsonl` (лучшая оценка в топ-5)."
        " База знаний — `eval/kb_queries.jsonl`.",
        "",
        "## Товары",
        "",
        *table(products),
        "",
        "## База знаний",
        "",
        *table(articles),
        "",
        "## Оценки: товары мимо каталога",
        "",
        *scores_list(products, positive=False),
        "",
        "## Оценки: вопросы мимо базы знаний",
        "",
        *scores_list(articles, positive=False),
        "",
        "## Оценки: нужные статьи базы знаний",
        "",
        *scores_list(articles, positive=True),
        "",
    ]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.date}-threshold.json").write_text(
        json.dumps({"products": products, "kb": articles}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.out / f"{args.date}-threshold.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    asyncio.run(main())
