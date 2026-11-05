import uuid
from datetime import UTC, datetime

from app.channels.outgoing import (
    button_text,
    clip,
    mentioned_products,
    order_button,
    product_card,
    split_text,
)
from app.channels.types import IncomingMessage, Media


def test_incoming_message_survives_json_roundtrip() -> None:
    message = IncomingMessage(
        channel_id=uuid.uuid4(),
        external_id="1",
        customer_external_id="77",
        text="привет",
        media=[Media(file_id="abc", mime_type="audio/ogg")],
        received_at=datetime(2026, 11, 5, tzinfo=UTC),
    )
    assert IncomingMessage.model_validate_json(message.model_dump_json()) == message


def test_order_button_roundtrip_keeps_language() -> None:
    button = order_button("PN-004", "kk")
    assert button is not None
    assert button.title == "Тапсырыс беру"
    assert button_text(button.payload) == "PN-004 тапсырыс бергім келеді"
    ru = order_button("PN-004", "mixed")
    assert ru is not None and button_text(ru.payload) == "Хочу заказать PN-004"


def test_order_button_skips_payload_over_platform_limit() -> None:
    assert order_button("S" * 60, "ru") is None
    assert order_button(None, "ru") is None


def test_button_text_ignores_unknown_payload() -> None:
    assert button_text("delete:everything") is None


def test_only_mentioned_products_become_cards() -> None:
    context = [
        {"type": "product", "id": "1", "name": "Белые пионы", "sku": "PN-1"},
        {"type": "product", "id": "2", "name": "Красные розы", "sku": "RS-2"},
        {"type": "product", "id": "3", "name": "Тюльпаны", "sku": "TL-3"},
        {"type": "kb", "id": "4", "title": "Белые пионы"},
    ]
    reply = "Советую белые пионы, а артикул TL-3 тоже хорош."
    assert mentioned_products(reply, context) == ["1", "3"]


def test_card_caption_has_db_price_and_https_image_only() -> None:
    card = product_card(
        name="Белые пионы",
        sku="PN-1",
        price=52000,
        images=["http://shop.kz/a.jpg", "https://shop.kz/b.jpg"],
        lang="ru",
    )
    assert card.caption == "Белые пионы\n52 000 ₸"
    assert card.image_url == "https://shop.kz/b.jpg"
    assert product_card(name="X", sku=None, price=None, images=[], lang="ru").caption == "X"


def test_split_text_respects_limit_and_keeps_words() -> None:
    text = "слово " * 100
    chunks = split_text(text, 50)
    assert all(len(c) <= 50 for c in chunks)
    assert " ".join(chunks).split() == text.split()
    assert split_text("a" * 120, 50) == ["a" * 50, "a" * 50, "a" * 20]
    assert split_text("   ", 50) == []


def test_clip_marks_truncation() -> None:
    assert clip("короткий", 20) == "короткий"
    assert clip("x" * 30, 10) == "x" * 9 + "…"
