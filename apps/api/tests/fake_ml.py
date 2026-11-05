import hashlib
import math
import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.catalog.embedding_text import product_text
from app.search.candidates import vector_literal

WORD = re.compile(r"\w+")


def _features(value: str) -> list[str]:
    words = [w.lower() for w in WORD.findall(value)]
    grams = [w[i : i + 4] for w in words for i in range(max(1, len(w) - 3))]
    return words + grams


def embed_text(value: str) -> list[float]:
    vector = [0.0] * 1024
    for feature in _features(value):
        digest = hashlib.md5(feature.encode()).digest()  # noqa: S324
        vector[int.from_bytes(digest[:2], "big") % 1024] += 1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class FakeML:
    def __init__(self, *, fail: bool = False, transcript: str = "голосовой текст") -> None:
        self.fail = fail
        self.reranked: list[list[str]] = []
        self.transcript = transcript
        self.transcribed: list[tuple[bytes, str | None]] = []

    async def transcribe(self, audio: bytes, mime_type: str | None = None) -> Any:
        from app.mlclient import MLError, Transcript

        if self.fail:
            raise MLError("down")
        self.transcribed.append((audio, mime_type))
        return Transcript(self.transcript, "kk", 0.9, 2.5, "fake-asr")

    async def embed(self, texts: list[str], kind: Any) -> list[list[float]]:
        if self.fail:
            from app.mlclient import MLError

            raise MLError("down")
        return [embed_text(t) for t in texts]

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if self.fail:
            from app.mlclient import MLError

            raise MLError("down")
        self.reranked.append(documents)
        q = set(_features(query))
        return [len(q & set(_features(d))) / (len(q) or 1) for d in documents]


async def make_shop(
    engine: AsyncEngine, products: list[dict[str, Any]], kb: list[dict[str, str]] | None = None
) -> uuid.UUID:
    async with engine.begin() as conn:
        tenant_id: uuid.UUID = await conn.scalar(
            text("INSERT INTO tenants (name) VALUES ('Поиск') RETURNING id")
        )
        for item in products:
            row = {"sku": None, "category": None, "description": None, "stock": 5, **item}
            vector = embed_text(
                product_text(row["name"], row["category"], row["description"], None, None)
            )
            await conn.execute(
                text(
                    "INSERT INTO products (tenant_id, sku, name, category, description, price,"
                    " stock, embedding, embedding_stale) VALUES (:t, :sku, :name, :category,"
                    " :description, :price, :stock, CAST(:v AS vector), false)"
                ),
                {"t": tenant_id, "v": vector_literal(vector), **row},
            )
        for chunk in kb or []:
            vector = embed_text(f"{chunk['title']}\n{chunk['text']}")
            await conn.execute(
                text(
                    "INSERT INTO kb_chunks (tenant_id, source, title, text, embedding,"
                    " embedding_stale) VALUES (:t, :source, :title, :text, CAST(:v AS vector),"
                    " false)"
                ),
                {"t": tenant_id, "v": vector_literal(vector), **chunk},
            )
    return tenant_id
