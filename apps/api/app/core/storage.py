import asyncio
from functools import lru_cache
from typing import Any, Protocol

import boto3

from app.core.config import Settings, get_settings


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name=settings.s3_region,
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]


@lru_cache
def get_storage() -> Storage:
    return S3Storage(get_settings())
