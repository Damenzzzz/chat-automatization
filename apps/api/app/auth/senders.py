import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

import structlog

from app.auth.identity import Identity
from app.core.config import Settings

log = structlog.get_logger()


class SenderUnavailableError(Exception):
    pass


class CodeSender(Protocol):
    async def send(self, identity: Identity, code: str) -> None: ...


class LogCodeSender:
    async def send(self, identity: Identity, code: str) -> None:
        log.info("auth.code", to=identity.value, kind=identity.kind, code=code)


class SmtpCodeSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_message(self, to: str, code: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.settings.smtp_from
        msg["To"] = to
        msg["Subject"] = f"Код входа в Satushy: {code}"
        msg.set_content(f"Ваш код: {code}\nОн действует 10 минут. Никому его не сообщайте.")
        return msg

    def _send_sync(self, msg: EmailMessage) -> None:
        s = self.settings
        assert s.smtp_host  # noqa: S101
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_user and s.smtp_password:
                smtp.login(s.smtp_user, s.smtp_password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, identity: Identity, code: str) -> None:
        await asyncio.to_thread(self._send_sync, self.build_message(identity.value, code))


class RoutingCodeSender:
    def __init__(self, email: CodeSender | None, phone: CodeSender | None) -> None:
        self.email = email
        self.phone = phone

    async def send(self, identity: Identity, code: str) -> None:
        sender = self.email if identity.kind == "email" else self.phone
        if sender is None:
            raise SenderUnavailableError(identity.kind)
        await sender.send(identity, code)


def build_code_sender(settings: Settings) -> CodeSender:
    dev_log = LogCodeSender() if settings.env != "prod" else None
    email = SmtpCodeSender(settings) if settings.smtp_host else dev_log
    return RoutingCodeSender(email=email, phone=dev_log)
