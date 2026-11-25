import pytest
from pydantic import ValidationError

from app.agent.args import CreateLeadArgs, SearchProductsArgs, parse_count, parse_money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12к", 12000),
        ("12 000 ₸", 12000),
        ("12 000", 12000),
        ("15 тыс.", 15000),
        ("2,5k", 2500),
        ("30 мың", 30000),
        ("45000 тг", 45000),
        (12000.4, 12000),
        (9000, 9000),
        (None, None),
        ("дёшево", "дёшево"),
    ],
)
def test_parse_money(raw: object, expected: object) -> None:
    assert parse_money(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [("2 шт", 2), (" 3", 3), (4.0, 4), ("x", "x")])
def test_parse_count(raw: object, expected: object) -> None:
    assert parse_count(raw) == expected


def test_search_args_reject_garbage_budget() -> None:
    with pytest.raises(ValidationError):
        SearchProductsArgs.model_validate({"query": "пионы", "budget_max": "дёшево"})
    with pytest.raises(ValidationError):
        SearchProductsArgs.model_validate({"query": "   "})


def test_lead_items_are_normalized() -> None:
    args = CreateLeadArgs.model_validate(
        {
            "items": [{"sku": " PN-001 ", "qty": "5000"}, {"sku": "GF-601", "qty": None}],
            "contact_phone": "+77011234567",
        }
    )
    assert [(i.sku, i.qty) for i in args.items] == [("PN-001", 999), ("GF-601", 1)]
    with pytest.raises(ValidationError):
        CreateLeadArgs.model_validate(
            {"items": [{"sku": "PN-001", "qty": 0}], "contact_phone": "+77011234567"}
        )
