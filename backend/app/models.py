from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    history_title: Mapped[str] = mapped_column(String(200), index=True)
    product_name: Mapped[str] = mapped_column(String(120), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="radar")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str] = mapped_column(String(500), default="任务已排队")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    user_instruction: Mapped[str] = mapped_column(Text, default="")
    platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    filter_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    product_dna: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    product_assets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    funnel_stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    videos: Mapped[list[VideoRecord]] = relationship(
        "VideoRecord",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="VideoRecord.replaceability_score.desc()",
    )


class VideoRecord(Base):
    __tablename__ = "video_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scan_sessions.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(20), index=True)
    platform_video_id: Mapped[str] = mapped_column(String(128))
    video_url: Mapped[str] = mapped_column(Text)
    download_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    views: Mapped[int] = mapped_column(BigInteger, default=0)
    likes: Mapped[int] = mapped_column(BigInteger, default=0)
    comments: Mapped[int] = mapped_column(BigInteger, default=0)
    shares: Mapped[int] = mapped_column(BigInteger, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)

    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_confidence: Mapped[int] = mapped_column(Integer, default=50)
    replaceability_score: Mapped[int] = mapped_column(Integer, default=0)
    original_featured_item: Mapped[str] = mapped_column(String(200), default="")
    analysis_mode: Mapped[str] = mapped_column(String(32), default="native_video")
    analysis_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    session: Mapped[ScanSession] = relationship("ScanSession", back_populates="videos")
    generated_assets: Mapped[list["GeneratedAsset"]] = relationship(
        "GeneratedAsset",
        back_populates="video",
        cascade="all, delete-orphan",
        order_by="GeneratedAsset.created_at.desc()",
    )


class GeneratedAsset(Base):
    __tablename__ = "generated_assets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("video_records.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("scan_sessions.id", ondelete="CASCADE"), index=True
    )
    # image | video_clip | uploaded_clip | final_video
    asset_type: Mapped[str] = mapped_column(String(24), index=True)
    slot_index: Mapped[int] = mapped_column(Integer, default=0)
    shot_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scene_title: Mapped[str] = mapped_column(String(200), default="")

    provider: Mapped[str] = mapped_column(String(32), default="gemini")
    model_name: Mapped[str] = mapped_column(String(80), default="")
    # pending | processing | completed | failed
    status: Mapped[str] = mapped_column(String(24), default="completed", index=True)
    prompt_used: Mapped[str] = mapped_column(Text, default="")
    external_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_image_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    mime_type: Mapped[str] = mapped_column(String(64), default="image/jpeg")
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    video: Mapped[VideoRecord] = relationship(
        "VideoRecord", back_populates="generated_assets"
    )
