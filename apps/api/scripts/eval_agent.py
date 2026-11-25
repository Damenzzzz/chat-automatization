"""Сценарный замер ответов бота на демо-магазине: тот же граф в режиме песочницы."""

import argparse
import asyncio
import datetime as dt
import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.agent.checkpoint import get_checkpointer
from app.agent.evaluation import judge, render, summarize
from app.agent.nodes import AgentDeps
from app.agent.runtime import Agent
from app.agent.sandbox import sandbox_conversation
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm import get_llm
from app.mlclient import get_ml_client
from app.seed import DEMO_TENANT_ID
from scripts.eval_search import ROOT, load_queries, ml_backends


class SilentQueue:
    async def enqueue(self, *args: Any, **kwargs: Any) -> None:
        return None


async def run_scenario(agent: Agent, item: dict[str, Any], tag: str) -> dict[str, Any]:
    conversation_id = await sandbox_conversation(DEMO_TENANT_ID, f"eval-{tag}-{item['id']}")
    latency: list[float] = []
    result = None
    for text in item["turns"]:
        started = time.perf_counter()
        result = await agent.run(
            tenant_id=DEMO_TENANT_ID, conversation_id=conversation_id, text=text, sandbox=True
        )
        latency.append((time.perf_counter() - started) * 1000)
    if result is None:
        raise SystemExit(f"в сценарии {item['id']} нет сообщений")
    state = await agent.graph.aget_state({"configurable": {"thread_id": str(conversation_id)}})
    turn = {
        "reply": result.reply,
        "intent": result.intent,
        "lang": result.lang,
        "human_mode": result.human_mode,
        "context": state.values.get("context", []),
        "trace": result.trace,
    }
    return {
        **item,
        "reply": result.reply,
        "intent": result.intent,
        "checks": judge(item.get("expect", {}), item["lang"], turn),
        "fallback": any(t.get("node") == "fallback" for t in result.trace),
        "latency_ms": latency,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--only", type=int, nargs="*", help="номера сценариев")
    args = parser.parse_args()
    configure_logging("WARNING")

    llm = get_llm()
    if llm is None:
        raise SystemExit("нужен GEMINI_API_KEY: замер идёт на настоящей модели")
    backends = await ml_backends()
    agent = Agent(
        AgentDeps(llm=llm, ml=get_ml_client(), queue=SilentQueue()),
        await get_checkpointer(),
    )
    scenarios = load_queries(ROOT / "eval" / "agent_scenarios.jsonl")
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in set(args.only)]
    tag = uuid.uuid4().hex[:8]
    rows = []
    for i, item in enumerate(scenarios, start=1):
        rows.append(await run_scenario(agent, item, tag))
        print(f"\r{i}/{len(scenarios)}", end="", flush=True)
    print()

    settings = get_settings()
    models = {
        "разбор": settings.llm_model_router,
        "ответ": settings.llm_model_reply,
        "сложный диалог": settings.llm_model_complex,
        "эмбеддинги": backends["embedder"],
        "реранкер": backends["reranker"],
    }
    summary = summarize(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.date}-agent.json").write_text(
        json.dumps(
            {"models": models, "summary": summary, "rows": rows},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    report = render(args.date, models, summary, rows)
    (args.out / f"{args.date}-agent.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
