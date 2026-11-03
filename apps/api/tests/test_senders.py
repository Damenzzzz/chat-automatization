from typing import Any

import pytest
import structlog

from app.auth.identity import Identity
from app.auth.senders import (
    LogCodeSender,
    RoutingCodeSender,
    SenderUnavailableError,
    SmtpCodeSender,
    build_code_sender,
)
from app.core.config import get_settings

EMAIL = Identity("email", "owner@pion.kz")
PHONE = Identity("phone", "+77001234567")


async def test_log_sender_writes_code() -> None:
    with structlog.testing.capture_logs() as logs:
        await LogCodeSender().send(PHONE, "123456")
    assert logs[0]["event"] == "auth.code"
    assert logs[0]["code"] == "123456"


async def test_smtp_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            sent.append((host, port))

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def starttls(self) -> None:
            sent.append("starttls")

        def login(self, user: str, password: str) -> None:
            sent.append(("login", user, password))

        def send_message(self, msg: Any) -> None:
            sent.append(msg)

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    settings = get_settings().model_copy(
        update={"smtp_host": "smtp.test", "smtp_user": "bot", "smtp_password": None}
    )
    await SmtpCodeSender(settings).send(EMAIL, "654321")

    assert sent[0] == ("smtp.test", 587)
    assert sent[1] == "starttls"
    msg = sent[-1]
    assert msg["To"] == "owner@pion.kz"
    assert "654321" in msg["Subject"]


def test_build_code_sender_routing() -> None:
    settings = get_settings()
    dev = build_code_sender(settings.model_copy(update={"env": "dev"}))
    assert isinstance(dev, RoutingCodeSender)
    assert isinstance(dev.phone, LogCodeSender) and isinstance(dev.email, LogCodeSender)

    prod = build_code_sender(settings.model_copy(update={"env": "prod", "smtp_host": "smtp.test"}))
    assert isinstance(prod, RoutingCodeSender)
    assert isinstance(prod.email, SmtpCodeSender)
    assert prod.phone is None


async def test_prod_has_no_sms() -> None:
    prod = build_code_sender(get_settings().model_copy(update={"env": "prod"}))
    with pytest.raises(SenderUnavailableError):
        await prod.send(PHONE, "111111")
