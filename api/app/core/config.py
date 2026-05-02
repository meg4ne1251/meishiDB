from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    secret_key: str = Field(min_length=16)
    database_url: str = "postgresql+asyncpg://meishi:meishi@localhost:5432/meishi"

    session_cookie_name: str = "meishi_session"
    session_ttl_days: int = 14
    cors_origins: str = "http://localhost:3000"

    ocr_service_url: str = "http://ocr:8000"
    meilisearch_url: str = ""
    meilisearch_key: str = ""
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket_original: str = "cards-original"
    minio_bucket_thumb: str = "cards-thumb"

    # WebAuthn / Passkey
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "meishiDB"
    webauthn_origin: str = "http://localhost:3000"

    # スキャナ watcher 等の自動投入用
    scanner_api_token: str = ""
    scanner_owner_email: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def webauthn_origins_list(self) -> list[str]:
        return [o.strip() for o in self.webauthn_origin.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
