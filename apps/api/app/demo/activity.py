import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Conversation,
    Customer,
    Lead,
    LedgerEntry,
    Message,
    Product,
    SearchLog,
    Unanswered,
)

DEMO_PREFIX = "demo:"
STALE_AFTER = timedelta(days=2)


@dataclass
class Say:
    role: str
    text: str
    skus: list[str] = field(default_factory=list)
    intent: str = "product"
    query: str | None = None


@dataclass
class Script:
    name: str
    channel: str
    lang: str
    hours_ago: float
    turns: list[Say]
    mode: str = "bot"
    lead: dict[str, Any] | None = None
    unanswered: str | None = None
    phone: str | None = None


SCRIPTS = [
    Script(
        "Айгерим",
        "whatsapp",
        "ru",
        0.4,
        [
            Say("customer", "Здравствуйте! Есть розовые пионы? Нужно на завтра к 10 утра"),
            Say(
                "bot",
                "Здравствуйте! Да, есть «Букет из 15 розовых пионов» — 32 000 ₸, в наличии 6 шт. "
                "Доставим завтра к 10:00 по Алматы. Оформить?",
                ["PN-001"],
                query="розовые пионы",
            ),
            Say("customer", "Да, оформляйте. Абая 150, кв 12, Айгерим 87015550101"),
            Say(
                "bot",
                "Записала заказ: «Букет из 15 розовых пионов», 32 000 ₸, завтра к 10:00, "
                "Абая 150, кв. 12. Менеджер позвонит для подтверждения оплаты.",
                ["PN-001"],
                intent="order",
            ),
        ],
        lead={
            "sku": "PN-001",
            "status": "new",
            "address": "Абая 150, кв. 12",
            "delivery_note": "завтра к 10:00",
        },
        phone="+77015550101",
    ),
    Script(
        "Нурлан",
        "telegram",
        "kk",
        1.2,
        [
            Say("customer", "Сәлеметсіз бе! 51 раушан гүлі қанша тұрады?"),
            Say(
                "bot",
                "Сәлеметсіз бе! «Букет из 51 розы» — 48 000 ₸, қоймада 5 дана бар. "
                "Алматы бойынша жеткізу 2 сағат ішінде. Тапсырыс береміз бе?",
                ["RS-102"],
                query="51 раушан",
            ),
            Say("customer", "Kaspi Red арқылы бөліп төлеуге бола ма?"),
        ],
        mode="human",
        unanswered="Kaspi Red арқылы бөліп төлеуге бола ма?",
    ),
    Script(
        "Динара",
        "instagram",
        "mixed",
        3.0,
        [
            Say("customer", "Салем! Маған тюльпан керек, бюджет 15 мыңға дейін"),
            Say(
                "bot",
                "Сәлем! До 15 000 ₸ подойдёт «Букет из 25 тюльпанов» — 12 500 ₸, "
                "жёлтые, красные и розовые. Есть 20 шт, привезём сегодня.",
                ["TL-201"],
                query="тюльпаны до 15000",
            ),
            Say("customer", "Керемет, рахмет! Кешке қарай жеткізіңізші"),
            Say(
                "bot",
                "Жақсы! Тапсырысты менеджерге бердім, ол сізге 10 минут ішінде жазады.",
                ["TL-201"],
                intent="order",
            ),
        ],
        lead={"sku": "TL-201", "status": "in_progress", "delivery_note": "сегодня вечером"},
        phone="+77075550202",
    ),
    Script(
        "Ержан",
        "web",
        "ru",
        5.5,
        [
            Say("customer", "Хочу сделать индивидуальный заказ на свадьбу, 40 букетов"),
            Say(
                "bot",
                "Поздравляю! Большие свадебные заказы готовит флорист лично — передаю диалог "
                "менеджеру, он ответит в течение 15 минут.",
                intent="handoff",
            ),
            Say("manager", "Ержан, добрый день! Меня зовут Асель, давайте обсудим палитру."),
            Say("customer", "Белый и пудровый, бюджет около 600 тысяч"),
        ],
        mode="human",
    ),
    Script(
        "Мадина",
        "whatsapp",
        "ru",
        8.0,
        [
            Say("customer", "Добрый вечер, что есть в шляпной коробке?"),
            Say(
                "bot",
                "Добрый вечер! «Пионы в шляпной коробке» — 45 000 ₸: розовые пионы "
                "с эвкалиптом в бархатной коробке, осталось 2 шт. "
                "Ещё есть «Розы в коробке «Сердце»» — 36 000 ₸.",
                ["PN-005", "RS-106"],
                query="шляпная коробка",
            ),
            Say("customer", "Возьму пионы, доставка на Достык 5 к 19:00"),
            Say(
                "bot",
                "Отлично! Записала «Пионы в шляпной коробке» на 19:00, Достык 5. "
                "Менеджер пришлёт ссылку на оплату Kaspi.",
                ["PN-005"],
                intent="order",
            ),
        ],
        lead={"sku": "PN-005", "status": "done", "address": "Достык 5"},
        phone="+77775550303",
    ),
    Script(
        "Әсем",
        "telegram",
        "kk",
        20.0,
        [
            Say("customer", "Анама гүл алғым келеді, не ұсынасыз?"),
            Say(
                "bot",
                "Анаңызға «Букет «Нежность»» — 21 000 ₸ немесе «Авторский букет «Алматы»» — "
                "28 000 ₸ жарасады. Екеуі де бүгін бар.",
                ["MX-302", "MX-301"],
                query="анама гүл",
            ),
            Say("customer", "Нежность алайын, ашықхат қоса аласыздар ма?"),
            Say(
                "bot",
                "Әрине! «Открытка ручной работы» — 1 500 ₸, мәтінін өзіңіз жазасыз. "
                "Барлығы 22 500 ₸.",
                ["GF-601"],
                intent="order",
            ),
        ],
        lead={"sku": "MX-302", "extra": "GF-601", "status": "done"},
        phone="+77015550404",
    ),
    Script(
        "Тимур",
        "web",
        "ru",
        27.0,
        [
            Say("customer", "Есть ли у вас гортензии?"),
            Say(
                "bot",
                "Да, «Монобукет из гортензии» — 22 000 ₸, три крупные голубые гортензии. "
                "В наличии 3 шт.",
                ["MX-305"],
                query="гортензии",
            ),
        ],
    ),
    Script(
        "Камила",
        "instagram",
        "ru",
        31.0,
        [
            Say("customer", "Вы доставляете в Каскелен? Сколько стоит?"),
            Say(
                "bot",
                "Точной цены доставки в Каскелен у меня нет — уточню у менеджера и вернусь "
                "с ответом.",
                intent="policy",
            ),
        ],
        unanswered="Вы доставляете в Каскелен? Сколько стоит?",
    ),
    Script(
        "Бауыржан",
        "whatsapp",
        "kk",
        44.0,
        [
            Say("customer", "101 раушан бар ма? Ертең туған күн"),
            Say(
                "bot",
                "Иә, «Букет из 101 розы» бар — 89 000 ₸, қоймада 2 дана. "
                "Ертеңге жеткізуді жазайын ба?",
                ["RS-103"],
                query="101 раушан",
            ),
            Say("customer", "Иә, жазыңыз. Сәтбаев 30"),
            Say(
                "bot",
                "Тапсырыс қабылданды: «Букет из 101 розы», 89 000 ₸, ертең, Сәтбаев 30.",
                ["RS-103"],
                intent="order",
            ),
        ],
        lead={"sku": "RS-103", "status": "in_progress", "address": "Сәтбаев 30"},
        phone="+77055550505",
    ),
    Script(
        "Светлана",
        "telegram",
        "ru",
        70.0,
        [
            Say("customer", "Можно ли оплатить при получении наличными?"),
            Say(
                "bot",
                "Об оплате при получении в магазине пока нет правила — передам вопрос менеджеру.",
                intent="policy",
            ),
        ],
        unanswered="Можно ли оплатить при получении наличными?",
    ),
    Script(
        "Арман",
        "web",
        "mixed",
        96.0,
        [
            Say("customer", "Привет, керек букет невесты, ақ түсті"),
            Say(
                "bot",
                "Сәлем! «Букет невесты» — 35 000 ₸: белые пионовидные розы и эустома. "
                "К нему «Бутоньерка для жениха» — 6 000 ₸.",
                ["MX-306", "MX-307"],
                query="букет невесты белый",
            ),
        ],
        lead={"sku": "MX-306", "extra": "MX-307", "status": "cancelled"},
        phone="+77085550606",
    ),
]

QUICK = [
    ("ru", "Сколько стоят ромашки?", "CH-401", "ромашки"),
    ("ru", "Есть подсолнухи?", "MX-303", "подсолнухи"),
    ("kk", "Шарлар бар ма?", "GF-602", "шарлар"),
    ("ru", "Нужен букет из красных роз", "RS-101", "красные розы"),
    ("kk", "Хризантема қанша?", "CH-402", "хризантема"),
    ("ru", "Что есть с макарунами?", "CP-503", "макаруны"),
    ("mixed", "Корзина цветов бар ма?", "CP-502", "корзина цветов"),
    ("ru", "Коралловые пионы ещё есть?", "PN-004", "коралловые пионы"),
    ("kk", "Кустовые раушан керек", "RS-104", "кустовые розы"),
    ("ru", "Подарочная коробка недорого", "CP-501", "коробка недорого"),
]

CHANNELS = ["whatsapp", "whatsapp", "telegram", "instagram", "web"]
NAMES = [
    "Алия",
    "Данияр",
    "Жанна",
    "Руслан",
    "Гүлнар",
    "Ольга",
    "Ерлан",
    "Сабина",
    "Максат",
    "Индира",
]


def _money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₸"


def _quick_reply(lang: str, product: Product) -> str:
    stock = f"в наличии {product.stock} шт." if product.stock else "уточню наличие у флориста."
    if lang == "kk":
        return f"«{product.name}» — {_money(product.price or 0)}. Бүгін жеткізе аламыз."
    return f"«{product.name}» — {_money(product.price or 0)}, {stock} Доставим сегодня по Алматы."


def _bot_trace(say: Say, lang: str, products: list[Product], charge: int) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [{"node": "understand", "intent": say.intent, "lang": lang}]
    if say.query:
        steps.append({"node": "retrieve", "query": say.query, "found": [p.name for p in products]})
    if say.intent == "handoff":
        steps.append({"node": "handoff"})
    steps.append({"node": "guard_out", "ok": True, "amounts": [p.price for p in products]})
    steps.append({"node": "send", "delivered": True, "products": [str(p.id) for p in products]})
    steps.append({"node": "meter", "charge": {"charged_kzt": charge}})
    return {"lang": lang, "intent": say.intent, "steps": steps}


async def demo_activity_fresh(session: AsyncSession) -> bool:
    latest = await session.scalar(
        select(func.max(Conversation.last_message_at))
        .join(Customer, Customer.id == Conversation.customer_id)
        .where(Customer.external_id.startswith(DEMO_PREFIX))
    )
    return latest is not None and datetime.now(UTC) - latest < STALE_AFTER


async def clear_demo_activity(session: AsyncSession) -> None:
    await session.execute(delete(Customer).where(Customer.external_id.startswith(DEMO_PREFIX)))


async def seed_activity(
    session: AsyncSession, tenant_id: uuid.UUID, *, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    rng = random.Random(42)  # noqa: S311
    settings = get_settings()
    products = {p.sku: p for p in await session.scalars(select(Product)) if p.sku}

    scripts = list(SCRIPTS)
    for i in range(56):
        lang, question, sku, query = QUICK[i % len(QUICK)]
        hours = 6 + (i * 157 % 330) + rng.random()
        scripts.append(
            Script(
                NAMES[i % len(NAMES)],
                CHANNELS[i % len(CHANNELS)],
                lang,
                hours,
                [Say("customer", question), Say("bot", "", [sku], query=query)],
            )
        )

    for index, script in enumerate(scripts):
        started = now - timedelta(hours=script.hours_ago)
        customer = Customer(
            tenant_id=tenant_id,
            channel=script.channel,
            external_id=f"{DEMO_PREFIX}{index}",
            name=script.name,
            phone=script.phone,
            lang=script.lang,
        )
        session.add(customer)
        await session.flush()
        conversation = Conversation(
            tenant_id=tenant_id,
            customer_id=customer.id,
            mode=script.mode,
            created_at=started,
        )
        session.add(conversation)
        await session.flush()

        at = started
        for say in script.turns:
            at += timedelta(seconds=rng.randint(20, 150))
            items = [products[s] for s in say.skus if s in products]
            text = say.text or _quick_reply(script.lang, items[0])
            message = Message(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                role=say.role,
                content=text,
                created_at=at,
            )
            if say.role == "bot":
                charge = rng.randint(4, 9)
                message.model = settings.llm_model_reply
                message.tokens_in = rng.randint(1800, 3200)
                message.tokens_out = rng.randint(60, 160)
                message.latency_ms = rng.randint(1100, 2600)
                message.cost_usd = Decimal("0.0006")
                message.trace = _bot_trace(say, script.lang, items, charge)
                session.add(message)
                await session.flush()
                session.add(
                    LedgerEntry(
                        tenant_id=tenant_id,
                        type="charge",
                        amount_kzt=-charge,
                        cost_usd=message.cost_usd,
                        model=message.model,
                        tokens_in=message.tokens_in,
                        tokens_out=message.tokens_out,
                        comment="демо",
                        created_at=at,
                    )
                )
                if say.query:
                    session.add(
                        SearchLog(
                            tenant_id=tenant_id,
                            conversation_id=conversation.id,
                            query=say.query,
                            lang=script.lang,
                            results=[str(p.id) for p in items],
                            result_count=len(items),
                            has_in_stock=any((p.stock or 0) > 0 for p in items),
                            latency_ms=rng.randint(180, 420),
                            created_at=at,
                        )
                    )
            else:
                session.add(message)
        conversation.last_message_at = at

        if script.lead:
            lead = script.lead
            items = [products[s] for s in (lead["sku"], lead.get("extra")) if s in products]
            session.add(
                Lead(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    items=[
                        {
                            "product_id": str(p.id),
                            "sku": p.sku,
                            "name": p.name,
                            "price": p.price,
                            "qty": 1,
                        }
                        for p in items
                    ],
                    total_kzt=sum(p.price or 0 for p in items),
                    contact_name=script.name,
                    contact_phone=script.phone,
                    address=lead.get("address"),
                    delivery_note=lead.get("delivery_note"),
                    status=lead["status"],
                    created_at=at,
                )
            )
        if script.unanswered:
            session.add(
                Unanswered(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    question=script.unanswered,
                    created_at=at,
                )
            )
    await session.flush()
    return len(scripts)
