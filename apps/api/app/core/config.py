from decimal import Decimal
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_PREFIX = "dev-only"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"]
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
    otp_ip_requests: int = 20

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "Satushy <no-reply@satushy.kz>"
    smtp_starttls: bool = True

    ml_url: str = "http://localhost:8001"
    ml_timeout: float = 120.0
    ml_max_retries: int = 3

    search_candidates: int = 50
    search_rrf_k: int = 60
    search_rerank_top: int = 20
    search_ef_search: int = 100

    catalog_max_upload_bytes: int = 20 * 1024 * 1024
    catalog_max_rows: int = 50_000

    pricing_kzt_per_usd: Decimal = Decimal(454)

    billing_seller_name: str | None = None
    billing_seller_iin: str | None = None
    billing_seller_iik: str | None = None
    billing_seller_bank: str | None = None
    billing_seller_bik: str | None = None
    billing_seller_kbe: str = "19"
    billing_seller_knp: str = "859"
    billing_seller_address: str | None = None
    billing_seller_vat_note: str = "Без НДС"

    analytics_timezone: str = "Asia/Almaty"
    bot_replies_per_hour: int = 30
    human_idle_release_hours: int = 12
    conversation_idle_close_days: int = 30
    sandbox_keep_days: int = 7
    search_log_keep_days: int = 90
    lead_reminder_hours: int = 2
    unanswered_group_threshold: float = 0.85

    demo_enabled: bool = False
    demo_chat_daily_limit: int = 3000
    sandbox_messages_per_hour: int = 120
    sandbox_autotests_per_hour: int = 6
    widget_channel_messages_per_hour: int = 600
    widget_sessions_per_ip_hour: int = 20

    public_api_url: str = "http://localhost:8100"
    public_web_url: str = "http://localhost:3000"
    channel_debounce_seconds: float = 1.5
    whatsapp_graph_version: str = "v25.0"

    @model_validator(mode="after")
    def no_dev_secrets_in_prod(self) -> Self:
        if self.env == "prod" and self.jwt_secret.get_secret_value().startswith(DEV_SECRET_PREFIX):
            raise ValueError("JWT_SECRET из .env.example нельзя использовать при ENV=prod")
        return self

    @property
    def cookie_secure(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
