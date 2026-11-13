"""Приём заявок с лендинга: проверка, сохранение в S3, письмо через SNS.

Текст заявки и контакты в логи не пишутся — только номер заявки и итог.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hmac
import json
import logging
import os
import secrets
from typing import Any

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_BODY = 10_000
MIN_FILL_MS = 2_000
LIMITS = {"name": 100, "contact": 200, "company": 150, "task": 3000}

_clients: dict[str, Any] = {}


def _client(name: str) -> Any:
    if name not in _clients:
        import boto3  # есть в среде Lambda; в тестах клиенты подменяются

        _clients[name] = boto3.client(name)
    return _clients[name]


def _reply(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _clean(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32)
    return text.strip()[:limit]


def parse(event: dict[str, Any]) -> dict[str, Any] | None:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
    if len(raw) > MAX_BODY:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def is_bot(data: dict[str, Any]) -> bool:
    """Ловушка: скрытое поле заполнено или форму отправили быстрее человека."""
    if _clean(data.get("website"), 200):
        return True
    elapsed = data.get("elapsed")
    return (
        isinstance(elapsed, (int, float))
        and not isinstance(elapsed, bool)
        and elapsed < MIN_FILL_MS
    )


def letter(lead: dict[str, str]) -> str:
    lines = [
        "Новая заявка с сайта Satushy",
        "",
        f"Имя: {lead['name']}",
        f"Контакт: {lead['contact']}",
        f"Компания: {lead['company'] or '—'}",
        "",
        "Задача:",
        lead["task"] or "—",
        "",
        f"Время (UTC): {lead['received_at']}",
        f"Номер заявки: {lead['id']}",
    ]
    return "\n".join(lines)


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    http = (event.get("requestContext") or {}).get("http") or {}
    if http.get("method") != "POST":
        return _reply(405, {"ok": False, "error": "Метод не поддерживается."})

    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    expected = os.environ.get("ORIGIN_SECRET", "")
    # Запросы принимаются только через CloudFront: он подставляет секретный заголовок.
    if expected and not hmac.compare_digest(headers.get("x-origin-verify", ""), expected):
        return _reply(401, {"ok": False, "error": "Запрос отклонён."})

    data = parse(event)
    if data is None:
        return _reply(
            400,
            {"ok": False, "error": "Заявка не разобрана. Обновите страницу и попробуйте ещё раз."},
        )

    if is_bot(data):
        # Роботу отвечаем как обычно, чтобы он не подбирал обход.
        return _reply(200, {"ok": True})

    lead = {field: _clean(data.get(field), limit) for field, limit in LIMITS.items()}
    if not lead["name"]:
        return _reply(400, {"ok": False, "error": "Укажите, как вас зовут."})
    if len(lead["contact"]) < 3:
        return _reply(400, {"ok": False, "error": "Укажите телефон, Telegram или почту для связи."})

    now = dt.datetime.now(dt.UTC)
    lead["id"] = f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    lead["received_at"] = now.isoformat(timespec="seconds")
    lead["page"] = _clean(data.get("page"), 200)
    lead["ip"] = headers.get("x-forwarded-for", "").split(",")[0].strip()[:64]

    saved = sent = False
    bucket = os.environ.get("LEADS_BUCKET", "")
    if bucket:
        try:
            _client("s3").put_object(
                Bucket=bucket,
                Key=f"leads/{now:%Y/%m}/{lead['id']}.json",
                Body=json.dumps(lead, ensure_ascii=False, indent=2).encode("utf-8"),
                ContentType="application/json; charset=utf-8",
                ServerSideEncryption="AES256",
            )
            saved = True
        except Exception:
            log.exception("lead %s: не сохранена в S3", lead["id"])

    topic = os.environ.get("LEADS_TOPIC_ARN", "")
    if topic:
        try:
            # Тема письма в SNS — только ASCII, поэтому латиницей.
            _client("sns").publish(
                TopicArn=topic, Subject="Satushy: novaya zayavka s sayta", Message=letter(lead)
            )
            sent = True
        except Exception:
            log.exception("lead %s: письмо не отправлено", lead["id"])

    if not saved and not sent:
        log.error("lead %s: потеряна", lead["id"])
        return _reply(
            502, {"ok": False, "error": "Заявка не отправилась. Попробуйте ещё раз через минуту."}
        )

    log.info("lead %s: saved=%s sent=%s", lead["id"], saved, sent)
    return _reply(200, {"ok": True})
