import re
from typing import Literal

Lang = Literal["ru", "kk", "mixed"]

WORD = re.compile(r"[а-яёәғқңөұүһі]+", re.IGNORECASE)
KK_LETTERS = set("әғқңөұүһі")
KK_WORDS = {
    "бар",
    "ма",
    "ме",
    "ба",
    "бе",
    "па",
    "пе",
    "жоқ",
    "және",
    "мен",
    "бір",
    "екі",
    "үш",
    "қанша",
    "қай",
    "керек",
    "бағасы",
    "тұрады",
    "сатасыз",
    "ба?",
    "гүл",
    "гүлдер",
    "шоқ",
    "сәлем",
    "рахмет",
    "иә",
    "жеткізу",
    "жеткізесіз",
    "анама",
    "апама",
    "сыйлық",
    "қызыл",
    "ақ",
    "сары",
    "көк",
    "үшін",
    "дейін",
    "арзан",
    "қымбат",
    "бүгін",
    "ертең",
    "раушан",
}


def _is_kk(word: str) -> bool:
    return bool(KK_LETTERS & set(word)) or word in KK_WORDS


def detect_lang(text: str) -> Lang | None:
    words = [w.lower() for w in WORD.findall(text)]
    if not words:
        return None
    kk = sum(_is_kk(w) for w in words)
    if kk == 0:
        return "ru"
    if kk == len(words) or kk / len(words) >= 0.6:
        return "kk"
    return "mixed"
