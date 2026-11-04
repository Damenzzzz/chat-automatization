import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from app.search.evaluation import aggregate, recall_at, reciprocal_rank, render_report, score

ROOT = Path(__file__).resolve().parents[1]


def test_recall_and_mrr() -> None:
    got = ["A", "B", "C", "D", "E", "F"]
    assert recall_at(["B", "F", "Z"], got, 5) == pytest.approx(1 / 3)
    assert recall_at(["B", "F", "Z"], got, 10) == pytest.approx(2 / 3)
    assert reciprocal_rank(["C", "F"], got) == pytest.approx(1 / 3)
    assert reciprocal_rank(["Z"], got) == 0.0


def test_aggregate_by_language() -> None:
    rows = [score("ru", ["A"], ["A"]), score("kk", ["A"], ["B", "A"]), score("kk", ["A"], [])]
    stats = aggregate(rows)
    assert stats["ru"]["mrr"] == 1.0
    assert stats["kk"]["mrr"] == pytest.approx(0.25)
    assert stats["kk"]["recall5"] == pytest.approx(0.5)
    assert stats["all"]["n"] == 3
    assert "mixed" not in stats


def test_report_renders_runs() -> None:
    run = {
        "label": "qwen3",
        "metrics": {"vector": aggregate([score("ru", ["A"], ["A"])])},
        "latency": {"p50": 120.0, "p95": 300.0},
        "misses": [],
    }
    report = render_report("2026-11-04", [run], 1)
    assert "| qwen3 | vector | 1.000 | 1.000 | 1.000 |" in report
    assert "| qwen3 | 120 | 300 |" in report


def test_eval_queries_cover_demo_catalog() -> None:
    queries = [
        json.loads(line)
        for line in (ROOT / "eval" / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    with (ROOT / "fixtures" / "pion_products.csv").open(encoding="utf-8") as f:
        skus = {row["sku"] for row in csv.DictReader(f)}
    assert len(queries) == 60
    assert Counter(q["lang"] for q in queries) == {"ru": 30, "kk": 15, "mixed": 15}
    assert len({q["id"] for q in queries}) == 60
    assert all(q["expected"] and set(q["expected"]) <= skus for q in queries)
