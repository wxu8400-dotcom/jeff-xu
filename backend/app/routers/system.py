from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..config import get_settings
from ..schemas import ConfigCheckOut
from ..services.ai_client import UnifiedAIClient
from ..services.video_processor import is_ffmpeg_available

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/api/system/config-check",
    response_model=ConfigCheckOut,
    dependencies=[Depends(require_auth)],
)
def config_check() -> ConfigCheckOut:
    cfg = get_settings()
    ai = UnifiedAIClient(cfg)
    fast_model = (
        cfg.gemini_fast_model if cfg.ai_provider == "gemini" else cfg.openai_fast_model
    )
    deep_model = (
        cfg.gemini_deep_model if cfg.ai_provider == "gemini" else cfg.openai_deep_model
    )
    custom_url = bool(
        cfg.gemini_base_url.strip()
        if cfg.ai_provider == "gemini"
        else cfg.openai_base_url.strip() != "https://api.openai.com/v1"
    )
    return ConfigCheckOut(
        tikhub_configured=bool(cfg.tikhub_api_key.strip()),
        youtube_api_configured=bool(cfg.youtube_api_key.strip()),
        ai_provider=cfg.ai_provider,
        ai_configured=ai.is_configured(),
        ai_fast_model=fast_model,
        ai_deep_model=deep_model,
        ai_custom_base_url=custom_url,
        database_kind=cfg.database_kind(),
        ffmpeg_available=is_ffmpeg_available(),
        mock_mode=cfg.enable_mock_mode,
        password_protected=bool(cfg.app_access_password.strip()),
        default_image_provider=cfg.default_image_provider,
        gemini_image_configured=cfg.gemini_image_configured(),
        gemini_image_model=cfg.gemini_image_model,
        openai_image_configured=cfg.openai_image_configured(),
        openai_image_model=cfg.openai_image_model,
        kling_configured=cfg.kling_configured(),
        kling_model_name=cfg.kling_model_name,
    )
