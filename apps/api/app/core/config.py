from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str
    database_owner_url: str
    redis_url: str

    s3_endpoint_url: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = "satushy"
    s3_region: str = "us-east-1"

    gemini_api_key: SecretStr | None = None
    gemini_use_vertexai: bool = True
    llm_model_router: str = "gemini-3.1-flash-lite"
    llm_model_reply: str = "gemini-3.5-flash-lite"
    llm_model_complex: str = "gemini-3.6-flash"
    llm_timeout: float = 30.0
    llm_max_retries: int = 3

    fernet_key: SecretStr
    jwt_secret: SecretStr = Field(min_length=32)

    access_token_ttl: int = 15 * 60
    refresh_token_ttl: int = 30 * 24 * 3600
    otp_ttl: int = 10 * 60
    otp_max_attempts: int = 5
    otp_max_requests: int = 3

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "Satushy <no-reply@satushy.kz>"
    smtp_starttls: bool = True

    ml_url: str = "http://localhost:8001"
    ml_timeout: float = 120.0
    ml_max_retries: int = 3

    catalog_max_upload_bytes: int = 20 * 1024 * 1024
    catalog_max_rows: int = 50_000

    @property
    def cookie_secure(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
