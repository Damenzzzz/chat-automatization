import os
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ML_EMBEDDER", "fake")
os.environ.setdefault("ML_RERANKER", "fake")

from app.config import Settings
from app.main import create_app


def wait_ready(client: TestClient, timeout: float = 600.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while True:
        body: dict[str, object] = client.get("/health").json()
        if body["status"] != "loading" or time.monotonic() > deadline:
            return body
        time.sleep(0.05)


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(ml_embedder="fake", ml_reranker="fake", ml_max_texts=8)
    with TestClient(create_app(settings)) as c:
        wait_ready(c)
        yield c
