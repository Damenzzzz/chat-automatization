import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

MODES = ("vector", "hybrid", "hybrid+rerank")
GROUPS = ("ru", "kk", "mixed", "all")


def recall_at(expected: Sequence[str], got: Sequence[str], k: int) -> float:
    if not expected:
        return 0.0
    return len(set(expected) & set(got[:k])) / len(set(expected))


def reciprocal_rank(expected: Sequence[str], got: Sequence[str], k: int = 10) -> float:
    wanted = set(expected)
    for rank, sku in enumerate(got[:k], start=1):
        if sku in wanted:
            return 1.0 / rank
    return 0.0


@dataclass
class Scored:
    lang: str
    recall5: float
    recall10: float
    rr: float


def score(lang: str, expected: Sequence[str], got: Sequence[str]) -> Scored:
    return Scored(
        lang,
        recall_at(expected, got, 5),
        recall_at(expected, got, 10),
        reciprocal_rank(expected, got),
    )


def aggregate(rows: Iterable[Scored]) -> dict[str, dict[str, float]]:
    rows = list(rows)
    out: dict[str, dict[str, float]] = {}
    for group in GROUPS:
        part = [r for r in rows if group == "all" or r.lang == group]
        if not part:
            continue
        out[group] = {
            "n": len(part),
            "recall5": statistics.fmean(r.recall5 for r in part),
            "recall10": statistics.fmean(r.recall10 for r in part),
            "mrr": statistics.fmean(r.rr for r in part),
        }
    return out


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def render_table(runs: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    for group in GROUPS:
        lines += [
            f"### {group}",
            "",
            "| Модель | Режим | Recall@5 | Recall@10 | MRR |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for run in runs:
            for mode in MODES:
                m = run["metrics"].get(mode, {}).get(group)
                if m:
                    lines.append(
                        f"| {run['label']} | {mode} | {m['recall5']:.3f} | {m['recall10']:.3f}"
                        f" | {m['mrr']:.3f} |"
                    )
        lines.append("")
    lines += [
        "### Задержка поиска с реранкером",
        "",
        "| Модель | p50, мс | p95, мс |",
        "| --- | ---: | ---: |",
    ]
    lines += [
        f"| {run['label']} | {run['latency']['p50']:.0f} | {run['latency']['p95']:.0f} |"
        for run in runs
    ]
    return "\n".join(lines) + "\n"


def render_report(date: str, runs: Sequence[dict[str, Any]], queries: int) -> str:
    parts = [
        f"# Качество поиска — {date}",
        "",
        f"Набор: `eval/queries.jsonl`, {queries} запросов к демо-каталогу «Цветы Пион».",
        "Режимы: `vector` — только pgvector; `hybrid` — vector + fts + sku через RRF;"
        " `hybrid+rerank` — полный конвейер `search_products`.",
        "",
        render_table(runs),
    ]
    for run in runs:
        misses = run.get("misses", [])
        parts += [f"## Промахи {run['label']} (hybrid+rerank, нет ожидаемого в топ-5)", ""]
        parts += [
            f"- [{m['lang']}] «{m['query']}»: ждали {', '.join(m['expected'])},"
            f" получили {', '.join(m['got'][:5]) or '—'}"
            for m in misses
        ] or ["- нет"]
        parts.append("")
    return "\n".join(parts)
