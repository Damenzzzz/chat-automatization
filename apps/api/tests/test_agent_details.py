import uuid

from app.agent.guard import check_reply
from app.agent.prompt import ShopProfile, context_block
from app.agent.tools import product_details, product_item
from app.search.types import ProductHit

PROFILE = ShopProfile(name="Цветы")


def hit(**extra: object) -> ProductHit:
    return ProductHit(
        id=uuid.uuid4(),
        sku="PN-001",
        name="Букет из 15 розовых пионов",
        category="Пионы",
        price=32000,
        stock=6,
        reasons=("fts",),
        ranks={"fts": 1},
        rrf=0.1,
        **extra,  # type: ignore[arg-type]
    )


def test_details_reach_the_prompt() -> None:
    item = product_item(
        hit(
            description="Пионы сорта Sarah Bernhardt,\n высота 50 см.",
            attributes={"цвет": "розовый", "упаковка": "крафт", "пусто": ""},
        )
    )
    assert item["attributes"] == "цвет: розовый; упаковка: крафт"
    assert item["description"] == "Пионы сорта Sarah Bernhardt, высота 50 см."
    block = context_block(lang="ru", intent="product", slots=None, context=[item])
    assert (
        "- PN-001 «Букет из 15 розовых пионов» — 32 000 ₸, в наличии 6 шт."
        " Характеристики: цвет: розовый; упаковка: крафт."
        " Описание: Пионы сорта Sarah Bernhardt, высота 50 см." in block
    )


def test_details_are_clipped_and_optional() -> None:
    assert product_details(None, None) == {}
    long = product_details("слово " * 200, {"a": "b" * 400})
    assert len(long["description"]) == 300
    assert long["description"].endswith("…")
    assert len(long["attributes"]) == 300
    plain = product_item(hit())
    assert "description" not in plain
    assert "Описание" not in context_block(lang="ru", intent=None, slots=None, context=[plain])


def test_amount_from_description_is_allowed() -> None:
    item = product_item(hit(description="Открытка в подарок, упаковка в коробку +3 000 ₸"))
    assert check_reply("Упаковка в коробку стоит 3 000 ₸.", [item], PROFILE).ok
    assert not check_reply("Упаковка в коробку стоит 4 000 ₸.", [item], PROFILE).ok
