import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class CryptoError(Exception):
    pass


@lru_cache
def _fernet() -> Fernet:
    try:
        return Fernet(get_settings().fernet_key.get_secret_value())
    except ValueError as exc:
        raise CryptoError("FERNET_KEY не задан или неверен") from exc


def encrypt_json(data: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt_json(token: bytes) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(_fernet().decrypt(token))
    except InvalidToken as exc:
        raise CryptoError("не удалось расшифровать ключи канала") from exc
    return data
