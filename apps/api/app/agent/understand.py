import re
from typing import Literal

from langchain_core.messages import AnyMessage, HumanMessage
from pydantic import BaseModel, Field

from app.llm import Message
from app.search.candidates import sku_codes
from app.search.lang import detect_lang

Intent = Literal["product", "policy", "order", "human", "smalltalk", "offtopic"]


class Slots(BaseModel):
    budget_max: int | None = Field(
        None, description="бюджет в тенге, целое число: «до 12к» → 12000"
    )
    occasion: str | None = Field(None, description="повод: день рождения, свадьба, 8 марта")
    car_make: str | None = None
    car_model: str | None = None
    year: int | None = None
    sku: str | None = Field(None, description="артикул, если покупатель его назвал")
    delivery_time: str | None = Field(None, description="когда доставить, как сказал покупатель")


class Understanding(BaseModel):
    lang: Literal["ru", "kk", "mixed"]
    intent: Intent
    complexity: Literal["low", "high"]
    slots: Slots = Field(default_factory=Slots)
    search_query: str | None = Field(
        None, description="короткий запрос для поиска по каталогу или базе знаний"
    )


ROUTER_PROMPT = """Ты классификатор сообщений покупателей интернет-магазина в Казахстане.
Определи по последнему сообщению покупателя (с учётом диалога):
- lang: ru — русский, kk — казахский, mixed — смесь языков в одном сообщении;
- intent:
  product — ищет товар, спрашивает цену, наличие, подбор;
  policy — доставка, оплата, возврат, гарантия, адрес, график работы;
  order — хочет оформить заказ, оставляет контакт, адрес, время доставки;
  human — просит живого менеджера или оператора, жалоба;
  smalltalk — приветствие, благодарность, прощание;
  offtopic — вопрос не про магазин (политика, код, домашка, другие сервисы);
- complexity: high — подбор по совместимости, несколько условий сразу, возражения, спор;
  иначе low;
- slots: только то, что покупатель явно сказал; остальное null;
- search_query: суть запроса для поиска на языке покупателя, без вежливых слов."""

INJECTION = re.compile(
    r"(ignore (all |the )?(previous|above) instructions|system prompt|"
    r"игнорируй (все |свои )?(предыдущие |прошлые )?(инструкции|правила)|"
    r"забудь (все |свои )?(инструкции|правила)|ты теперь|системн\w+ промпт)",
    re.IGNORECASE,
)
MAX_INPUT_CHARS = 2000


def is_injection(text: str) -> bool:
    return bool(INJECTION.search(text))


def router_messages(history: list[AnyMessage], text: str) -> list[Message]:
    lines = []
    for message in history[-8:-1]:
        if message.type in ("human", "ai") and isinstance(message.content, str) and message.content:
            who = "Покупатель" if isinstance(message, HumanMessage) else "Бот"
            lines.append(f"{who}: {message.content[:500]}")
    dialog = "\n".join(lines) or "(начало диалога)"
    return [
        Message("system", ROUTER_PROMPT),
        Message("user", f"Диалог:\n{dialog}\n\nПоследнее сообщение покупателя:\n{text}"),
    ]


def heuristic(text: str) -> Understanding:
    codes = sku_codes(text)
    return Understanding(
        lang=detect_lang(text) or "ru",
        intent="product",
        complexity="low",
        slots=Slots(sku=codes[0] if codes else None),
        search_query=text,
    )


def merge_slots(previous: dict[str, object] | None, new: Slots) -> dict[str, object]:
    merged = dict(previous or {})
    merged.update({k: v for k, v in new.model_dump().items() if v is not None})
    return merged
