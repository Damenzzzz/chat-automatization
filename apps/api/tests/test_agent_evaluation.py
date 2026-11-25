from typing import Any

from app.agent.evaluation import judge, render, summarize

CONTEXT = [
    {"type": "product", "id": "p1", "sku": "PN-001", "name": "Букет из 15 розовых пионов"},
    {"type": "kb", "id": "k1", "source": "delivery"},
]


def turn(**extra: Any) -> dict[str, Any]:
    return {
        "reply": "Букет из 15 розовых пионов стоит 32 000 ₸",
        "intent": "product",
        "lang": "ru",
        "human_mode": False,
        "context": CONTEXT,
        "trace": [{"node": "guard_out", "ok": True}, {"node": "meter", "unanswered": False}],
        **extra,
    }


def test_judge_passes_matching_turn() -> None:
    expect = {
        "intent": "product",
        "skus_any": ["PN-001"],
        "kb_any": ["delivery"],
        "reply_has": ["32 000"],
        "handoff": False,
        "unanswered": False,
    }
    checks = judge(expect, "ru", turn())
    assert checks == dict.fromkeys(
        ("intent", "lang", "products", "kb", "reply", "handoff", "unanswered", "clean"), True
    )


def test_judge_catches_failures() -> None:
    trace = [
        {"node": "guard_out", "ok": False},
        {"node": "guard_out", "ok": True},
        {"node": "meter", "unanswered": True},
    ]
    checks = judge(
        {"intent": "policy", "skus_any": ["RS-101"], "unanswered": False},
        "kk",
        turn(trace=trace),
    )
    assert checks == {
        "intent": False,
        "lang": False,
        "products": False,
        "unanswered": False,
        "clean": False,
    }
    assert "lang" not in judge({}, "mixed", turn())


def test_summary_and_report() -> None:
    rows = [
        {"id": 1, "lang": "ru", "turns": ["a"], "checks": {"intent": True, "clean": True}},
        {
            "id": 2,
            "lang": "kk",
            "turns": ["b"],
            "checks": {"intent": False, "clean": True},
            "reply": "ответ",
            "fallback": True,
            "latency_ms": [1000.0, 3000.0],
        },
    ]
    summary = summarize(rows)
    assert summary["passed"] == 0.5
    assert summary["checks"]["intent"] == {"n": 2, "rate": 0.5}
    assert summary["fallbacks"] == 0.5
    assert summary["latency_p50"] == 2000.0
    report = render("2026-11-26", {"ответ": "m"}, summary, rows)
    assert "пройдено целиком: 50%" in report
    assert "- 2. [kk] «b» — намерение." in report


def test_translated_name_counts_by_price() -> None:
    context = [
        {
            "type": "product",
            "id": "t",
            "sku": "TL-202",
            "name": "Букет из 51 тюльпана",
            "price": 23000,
        }
    ]
    kk = turn(reply="51 қызғалдақтан тұратын шоқ 23 000 ₸ тұрады.", context=context, lang="kk")
    assert judge({"skus_any": ["TL-202"]}, "kk", kk)["products"]
    other = turn(reply="Шоқ 25 000 ₸ тұрады.", context=context, lang="kk")
    assert not judge({"skus_any": ["TL-202"]}, "kk", other)["products"]
