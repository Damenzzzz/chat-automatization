import pytest

from app.agent.understand import guess_budget, guess_intent, heuristic


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Позовите менеджера, пожалуйста", "human"),
        ("менеджерге қосыңызшы", "human"),
        ("Хочу оформить заказ на пионы", "order"),
        ("Тапсырыс бергім келеді", "order"),
        ("Сколько стоит доставка в Каскелен?", "policy"),
        ("Kaspi арқылы төлеуге бола ма", "policy"),
        ("До скольки вы работаете?", "policy"),
        ("Здравствуйте!", "smalltalk"),
        ("рахмет", "smalltalk"),
        ("Спасибо, а пионы есть?", "product"),
        ("Есть розовые пионы?", "product"),
        ("қызыл раушан бар ма?", "product"),
    ],
)
def test_guess_intent(text: str, intent: str) -> None:
    assert guess_intent(text) == intent


@pytest.mark.parametrize(
    ("text", "budget"),
    [
        ("пионы до 30к", 30000),
        ("букет до 25 000 тг", 25000),
        ("что-нибудь до 15 тыс.", 15000),
        ("не дороже 40000", 40000),
        ("20 мыңға дейін гүл", 20000),
        ("30000 теңгеге дейін", 30000),
        ("букет из 15 пионов", None),
        ("доставка до 19:00", None),
    ],
)
def test_guess_budget(text: str, budget: int | None) -> None:
    assert guess_budget(text) == budget


def test_heuristic_fills_slots() -> None:
    result = heuristic("PN-001 до 35к есть?")
    assert result.intent == "product"
    assert result.slots.sku == "PN001"
    assert result.slots.budget_max == 35000
