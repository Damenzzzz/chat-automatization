import os
import uuid

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import SecretStr

from app.core.config import get_settings
from app.core.storage import S3Storage


async def test_s3_roundtrip() -> None:
    settings = get_settings().model_copy(
        update={
            "s3_endpoint_url": os.environ.get("TEST_S3_ENDPOINT_URL", "http://localhost:9000"),
            "s3_access_key": SecretStr("satushy"),
            "s3_secret_key": SecretStr("satushy-dev-secret"),
            "s3_bucket": "satushy",
        }
    )
    storage = S3Storage(settings)
    storage.client.meta.config.connect_timeout = 1
    key = f"tests/{uuid.uuid4()}.csv"
    try:
        await storage.put(key, "имя\nпион".encode(), "text/csv")
    except (BotoCoreError, ClientError) as exc:
        pytest.skip(f"MinIO недоступен: {exc}")
    assert (await storage.get(key)).decode() == "имя\nпион"
