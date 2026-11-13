from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import handler as h


class FakeS3:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("s3 down")
        self.puts.append(kwargs)


class FakeSNS:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("sns down")
        self.sent.append(kwargs)


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeS3, FakeSNS]:
    s3, sns = FakeS3(), FakeSNS()
    monkeypatch.setattr(h, "_clients", {"s3": s3, "sns": sns})
    monkeypatch.setenv("LEADS_BUCKET", "leads-bucket")
    monkeypatch.setenv("LEADS_TOPIC_ARN", "arn:aws:sns:eu-central-1:000000000000:leads")
    monkeypatch.setenv("ORIGIN_SECRET", "s3cret")
    return s3, sns


def event(
    body: Any, *, method: str = "POST", secret: str | None = "s3cret", b64: bool = False
) -> dict[str, Any]:
    raw = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    headers = {"content-type": "application/json", "x-forwarded-for": "203.0.113.7, 10.0.0.1"}
    if secret is not None:
        headers["X-Origin-Verify"] = secret
    return {
        "requestContext": {"http": {"method": method}},
        "headers": headers,
        "body": base64.b64encode(raw.encode()).decode() if b64 else raw,
        "isBase64Encoded": b64,
    }


GOOD = {
    "name": "Айгерим",
    "contact": "+7 700 000 00 00",
    "company": "Цветы Пион",
    "task": "Отвечать покупателям в WhatsApp ночью",
    "website": "",
    "elapsed": 15_000,
    "page": "/",
}


def body(resp: dict[str, Any]) -> dict[str, Any]:
    return json.loads(resp["body"])


def test_good_lead_is_saved_and_mailed(aws: tuple[FakeS3, FakeSNS]) -> None:
    s3, sns = aws
    resp = h.handler(event(GOOD))

    assert resp["statusCode"] == 200 and body(resp) == {"ok": True}
    assert len(s3.puts) == 1 and len(sns.sent) == 1

    put = s3.puts[0]
    assert put["Bucket"] == "leads-bucket"
    assert put["Key"].startswith("leads/") and put["Key"].endswith(".json")
    assert put["ServerSideEncryption"] == "AES256"
    stored = json.loads(put["Body"])
    assert stored["name"] == "Айгерим" and stored["contact"] == "+7 700 000 00 00"
    assert stored["ip"] == "203.0.113.7"

    mail = sns.sent[0]
    assert mail["Subject"].isascii() and len(mail["Subject"]) < 100
    assert "Айгерим" in mail["Message"] and "+7 700 000 00 00" in mail["Message"]
    assert "Отвечать покупателям" in mail["Message"]


def test_base64_body_is_accepted(aws: tuple[FakeS3, FakeSNS]) -> None:
    s3, _ = aws
    assert h.handler(event(GOOD, b64=True))["statusCode"] == 200
    assert len(s3.puts) == 1


def test_only_post(aws: tuple[FakeS3, FakeSNS]) -> None:
    s3, sns = aws
    assert h.handler(event(GOOD, method="GET"))["statusCode"] == 405
    assert not s3.puts and not sns.sent


@pytest.mark.parametrize("secret", [None, "wrong"])
def test_request_without_cloudfront_secret_is_rejected(
    aws: tuple[FakeS3, FakeSNS], secret: str | None
) -> None:
    s3, sns = aws
    # Не 403: CloudFront подменяет 403 страницей «не найдено».
    assert h.handler(event(GOOD, secret=secret))["statusCode"] == 401
    assert not s3.puts and not sns.sent


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", '"text"', "x" * (h.MAX_BODY + 1)])
def test_broken_body_is_400(aws: tuple[FakeS3, FakeSNS], raw: str) -> None:
    s3, sns = aws
    assert h.handler(event(raw))["statusCode"] == 400
    assert not s3.puts and not sns.sent


@pytest.mark.parametrize(
    ("patch", "word"),
    [
        ({"name": "   "}, "зовут"),
        ({"contact": "a"}, "связи"),
        ({"name": 5}, "зовут"),
        ({"contact": None}, "связи"),
    ],
)
def test_required_fields(aws: tuple[FakeS3, FakeSNS], patch: dict[str, Any], word: str) -> None:
    s3, sns = aws
    resp = h.handler(event({**GOOD, **patch}))
    assert resp["statusCode"] == 400 and word in body(resp)["error"]
    assert not s3.puts and not sns.sent


@pytest.mark.parametrize("patch", [{"website": "http://spam.example"}, {"elapsed": 300}])
def test_bots_get_ok_but_nothing_is_stored(
    aws: tuple[FakeS3, FakeSNS], patch: dict[str, Any]
) -> None:
    s3, sns = aws
    resp = h.handler(event({**GOOD, **patch}))
    assert resp["statusCode"] == 200 and body(resp) == {"ok": True}
    assert not s3.puts and not sns.sent


def test_missing_elapsed_is_not_treated_as_bot(aws: tuple[FakeS3, FakeSNS]) -> None:
    s3, _ = aws
    lead = {k: v for k, v in GOOD.items() if k != "elapsed"}
    assert h.handler(event(lead))["statusCode"] == 200
    assert len(s3.puts) == 1


def test_long_and_dirty_fields_are_trimmed(aws: tuple[FakeS3, FakeSNS]) -> None:
    s3, _ = aws
    h.handler(event({**GOOD, "name": "А" * 500, "task": "строка\x00 с\x07 мусором\nвторая"}))
    stored = json.loads(s3.puts[0]["Body"])
    assert len(stored["name"]) == h.LIMITS["name"]
    assert stored["task"] == "строка с мусором\nвторая"


def test_lead_survives_mail_failure(
    aws: tuple[FakeS3, FakeSNS], monkeypatch: pytest.MonkeyPatch
) -> None:
    s3, _ = aws
    monkeypatch.setattr(h, "_clients", {"s3": s3, "sns": FakeSNS(fail=True)})
    assert h.handler(event(GOOD))["statusCode"] == 200
    assert len(s3.puts) == 1


def test_lead_survives_storage_failure(
    aws: tuple[FakeS3, FakeSNS], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, sns = aws
    monkeypatch.setattr(h, "_clients", {"s3": FakeS3(fail=True), "sns": sns})
    assert h.handler(event(GOOD))["statusCode"] == 200
    assert len(sns.sent) == 1


def test_error_when_lead_is_lost(
    aws: tuple[FakeS3, FakeSNS], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(h, "_clients", {"s3": FakeS3(fail=True), "sns": FakeSNS(fail=True)})
    resp = h.handler(event(GOOD))
    assert resp["statusCode"] == 502 and body(resp)["ok"] is False


def test_customer_text_never_reaches_logs(
    aws: tuple[FakeS3, FakeSNS], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        h.handler(event(GOOD))
    assert caplog.text, "ожидалась запись о заявке"
    for secret_text in ("Айгерим", "700 000", "Цветы Пион", "WhatsApp", "203.0.113.7"):
        assert secret_text not in caplog.text
