import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.catalog.mapping import heuristic_mapping
from app.catalog.mapping_llm import LlmColumn, LlmMapping, refine_with_llm
from app.llm import LLMError, get_llm
from app.llm.fake import FakeLLM
from tests.files import csv_bytes

HEADERS = ["Тауар атауы", "Бағасы, ₸", "Х", "Бренд"]
ROWS = [["Раушан гүлдері", "24 000", "12", "Ecuador"]]


async def test_llm_refines_low_confidence_columns() -> None:
    draft = heuristic_mapping(HEADERS, ROWS)
    llm = FakeLLM(
        [
            LlmMapping(
                columns=[
                    LlmColumn(column="Тауар атауы", field="name", confidence=0.95),
                    LlmColumn(column="Х", field="stock", confidence=0.8),
                    LlmColumn(column="Бренд", field="something.bad", confidence=0.99),
                    LlmColumn(column="Бағасы, ₸", field="name", confidence=0.6),
                ]
            )
        ]
    )

    proposal = await refine_with_llm(llm, "gemini-3.1-flash-lite", HEADERS, ROWS, draft)

    fields = {c.column: c.field for c in proposal.columns}
    assert proposal.method == "llm"
    assert fields == {
        "Тауар атауы": "name",
        "Бағасы, ₸": "price",
        "Х": "stock",
        "Бренд": "attributes.бренд",
    }
    call = llm.calls[0]
    assert call.model == "gemini-3.1-flash-lite"
    assert call.response_schema is LlmMapping
    assert "Раушан гүлдері" in call.messages[-1].text


async def test_mapping_endpoint_uses_llm_and_falls_back(
    client: AsyncClient, app: FastAPI, owner: uuid.UUID
) -> None:
    data = csv_bytes([HEADERS, *ROWS])
    job_id = (
        await client.post("/catalog/uploads", files={"file": ("kk.csv", data, "text/csv")})
    ).json()["id"]

    llm = FakeLLM(
        [
            LlmMapping(columns=[LlmColumn(column="Х", field="stock", confidence=0.9)]),
            LLMError("429"),
        ]
    )
    app.dependency_overrides[get_llm] = lambda: llm

    first = (await client.get(f"/catalog/uploads/{job_id}/mapping")).json()
    assert first["method"] == "llm"
    assert next(c for c in first["columns"] if c["column"] == "Х")["field"] == "stock"

    second = (await client.get(f"/catalog/uploads/{job_id}/mapping")).json()
    assert second["method"] == "heuristic"
