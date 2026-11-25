from typing import Any

import pytest

from app.agent.guard import check_reply, promises_manager
from app.agent.prompt import ShopProfile

PROFILE = ShopProfile(name="Цветы", rules={"contacts": "Сайт pion.kz, Instagram @pion"})
CONTEXT: list[dict[str, Any]] = [
    {
        "type": "product",
        "id": "1",
        "sku": "PN-001",
        "sku_norm": "PN001",
        "name": "Букет из 15 розовых пионов",
        "price": 32000,
        "stock": 6,
    },
    {
        "type": "kb",
        "id": "2",
        "source": "address",
        "title": "Адрес",
        "text": "Жибек Жолы 115. Телефон и WhatsApp: +7 700 000 00 00. Карта: https://2gis.kz/almaty/firm/1",
    },
]


def errors(reply: str, customer: str = "", lang: str | None = "ru") -> list[str]:
    return check_reply(reply, CONTEXT, PROFILE, customer, lang=lang).errors


@pytest.mark.parametrize(
    "reply",
    [
        "Звоните: 8 (700) 000-00-00.",
        "Наш WhatsApp +7 700 000 00 00",
        "Мы на карте: https://2gis.kz/almaty/firm/1",
        "Каталог на сайте pion.kz",
        "Оплатить можно через Kaspi.kz",
        "В наличии 6 шт., букет из 15 пионов.",
        "Осталось 6 штук.",
        "Перезвоню на ваш номер 8 701 555 44 33.",
    ],
)
def test_facts_from_data_pass(reply: str) -> None:
    assert errors(reply, customer="мой номер 8 701 555 44 33") == []


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ("Звоните: +7 777 123 45 67", "телефона «+7 777 123 45 67» нет"),
        ("Подробнее на www.pion-flowers.kz", "ссылки «www.pion-flowers.kz» нет"),
        ("Оплата по ссылке https://pay.example.com/x", "ссылки «https://pay.example.com/x» нет"),
        ("В наличии 12 шт.", "остаток «В наличии 12 шт» не совпадает"),
        ("3 штуки осталось", "остаток «3 штуки осталось» не совпадает"),
    ],
)
def test_invented_facts_are_caught(reply: str, error: str) -> None:
    found = errors(reply)
    assert any(e.startswith(error) for e in found), found


def test_kazakh_customer_needs_kazakh_reply() -> None:
    russian = "Здравствуйте, букет из пионов стоит 32 000 ₸, привезём сегодня вечером."
    kazakh = "Сәлеметсіз бе! Пиондар шоғы 32 000 ₸ тұрады, бүгін кешке жеткіземіз."
    assert errors(russian, lang="kk") == ["покупатель пишет по-казахски, а ответ на русском"]
    assert errors(kazakh, lang="kk") == []
    assert errors("Да, 32 000 ₸.", lang="kk") == []
    assert errors(russian, lang="mixed") == []
    only_ru = ShopProfile(name="Цветы", languages=("ru",))
    assert check_reply(russian, CONTEXT, only_ru, lang="kk").ok


@pytest.mark.parametrize(
    "reply",
    [
        "Свежие цветы возврату и обмену не подлежат.",
        "Сейчас действует скидка 10% на всё.",
        "Дарим гарантию свежести 7 дней.",
        "Можно оформить рассрочку.",
        "Гүлдерді қайтаруға болмайды.",
    ],
)
def test_invented_shop_terms_are_caught(reply: str) -> None:
    assert any(e.startswith("в данных магазина нет условий про") for e in errors(reply))


@pytest.mark.parametrize(
    "reply",
    [
        "Про возврат уточню у менеджера и вернусь с ответом.",
        "Қайтару туралы менеджерден нақтылап беремін.",
        "Фото букета пришлём перед выездом курьера.",
    ],
)
def test_deferred_or_unrelated_terms_pass(reply: str) -> None:
    assert errors(reply) == []


def test_terms_from_knowledge_base_pass() -> None:
    kb = {"type": "kb", "id": "r", "source": "returns", "text": "Возврат возможен в течение часа"}
    reply = "Возврат возможен в течение часа после доставки."
    assert check_reply(reply, [*CONTEXT, kb], PROFILE, lang="ru").ok


@pytest.mark.parametrize(
    ("reply", "promised"),
    [
        ("Уточню этот вопрос у менеджера и вернусь с ответом.", True),
        ("Менеджер скоро подключится к чату.", True),
        ("Передала ваш вопрос менеджеру.", True),
        ("Менеджер сізге жақын арада жауап береді.", True),
        ("Бұл сұрақты менеджерден нақтылап, жауап беремін.", True),
        ("Пионы стоят 32 000 ₸, оформить заказ?", False),
        ("Если захотите, позову менеджера.", False),
    ],
)
def test_manager_promise(reply: str, promised: bool) -> None:
    assert promises_manager(reply) is promised
