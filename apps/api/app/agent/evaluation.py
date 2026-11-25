"""Проверки ответа бота для сценарного замера (scripts/eval_agent.py)."""

import statistics
from collections.abc import Sequence
from typing import Any

from app.agent.guard import numbers
from app.channels.outgoing import mentioned_products

CHECKS = ("intent", "lang", "products", "kb", "reply", "handoff", "unanswered", "clean")
CHECK_NAMES = {
    "intent": "намерение",
    "lang": "язык ответа",
    "products": "нужный товар в ответе",
    "kb": "нужная статья базы знаний",
    "reply": "обязательный текст в ответе",
    "handoff": "передача менеджеру",
    "unanswered": "отметка «не знал ответа»",
    "clean": "ответ прошёл проверку с первого раза",
}


def named_skus(reply: str, context: list[dict[str, Any]]) -> set[str | None]:
    """Товары, названные в ответе: по названию или артикулу, а если бот перевёл
    название (казахский ответ) — по цене товара из данных."""
    products = [c for c in context if c.get("type") == "product"]
    by_id = {c["id"]: c.get("sku") for c in products}
    named = {by_id.get(i) for i in mentioned_products(reply, products, limit=None)}
    said = numbers(reply)
    named |= {c.get("sku") for c in products if c.get("price") and c["price"] in said}
    return named


def judge(expect: dict[str, Any], lang: str, turn: dict[str, Any]) -> dict[str, bool]:
    """turn: reply, intent, lang, human_mode, context, trace последнего хода."""
    reply = turn.get("reply") or ""
    context = turn.get("context", [])
    trace = turn.get("trace", [])
    checks: dict[str, bool] = {}
    if "intent" in expect:
        checks["intent"] = turn.get("intent") == expect["intent"]
    if lang in ("ru", "kk"):
        checks["lang"] = turn.get("lang") == lang
    if "skus_any" in expect:
        checks["products"] = bool(named_skus(reply, context) & set(expect["skus_any"]))
    if "kb_any" in expect:
        sources = {c.get("source") for c in context if c.get("type") == "kb"}
        checks["kb"] = bool(sources & set(expect["kb_any"]))
    if "reply_has" in expect:
        folded = reply.casefold().replace(" ", " ")
        checks["reply"] = all(part.casefold() in folded for part in expect["reply_has"])
    if "handoff" in expect:
        checks["handoff"] = bool(turn.get("human_mode")) == expect["handoff"]
    if "unanswered" in expect:
        meter: dict[str, Any] = next((t for t in trace if t.get("node") == "meter"), {})
        checks["unanswered"] = bool(meter.get("unanswered")) == expect["unanswered"]
    guards = [t for t in trace if t.get("node") == "guard_out"]
    fell_back = any(t.get("node") == "fallback" for t in trace)
    checks["clean"] = not fell_back and (not guards or bool(guards[0].get("ok")))
    return checks


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_check: dict[str, dict[str, float]] = {}
    for name in CHECKS:
        values = [r["checks"][name] for r in rows if name in r["checks"]]
        if values:
            by_check[name] = {"n": len(values), "rate": sum(values) / len(values)}
    passed = [all(r["checks"].values()) for r in rows]
    latency = [ms for r in rows for ms in r.get("latency_ms", [])]
    return {
        "scenarios": len(rows),
        "passed": sum(passed) / (len(passed) or 1),
        "checks": by_check,
        "fallbacks": sum(1 for r in rows if r.get("fallback")) / (len(rows) or 1),
        "latency_p50": statistics.median(latency) if latency else 0.0,
        "latency_max": max(latency) if latency else 0.0,
    }


def render(date: str, models: dict[str, str], summary: dict[str, Any], rows: list[Any]) -> str:
    lines = [
        f"# Качество ответов бота — {date}",
        "",
        "Сценарии: `eval/agent_scenarios.jsonl`, демо-магазин «Цветы Пион», песочница"
        " (тот же граф, без каналов и списаний).",
        "Модели: " + ", ".join(f"{k} — {v}" for k, v in models.items()) + ".",
        "",
        f"Сценариев: {summary['scenarios']}, пройдено целиком: {summary['passed']:.0%}."
        f" Ответ заменён шаблоном «уточню у менеджера»: {summary['fallbacks']:.0%}.",
        f"Время хода: медиана {summary['latency_p50'] / 1000:.1f} с,"
        f" максимум {summary['latency_max'] / 1000:.1f} с.",
        "",
        "| Проверка | Сценариев | Успешно |",
        "| --- | ---: | ---: |",
    ]
    for name, value in summary["checks"].items():
        lines.append(f"| {CHECK_NAMES[name]} | {value['n']} | {value['rate']:.0%} |")
    lines += ["", "## Не прошли", ""]
    failed = [r for r in rows if not all(r["checks"].values())]
    for r in failed:
        bad = ", ".join(CHECK_NAMES[k] for k, ok in r["checks"].items() if not ok)
        lines.append(f"- {r['id']}. [{r['lang']}] «{r['turns'][-1]}» — {bad}.")
        lines.append(f"  Ответ: «{(r.get('reply') or '').strip()[:300]}»")
    if not failed:
        lines.append("- нет")
    return "\n".join(lines) + "\n"
