from langchain_core.messages import AnyMessage, HumanMessage

SESSION_GAP = 6 * 3600


def sent_at(message: AnyMessage) -> float | None:
    value = message.additional_kwargs.get("at")
    return float(value) if isinstance(value, int | float) else None


def session_start(messages: list[AnyMessage]) -> int:
    start, later = len(messages), None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, HumanMessage):
            continue
        at = sent_at(message)
        if at is not None and later is not None and later - at > SESSION_GAP:
            break
        start = index
        later = at if at is not None else later
    return start


def new_session(messages: list[AnyMessage]) -> bool:
    humans = [m for m in messages if isinstance(m, HumanMessage)]
    return len(humans) > 1 and session_start(messages) == messages.index(humans[-1])
