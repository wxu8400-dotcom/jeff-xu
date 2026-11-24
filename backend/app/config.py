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
        default="gemini-3.5-flash-lite", alias="GEMINI_FAST_MODEL"
    )
    gemini_deep_model: str = Field(
        default="gemini-3.5-flash", alias="GEMINI_DEEP_MODEL"
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="OPENAI_BASE_URL"
    )
    openai_fast_model: str = Field(default="gpt-4o-mini", alias="OPENAI_FAST_MODEL")
    openai_deep_model: str = Field(default="gpt-4o", alias="OPENAI_DEEP_MODEL")

    # V2.0 One-Click Image Generation (Gemini native image & OpenAI gpt-image-1)
    default_image_provider: Literal["gemini", "openai"] = Field(
        default="gemini", alias="IMAGE_PROVIDER"
    )
    gemini_image_model: str = Field(
        default="gemini-2.5-flash-image", alias="GEMINI_IMAGE_MODEL"
    )
    openai_image_api_key: str = Field(default="", alias="OPENAI_IMAGE_API_KEY")
    openai_image_base_url: str = Field(default="", alias="OPENAI_IMAGE_BASE_URL")
    openai_image_model: str = Field(
        default="gpt-image-2.6-sunburst", alias="OPENAI_IMAGE_MODEL"
    )

    # V2.0 One-Click Video Generation (Kling AI official AK/SK JWT, relay key, or auto-reuse 302.ai key)
    kling_api_base_url: str = Field(
        default="https://api-beijing.klingai.com", alias="KLING_API_BASE_URL"
    )
    kling_access_key: str = Field(default="", alias="KLING_ACCESS_KEY")
    kling_secret_key: str = Field(default="", alias="KLING_SECRET_KEY")
    kling_api_key: str = Field(default="", alias="KLING_API_KEY")
    kling_model_name: str = Field(
        default="kling-v3", alias="KLING_MODEL_NAME"
    )
    kling_mode: str = Field(default="std", alias="KLING_MODE")

    enable_mock_mode: bool = Field(default=False, alias="ENABLE_MOCK_MODE")
    max_upload_mb: int = Field(default=60, alias="MAX_UPLOAD_MB")

    def gemini_image_configured(self) -> bool:
        return self.enable_mock_mode or bool(self.gemini_api_key.strip())

    def openai_image_configured(self) -> bool:
        return self.enable_mock_mode or bool(
            (self.openai_image_api_key or self.openai_api_key).strip()
        )

    def _is_302_image_relay(self) -> bool:
        img_key = self.resolved_openai_image_key()
        img_url = self.resolved_openai_image_base_url().lower()
        return bool(img_key) and ("302.ai" in img_url or "302ai.com" in img_url)

    def resolved_kling_api_key(self) -> str:
        if self.kling_api_key.strip():
            return self.kling_api_key.strip()
        if self._is_302_image_relay():
            return self.resolved_openai_image_key()
        return ""

    def resolved_kling_base_url(self) -> str:
        if self.kling_api_key.strip() or (
            self.kling_access_key.strip() and self.kling_secret_key.strip()
        ):
            raw = self.kling_api_base_url.strip().rstrip("/")
        elif self._is_302_image_relay():
            raw = self.resolved_openai_image_base_url()
        else:
            raw = self.kling_api_base_url.strip().rstrip("/")
        if raw.endswith("/v1"):
            raw = raw[:-3].rstrip("/")
        return raw

    def kling_configured(self) -> bool:
        if self.enable_mock_mode:
            return True
        if self.resolved_kling_api_key():
            return True
        return bool(self.kling_access_key.strip() and self.kling_secret_key.strip())

    def resolved_openai_image_key(self) -> str:
        return (self.openai_image_api_key or self.openai_api_key).strip()

    def resolved_openai_image_base_url(self) -> str:
        return (self.openai_image_base_url or self.openai_base_url).strip().rstrip("/")

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
