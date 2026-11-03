import uuid
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.catalog.gsheet import SheetError, SheetRef, parse_sheet_url
from app.core.http import get_http_client
from app.core.storage import MemoryStorage

SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


@pytest.mark.parametrize(
    ("url", "gid"),
    [
        (f"https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid=42", "42"),
        (f"https://docs.google.com/spreadsheets/d/{SHEET}/edit?gid=7#gid=7", "7"),
        (f"https://docs.google.com/spreadsheets/d/{SHEET}/edit", "0"),
    ],
)
def test_parse_sheet_url(url: str, gid: str) -> None:
    assert parse_sheet_url(url) == SheetRef(SHEET, gid)


@pytest.mark.parametrize(
    "url", ["https://evil.com/spreadsheets/d/" + SHEET, "https://docs.google.com/document/d/x"]
)
def test_parse_rejects_non_sheets(url: str) -> None:
    with pytest.raises(SheetError):
        parse_sheet_url(url)


def _mock(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_gsheet_upload(
    client: AsyncClient, app: FastAPI, owner: uuid.UUID, storage: MemoryStorage
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            content="Название,Цена\nПионы,32000\n".encode(),
            headers={"content-type": "text/csv"},
        )

    app.dependency_overrides[get_http_client] = lambda: _mock(handler)
    url = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid=5"
    response = await client.post("/catalog/uploads/gsheet", json={"url": url})

    assert response.status_code == 201
    assert seen == [f"https://docs.google.com/spreadsheets/d/{SHEET}/export?format=csv&gid=5"]
    assert response.json()["status"] == "pending"
    [(data, content_type)] = storage.objects.values()
    assert data.decode().startswith("Название") and content_type == "text/csv"


async def test_private_sheet(client: AsyncClient, app: FastAPI, owner: uuid.UUID) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"<html>login</html>", headers={"content-type": "text/html"}
        )

    app.dependency_overrides[get_http_client] = lambda: _mock(handler)
    url = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit"
    response = await client.post("/catalog/uploads/gsheet", json={"url": url})
    assert response.status_code == 400
    assert response.json()["detail"] == "sheet_not_public"
