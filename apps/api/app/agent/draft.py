import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.guard import check_reply
from app.agent.llmcall import call_llm
from app.agent.prompt import context_block, load_profile, system_prompt
from app.agent.tools import kb_item, product_item
from app.core.config import get_settings
from app.llm import LLM, Message
from app.models import Message as StoredMessage
from app.search import search_kb, search_products
from app.search.lang import detect_lang
from app.search.types import SearchML

HISTORY = 12
TASK = (
    "[Задача] Сейчас покупателю отвечает менеджер магазина. Напиши черновик его следующего"
    " сообщения: коротко и по делу, без приветствия, если оно уже было. Цены и остатки бери"
    " только из данных выше. Не обещай скидки, сроки и условия, которых там нет: предложи"
    " уточнить. Верни только текст сообщения."
)
ROLES = {"customer": "user", "bot": "model", "manager": "model"}


@dataclass(frozen=True)
class Draft:
    text: str
    verified: bool


class NothingToAnswerError(Exception):
    pass


async def draft_reply(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    llm: LLM,
    ml: SearchML,
) -> Draft:
    rows = list(
        await session.scalars(
            select(StoredMessage)
            .where(
                StoredMessage.conversation_id == conversation_id,
                StoredMessage.role.in_(tuple(ROLES)),
                StoredMessage.content.is_not(None),
            )
            .order_by(StoredMessage.created_at.desc())
            .limit(HISTORY)
        )
    )
    rows.reverse()
    question = next((m.content for m in reversed(rows) if m.role == "customer"), None)
    if not question:
        raise NothingToAnswerError
    profile = await load_profile(session, tenant_id)
    products = await search_products(session, question, ml=ml, record=False)
    articles = await search_kb(session, question, ml=ml, record=False)
    context = [*map(product_item, products.items), *map(kb_item, articles.items)]
    lang = detect_lang(question) or "ru"
    data = context_block(lang=lang, intent=None, slots=None, context=context, notes=[TASK])
    messages = [
        Message("system", system_prompt(profile)),
        *(Message(ROLES[m.role], m.content or "") for m in rows),  # type: ignore[arg-type]
        Message("user", data),
    ]
    response, _ = await call_llm(llm, "draft", get_settings().llm_model_reply, messages)
    text = (response.text or "").strip()
    return Draft(text=text, verified=check_reply(text, context, profile, question).ok)
