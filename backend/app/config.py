from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(PROJECT_ROOT / "backend" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    port: int = Field(default=7860, alias="PORT")
    app_access_password: str = Field(default="", alias="APP_ACCESS_PASSWORD")
    app_session_secret: str = Field(default="", alias="APP_SESSION_SECRET")

    database_url: str = Field(default="", alias="DATABASE_URL")

    tikhub_api_key: str = Field(default="", alias="TIKHUB_API_KEY")
    tikhub_base_url: str = Field(default="https://api.tikhub.io", alias="TIKHUB_BASE_URL")
    youtube_api_key: str = Field(default="", alias="YOUTUBE_API_KEY")

    ai_provider: Literal["gemini", "openai_compatible"] = Field(
        default="gemini", alias="AI_PROVIDER"
    )
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_base_url: str = Field(default="", alias="GEMINI_BASE_URL")
    gemini_fast_model: str = Field(
        default="gemini-2.5-flash-lite", alias="GEMINI_FAST_MODEL"
    )
    gemini_deep_model: str = Field(
        default="gemini-2.5-flash", alias="GEMINI_DEEP_MODEL"
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="OPENAI_BASE_URL"
    )
    openai_fast_model: str = Field(default="gpt-4o-mini", alias="OPENAI_FAST_MODEL")
    openai_deep_model: str = Field(default="gpt-4o", alias="OPENAI_DEEP_MODEL")

    enable_mock_mode: bool = Field(default=False, alias="ENABLE_MOCK_MODE")
    max_upload_mb: int = Field(default=60, alias="MAX_UPLOAD_MB")

    def resolved_session_secret(self) -> str:
        if self.app_session_secret.strip():
            return self.app_session_secret.strip()
        if not hasattr(self, "_runtime_secret"):
            object.__setattr__(self, "_runtime_secret", secrets.token_hex(32))
        return getattr(self, "_runtime_secret")

    def resolved_database_url(self) -> str:
        raw = self.database_url.strip()
        if not raw:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{DATA_DIR / 'radar.db'}"
        if raw.startswith("postgres://"):
            return "postgresql+psycopg://" + raw[len("postgres://") :]
        if raw.startswith("postgresql://") and "+psycopg" not in raw:
            return "postgresql+psycopg://" + raw[len("postgresql://") :]
        return raw

    def database_kind(self) -> str:
        url = self.resolved_database_url()
        return "postgresql" if url.startswith("postgresql") else "sqlite"


@lru_cache
def get_settings() -> Settings:
    return Settings()
