from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.prompt import ShopProfile, context_block, load_profile, money, system_prompt
from app.db.session import tenant_session
from tests.agent_helpers import make_conversation

PROFILE = ShopProfile(
    name="Цветы Пион",
    niche="цветы",
    city="Алматы",
    tone="Тёплый и вежливый",
    greeting="Здравствуйте! Это «Цветы Пион».",
    rules={"address_form": "ты", "delivery": "Доставка по Алматы 2 000 ₸"},
    languages=("ru", "kk"),
)


def test_system_prompt_uses_profile() -> None:
    prompt = system_prompt(PROFILE)
    assert prompt.startswith("Ты — консультант магазина «Цветы Пион» (цветы, Алматы).")
    assert "Тон: Тёплый и вежливый." in prompt
    assert "на «ты»" in prompt
    assert "Здравствуйте! Это «Цветы Пион»." in prompt
    assert "- Доставка по Алматы 2 000 ₸" in prompt
    assert "Языки магазина: русский, казахский." in prompt
    assert "посторонние темы вежливо откажи" in prompt


def test_system_prompt_is_stable() -> None:
    assert system_prompt(PROFILE) == system_prompt(PROFILE)


def test_context_block_lists_language_and_prices() -> None:
    block = context_block(
        lang="kk",
        intent="product",
        slots={"budget_max": 30000, "sku": None},
        context=[
            {"type": "product", "sku": "PN-001", "name": "Пионы", "price": 32000, "stock": 6},
            {"type": "product", "sku": None, "name": "Тюльпаны", "price": 9000, "stock": 0},
            {"type": "kb", "source": "delivery", "title": "Доставка", "text": "2 000 ₸"},
        ],
        notes=["Подсказка"],
    )
    assert "Отвечай на казахском языке (kk)." in block
    assert "- PN-001 «Пионы» — 32 000 ₸, в наличии 6 шт." in block
    assert "- «Тюльпаны» — 9 000 ₸, нет в наличии" in block
    assert "- Доставка: 2 000 ₸" in block
    assert "budget_max = 30000" in block
    assert "sku" not in block.split("Известно:")[1].split("\n")[0]
    assert "Подсказка" in block


def test_money() -> None:
    assert money(1234567) == "1 234 567 ₸"


async def test_load_profile_active_version(owner_engine: AsyncEngine) -> None:
    tenant_id, _ = await make_conversation(owner_engine)
    async with owner_engine.begin() as conn:
        for version, active, tone in ((1, False, "старый"), (2, True, "новый")):
            await conn.execute(
                text(
                    "INSERT INTO bot_profiles (tenant_id, version, is_active, tone) "
                    "VALUES (:t, :v, :a, :tone)"
                ),
                {"t": tenant_id, "v": version, "a": active, "tone": tone},
            )
    async with tenant_session(tenant_id) as session:
        profile = await load_profile(session, tenant_id)
    assert profile.name == "Цветы"
    assert profile.tone == "новый"
    assert profile.version == 2


async def test_load_profile_without_bot_profile(owner_engine: AsyncEngine) -> None:
    tenant_id, _ = await make_conversation(owner_engine)
    async with tenant_session(tenant_id) as session:
        profile = await load_profile(session, tenant_id)
    assert profile.version is None
    assert "консультант магазина «Цветы»" in system_prompt(profile)
