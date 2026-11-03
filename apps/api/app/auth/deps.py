from functools import lru_cache

from app.auth.otp import OtpService
from app.auth.senders import CodeSender, build_code_sender
from app.auth.tokens import RefreshStore
from app.core.config import get_settings
from app.core.redis import get_redis


def get_otp() -> OtpService:
    return OtpService(get_redis(), get_settings())


@lru_cache
def get_code_sender() -> CodeSender:
    return build_code_sender(get_settings())


def get_refresh_store() -> RefreshStore:
    return RefreshStore(get_redis(), get_settings())
