import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.agent.prompt import ShopProfile, money
from app.catalog.normalize import sku_norm
from app.search.lang import WORD, detect_lang

NUMBER = r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
AMOUNT = re.compile(
    rf"(?<![\w.,])(?P<num>{NUMBER})"
    r"(?:\s*(?P<thousand>тыс\.?|тысяч\w*|мың)|(?P<k>[кkК])(?![а-яёa-z]))?"
    r"(?:\s*(?P<cur>₸|тг\.?|тенге|теңге|kzt))?",
    re.IGNORECASE,
)
NOISE = re.compile(
    r"\+?[78][\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"
    r"|\d{1,2}:\d{2}"
    r"|\d+(?:[.,]\d+)?\s*%"
    r"|\d{1,2}\.\d{1,2}\.\d{2,4}"
)
PHONE = re.compile(
    r"\+?[78][\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"
    r"|\b\d{3}[\s-]\d{2}[\s-]\d{2}\b"
)
DOMAINS = "kz|ru|com|app|me|shop|store|net|org"
URL = re.compile(
    r"(?:https?://|www\.)[^\s,;)»\"]+"
    rf"|\b[\w-]+\.(?:{DOMAINS})\b(?:/[^\s,;)»\"]*)?",
    re.IGNORECASE,
)
STOCK_WORDS = r"в наличии|наличии|осталось|остаток|осталась|остался|қалды|бар"
STOCK = re.compile(
    rf"(?:{STOCK_WORDS})\D{{0,12}}?(?P<a>\d+)\s*(?:шт|штук|дана)"
    rf"|(?P<b>\d+)\s*(?:шт\.?|штук\w*|дана)\s*(?:{STOCK_WORDS})",
    re.IGNORECASE,
)
TOPICS = {
    "возврат и обмен": re.compile(r"возврат|вернуть|верн[её]м|обмен|қайтар|ауыстыр", re.I),
    "скидки и акции": re.compile(r"скидк|акци[яиюй]|промокод|жеңілдік", re.I),
    "гарантию": re.compile(r"гаранти|кепілдік", re.I),
    "рассрочку": re.compile(r"рассрочк|кредит|бөліп төле", re.I),
}
DEFER = re.compile(r"уточн|менеджер|нақтыла|узна[юе]", re.I)
NO_TERMS = "в данных магазина нет условий про"
PROMISE = re.compile(
    r"уточн\w*[^.!?\n]{0,40}менеджер"
    r"|менеджер\w*[^.!?\n]{0,30}(подключ|свяж|ответ|напиш|перезвон)"
    r"|передал\w*[^.!?\n]{0,30}менеджер"
    r"|менеджер\w*[^.!?\n]{0,30}(нақтыла|жауап|хабарлас|қосыл)",
    re.IGNORECASE,
)


def promises_manager(reply: str) -> bool:
    """Бот пообещал, что дальше ответит человек: тогда диалог должен уйти менеджеру."""
    return bool(PROMISE.search(reply))


KK_CHECK_WORDS = 6
WELL_KNOWN = frozenset({"kaspi.kz"})
SENTENCE = re.compile(r"[!?\n]+|\.\s+(?=[A-ZА-ЯЁӘҒҚҢӨҰҮҺІ])")
SKU_LIKE = re.compile(r"(?<![\w-])[A-Za-zА-ЯЁа-яё]{1,5}-?\d{2,}[A-Za-z0-9-]*(?![\w-])")
MAX_TERMS = 4
MAX_BASE = 40
MAX_COUNT = 1000


@dataclass
class Amount:
    value: int
    text: str


@dataclass
class CheckResult:
    amounts: list[int] = field(default_factory=list)
    skus: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _value(match: re.Match[str]) -> int:
    raw = re.sub(r"[   ]", "", match["num"]).replace(",", ".")
    value = float(raw)
    if match["thousand"] or match["k"]:
        value *= 1000
    return round(value)


def numbers(text: str) -> set[int]:
    return {_value(m) for m in AMOUNT.finditer(NOISE.sub(" ", text))}


def amounts(text: str) -> list[Amount]:
    found: list[Amount] = []
    for sentence in SENTENCE.split(NOISE.sub(" ", text)):
        matches = list(AMOUNT.finditer(sentence))
        marked = [m for m in matches if m["cur"] or m["thousand"] or m["k"]]
        if not marked:
            continue
        for m in matches:
            value = _value(m)
            if m in marked or value >= 1000:
                found.append(Amount(value, m.group(0).strip()))
    return found


def _sums(base: Iterable[int]) -> set[int]:
    values = sorted({v for v in base if v > 0})[:MAX_BASE]
    allowed = set(values)
    layer = set(values)
    for _ in range(MAX_TERMS - 1):
        layer = {a + b for a in layer for b in values}
        allowed |= layer
    return allowed


def allowed_base(
    context: list[dict[str, Any]], profile: ShopProfile, customer_text: str, slots: dict[str, Any]
) -> set[int]:
    base: set[int] = set()
    for item in context:
        if item.get("type") == "product":
            if item.get("price") is not None:
                base.add(int(item["price"]))
            details = f"{item.get('attributes') or ''} {item.get('description') or ''}"
            base |= numbers(details)
        elif item.get("type") == "lead" and item.get("total_kzt") is not None:
            base.add(int(item["total_kzt"]))
        elif item.get("type") == "kb":
            base |= numbers(str(item.get("text", "")))
    profile_text = " ".join(
        [profile.tone or "", profile.greeting or "", *map(str, profile.rules.values())]
    )
    base |= numbers(profile_text)
    base |= numbers(customer_text)
    if slots.get("budget_max"):
        base.add(int(slots["budget_max"]))
    return base


def phones(text: str) -> set[str]:
    return {re.sub(r"\D", "", m)[-7:] for m in PHONE.findall(text)}


def urls(text: str) -> set[str]:
    return {_url_key(m) for m in URL.findall(text)}


def _url_key(value: str) -> str:
    key = re.sub(r"^(?:https?://)?(?:www\.)?", "", value.lower())
    return key.rstrip(".!?/")


def sources_text(
    context: list[dict[str, Any]], profile: ShopProfile, customer_text: str = ""
) -> str:
    parts = [
        profile.tone or "",
        profile.greeting or "",
        *map(str, profile.rules.values()),
        customer_text,
    ]
    for item in context:
        if item.get("type") == "kb":
            parts += [str(item.get("title") or ""), str(item.get("text") or "")]
        elif item.get("type") == "product":
            parts += [str(item.get("description") or ""), str(item.get("attributes") or "")]
    return "\n".join(parts)


def check_facts(
    reply: str,
    context: list[dict[str, Any]],
    profile: ShopProfile,
    customer_text: str,
    lang: str | None,
) -> list[str]:
    errors: list[str] = []
    source = sources_text(context, profile, customer_text)
    known_phones = phones(source)
    for match in PHONE.finditer(reply):
        if re.sub(r"\D", "", match.group(0))[-7:] not in known_phones:
            errors.append(f"телефона «{match.group(0).strip()}» нет в данных магазина")
    known_urls = urls(source) | WELL_KNOWN
    for match in URL.finditer(reply):
        key = _url_key(match.group(0))
        if not any(key == k or key.startswith(k + "/") or k.startswith(key) for k in known_urls):
            errors.append(f"ссылки «{match.group(0)}» нет в данных магазина")
    stocks = {
        int(item["stock"])
        for item in context
        if item.get("type") == "product" and item.get("stock") is not None
    }
    names = " ".join(str(item.get("name") or "") for item in context)
    allowed = stocks | numbers(names) | numbers(source)
    for match in STOCK.finditer(reply):
        value = int(match["a"] or match["b"])
        if value not in allowed:
            errors.append(f"остаток «{match.group(0)}» не совпадает с каталогом")
    shop_data = sources_text(context, profile)
    if not DEFER.search(reply):
        for topic, pattern in TOPICS.items():
            if pattern.search(reply) and not pattern.search(shop_data):
                errors.append(f"{NO_TERMS} {topic}: не придумывай, предложи уточнить у менеджера")
    words = WORD.findall(reply)
    kk_shop = "kk" in profile.languages
    if lang == "kk" and kk_shop and len(words) >= KK_CHECK_WORDS and detect_lang(reply) == "ru":
        errors.append("покупатель пишет по-казахски, а ответ на русском")
    return errors


def check_reply(
    reply: str,
    context: list[dict[str, Any]],
    profile: ShopProfile,
    customer_text: str = "",
    slots: dict[str, Any] | None = None,
    lang: str | None = None,
) -> CheckResult:
    result = CheckResult()
    if not reply.strip():
        result.errors.append("ответ пустой")
        return result
    allowed = _sums(allowed_base(context, profile, customer_text, slots or {}))
    prices = {int(i["price"]) for i in context if i.get("type") == "product" and i.get("price")}
    counts = {n for n in numbers(reply) | numbers(customer_text) if 1 < n < MAX_COUNT}
    allowed |= {price * count for price in prices for count in counts}
    for amount in amounts(reply):
        result.amounts.append(amount.value)
        if amount.value not in allowed:
            result.errors.append(
                f"сумма «{amount.text}» ({money(amount.value)}) не совпадает с ценами товаров"
                " и правилами магазина"
            )
    known = {item.get("sku_norm") for item in context if item.get("type") == "product"}
    for token in SKU_LIKE.findall(reply):
        code = sku_norm(token)
        result.skus.append(code or token)
        if code not in known:
            result.errors.append(f"артикула «{token}» нет среди найденных товаров")
    result.errors += check_facts(reply, context, profile, customer_text, lang)
    return result
