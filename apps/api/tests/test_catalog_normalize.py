from typing import Any

import pytest

from app.catalog.normalize import (
    NormalizeError,
    clean_sku,
    clean_text,
    content_hash,
    name_hash,
    parse_images,
    parse_price,
    parse_stock,
    sku_norm,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("22 900 тг", 22900),
        ("22 900 ₸", 22900),
        ("52 000,00 ₸", 52000),
        ("8 000.50", 8001),
        ("1,500", 1500),
        ("1.500", 1500),
        ("12,5", 13),
        ("1 234 567,89 тенге", 1234568),
        ("24000", 24000),
        (24000, 24000),
        (24000.4, 24000),
        ("", None),
        (None, None),
    ],
)
def test_parse_price(raw: Any, expected: int | None) -> None:
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["договорная", "-5", "abc 100"])
def test_parse_price_errors(raw: str) -> None:
    with pytest.raises(NormalizeError):
        parse_price(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("6", 6), ("3 шт", 3), (12, 12), (5.0, 5), ("нет", 0), ("есть", None), ("", None)],
)
def test_parse_stock(raw: Any, expected: int | None) -> None:
    assert parse_stock(raw) == expected


@pytest.mark.parametrize("raw", ["-2", "много"])
def test_parse_stock_errors(raw: str) -> None:
    with pytest.raises(NormalizeError):
        parse_stock(raw)


def test_text_helpers() -> None:
    assert clean_text("<p>Розовые <b>пионы</b>&nbsp;&amp; зелень</p>") == "Розовые пионы & зелень"
    assert clean_text("   ") is None
    assert clean_sku(12345.0) == "12345"
    assert sku_norm(clean_sku(" pn -002 ")) == "PN002"
    assert sku_norm("ab-12 3c") == "AB123C"
    assert parse_images("https://a/1.jpg; https://a/2.jpg,https://a/3.jpg") == [
        "https://a/1.jpg",
        "https://a/2.jpg",
        "https://a/3.jpg",
    ]
    assert name_hash("Букет  Пионов") == name_hash("букет пионов")


def test_content_hash_ignores_key_order() -> None:
    a = content_hash("Пион", None, "Цветы", {"цвет": "розовый", "размер": "M"})
    b = content_hash("Пион", None, "Цветы", {"размер": "M", "цвет": "розовый"})
    assert a == b
    assert a != content_hash("Пион", "новое описание", "Цветы", {"цвет": "розовый", "размер": "M"})
