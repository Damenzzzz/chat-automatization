import os
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ML_EMBEDDER", "fake")
os.environ.setdefault("ML_RERANKER", "fake")
os.environ.setdefault("ML_ASR", "fake")

from app.config import Settings
from app.main import create_app


def wait_ready(client: TestClient, timeout: float = 600.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        body: dict[str, Any] = client.get("/health").json()
        asr_done = body["asr"]["loaded"] or body["asr"]["error"]
        if (body["status"] != "loading" and asr_done) or time.monotonic() > deadline:
            return body
        time.sleep(0.05)


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        ml_embedder="fake",
        ml_reranker="fake",
        ml_asr="fake",
        ml_max_texts=8,
        ml_max_audio_bytes=1024,
    )
    with TestClient(create_app(settings)) as c:
        wait_ready(c)
        yield c
