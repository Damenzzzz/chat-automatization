import re
from dataclasses import dataclass
from typing import Literal, Self

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, model_validator

Kind = Literal["phone", "email"]


@dataclass(frozen=True)
class Identity:
    kind: Kind
    value: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.value}"


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) != 11 or digits[0] != "7":
        raise ValueError("номер должен быть казахстанским: +7XXXXXXXXXX")
    return "+" + digits


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc


class IdentityIn(BaseModel):
    phone: str | None = None
    email: str | None = None

    @model_validator(mode="after")
    def _normalize(self) -> Self:
        if (self.phone is None) == (self.email is None):
            raise ValueError("укажите либо phone, либо email")
        if self.phone is not None:
            self.phone = normalize_phone(self.phone)
        if self.email is not None:
            self.email = normalize_email(self.email)
        return self

    @property
    def identity(self) -> Identity:
        if self.phone is not None:
            return Identity("phone", self.phone)
        return Identity("email", self.email or "")
