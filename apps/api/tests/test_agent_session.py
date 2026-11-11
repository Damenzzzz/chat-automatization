from datetime import UTC, datetime

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from app.agent.prompt import context_block, local_time
from app.agent.respond import dialog_length
from app.agent.session import SESSION_GAP, new_session
from app.channels.staff import staff_text


def human(at: float) -> HumanMessage:
    return HumanMessage("вопрос", additional_kwargs={"at": at})


def test_dialog_length_counts_only_current_session() -> None:
    old: list[AnyMessage] = [m for i in range(10) for m in (human(i), AIMessage("ответ"))]
    fresh: list[AnyMessage] = [
        human(SESSION_GAP * 2),
        AIMessage("ответ"),
        human(SESSION_GAP * 2 + 10),
    ]

    assert dialog_length(old) == 20
    assert dialog_length([*old, *fresh]) == 3


def test_messages_without_time_stay_in_session() -> None:
    assert dialog_length([HumanMessage("вопрос"), AIMessage("ответ"), human(5)]) == 3


def test_new_session_starts_after_long_pause() -> None:
    assert new_session([human(0), AIMessage("ответ"), human(SESSION_GAP + 1)])
    assert not new_session([human(0), AIMessage("ответ"), human(10)])
    assert not new_session([human(0)])


def test_staff_text_links_to_dialog() -> None:
    text = staff_text("handoff", {"conversation_id": "c1", "reason": "оптовый заказ"})
    assert text is not None
    assert "оптовый заказ" in text
    assert text.endswith("/dialogs?id=c1")
    assert staff_text("unknown", {}) is None


def test_bot_knows_shop_local_time() -> None:
    moment = datetime(2026, 11, 10, 18, 41, tzinfo=UTC)
    assert local_time(moment) == "вторник, 10.11.2026 23:41"
    assert "Сейчас " in context_block(lang="ru", intent=None, slots=None, context=[])
