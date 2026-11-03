from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str
    redis_url: str

    s3_endpoint_url: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = "satushy"
    s3_region: str = "us-east-1"

    gemini_api_key: SecretStr | None = None
    gemini_use_vertexai: bool = True

    fernet_key: SecretStr
    jwt_secret: SecretStr

    ml_url: str = "http://localhost:8001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
