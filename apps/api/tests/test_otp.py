import asyncio

import pytest
from pydantic import ValidationError
from redis.asyncio import Redis

from app.auth.identity import Identity, IdentityIn
from app.auth.otp import (
    CodeExpiredError,
    OtpService,
    TooManyAttemptsError,
    TooManyRequestsError,
    WrongCodeError,
)
from app.core.config import get_settings

PHONE = Identity("phone", "+77001234567")


@pytest.fixture
def otp(redis: Redis) -> OtpService:
    return OtpService(redis, get_settings())


async def test_code_roundtrip_and_only_hash_stored(otp: OtpService, redis: Redis) -> None:
    code = await otp.issue(PHONE)

    assert len(code) == 6 and code.isdigit()
    stored = await redis.get("otp:phone:+77001234567:code")
    assert stored and code not in stored and len(stored) == 64
    assert 0 < await redis.ttl("otp:phone:+77001234567:code") <= 600

    await otp.verify(PHONE, code)
    with pytest.raises(CodeExpiredError):
        await otp.verify(PHONE, code)


async def test_wrong_code_attempts_limit(otp: OtpService) -> None:
    code = await otp.issue(PHONE)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(WrongCodeError):
            await otp.verify(PHONE, wrong)

    with pytest.raises(TooManyAttemptsError):
        await otp.verify(PHONE, code)
    with pytest.raises(CodeExpiredError):
        await otp.verify(PHONE, code)


async def test_request_rate_limit(otp: OtpService) -> None:
    for _ in range(3):
        await otp.issue(PHONE)
    with pytest.raises(TooManyRequestsError):
        await otp.issue(PHONE)


async def test_expired_code(otp: OtpService, redis: Redis) -> None:
    code = await otp.issue(PHONE)
    await redis.pexpire("otp:phone:+77001234567:code", 1)
    await asyncio.sleep(0.01)

    with pytest.raises(CodeExpiredError):
        await otp.verify(PHONE, code)


async def test_verify_without_consume_keeps_code(otp: OtpService) -> None:
    code = await otp.issue(PHONE)
    await otp.verify(PHONE, code, consume=False)
    await otp.verify(PHONE, code)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("8 (700) 123-45-67", "+77001234567"), ("7001234567", "+77001234567")],
)
def test_phone_normalization(raw: str, expected: str) -> None:
    assert IdentityIn(phone=raw).identity == Identity("phone", expected)


def test_identity_requires_exactly_one_field() -> None:
    with pytest.raises(ValidationError):
        IdentityIn(phone="+77001234567", email="a@b.kz")
    with pytest.raises(ValidationError):
        IdentityIn(phone="+1 555 0100")
    assert IdentityIn(email=" Shop@Mail.KZ ").identity.value == "shop@mail.kz"
