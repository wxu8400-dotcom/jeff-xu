from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchQueries(BaseModel):
    tiktok: list[str] = Field(default_factory=list)
    instagram: list[str] = Field(default_factory=list)
    youtube: list[str] = Field(default_factory=list)


class ProductDNA(BaseModel):
    product_name: str = "未命名产品"
    category: str = "通用消费品"
    physical_form: str = ""
    core_selling_points: list[str] = Field(default_factory=list)
    target_audience: str = ""
    usage_scenarios: list[str] = Field(default_factory=list)
    replaceable_visual_slots: list[str] = Field(default_factory=list)
    avoid_patterns: list[str] = Field(default_factory=list)
    category_leak_keywords: list[str] = Field(default_factory=list)
    search_queries: SearchQueries = Field(default_factory=SearchQueries)


class PreliminaryScreeningItem(BaseModel):
    candidate_id: str
    preliminary_score: int = Field(ge=0, le=100)
    visual_creativity_score: int = Field(ge=0, le=100, default=75)
    is_same_category: bool = False
    is_cartoon_or_animation: bool = False
    has_realistic_human: bool = True
    original_featured_item: str = ""
    reason: str = ""
    is_replaceable: bool = False


class PreliminaryScreeningBatch(BaseModel):
    results: list[PreliminaryScreeningItem] = Field(default_factory=list)


class ReplaceabilityAnalysis(BaseModel):
    score: int = Field(ge=0, le=100, default=75)
    original_featured_item: str = ""
    replacement_strategy: str = ""
    replacement_difficulty: str = "中"
    recommended_workflow: str = "实拍复刻 + AI复刻双方案皆可"


class VideoStructureAnalysis(BaseModel):
    hook_3s: str = ""
    pacing_curve: str = ""
    conversion_cta: str = ""
    viral_reasons: list[str] = Field(default_factory=list)


class StoryboardShot(BaseModel):
    shot_no: int = 1
    time_range: str = "00:00-00:03"
    shot_size: str = "特写"
    camera_movement: str = "推镜"
    original_visual: str = ""
    adapted_visual_for_product: str = ""
    audio_sfx: str = ""
    production_mode: str = "ai"  # "ai" | "real_shoot"
    real_shoot_guide: str = ""
    spoken_line: str = ""
    # V2.1 1:1 Faithful Replication & Director Co-creation fields
    replication_action: str = "insert_product"  # "keep_scene" | "insert_product" | "rewrite_scene"
    director_advice: str = ""
    has_person: bool = False


class DirectorPlan(BaseModel):
    original_plot_summary: str = ""
    ai_character_profile_cn: str = ""
    ai_character_profile_en: str = ""
    product_placement_plan: str = ""
    open_questions_for_user: list[str] = Field(default_factory=list)
    revision_status: str = "draft"  # "draft" | "locked"
    revision_history: list[dict[str, Any]] = Field(default_factory=list)


class ShootingRequirements(BaseModel):
    lighting: str = ""
    camera_setup: str = ""
    props_and_scene: str = ""
    editing_rhythm: str = ""
    bgm_style: str = ""


class CopywritingAnalysis(BaseModel):
    original_transcript: str = ""
    chinese_translation: str = ""
    adapted_script_cn: str = ""
    adapted_script_en: str = ""
    caption_and_hashtags: str = ""


class ChatGPTImagePrompt(BaseModel):
    scene_title: str = "爆款主视觉海报"
    usage_note: str = "在 ChatGPT 中上传你的产品实拍图，然后直接复制下方提示词发送"
    aspect_ratio: str = "9:16"
    prompt_en: str = ""
    prompt_cn: str = ""


class KlingVideoPrompt(BaseModel):
    shot_no: int = 1
    scene_title: str = "分镜1"
    mode: str = "图生视频 (I2V)"
    recommended_params: str = "时长: 5s | 画质: 高品质 | 运镜: 缓慢推进 | 创意相关性: 0.5"
    prompt_cn: str = ""
    prompt_en: str = ""
    negative_prompt: str = (
        "变形, 模糊, 产品Logo扭曲, 穿模, 多余手指, 闪烁, 画面撕裂, 水印, 杂乱文字"
    )


class VideoDeepAnalysis(BaseModel):
    is_ai_generated: bool = False
    ai_confidence: int = Field(ge=0, le=100, default=70)
    ai_detection_reason: str = ""
    director_plan: DirectorPlan = Field(default_factory=DirectorPlan)
    replaceability: ReplaceabilityAnalysis = Field(
        default_factory=ReplaceabilityAnalysis
    )
    structure: VideoStructureAnalysis = Field(default_factory=VideoStructureAnalysis)
    storyboard: list[StoryboardShot] = Field(default_factory=list)
    shooting_requirements: ShootingRequirements = Field(
        default_factory=ShootingRequirements
    )
    copywriting: CopywritingAnalysis = Field(default_factory=CopywritingAnalysis)
    chatgpt_images_prompts: list[ChatGPTImagePrompt] = Field(default_factory=list)
    kling_prompts: list[KlingVideoPrompt] = Field(default_factory=list)


class LearnedMemoryItem(BaseModel):
    category: str = "product_replacement"  # character | scene_style | product_replacement | pacing_framing | taboo
    product_scope: str = "global"
    rule_summary: str
    example_snippet: str = ""


class DirectorRevisionResponse(BaseModel):
    director_reply: str = ""
    changed_shots: list[int] = Field(default_factory=list)
    learned_memories: list[LearnedMemoryItem] = Field(default_factory=list)
    analysis: VideoDeepAnalysis


class DirectorMemoryOut(BaseModel):
    id: str
    category: str
    product_scope: str
    rule_summary: str
    example_snippet: str = ""
    source_video_title: str = ""
    confidence_hits: int = 1
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class CreateDirectorMemoryRequest(BaseModel):
    category: str = "product_replacement"
    product_scope: str = "global"
    rule_summary: str
    example_snippet: str = ""


class UpdateDirectorMemoryRequest(BaseModel):
    rule_summary: str | None = None
    category: str | None = None
    product_scope: str | None = None
    example_snippet: str | None = None
    is_active: bool | None = None


class VideoRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    platform: str
    platform_video_id: str
    video_url: str
    cover_url: str | None = None
    author_name: str | None = None
    title: str
    published_at: str | None = None
    duration_sec: int | None = None
    views: int
    likes: int
    comments: int
    shares: int
    engagement_rate: float
    is_ai_generated: bool
    ai_confidence: int
    replaceability_score: int
    original_featured_item: str
    analysis_mode: str
    analysis_json: dict[str, Any]
    token_usage: dict[str, Any]
    created_at: datetime


class ScanSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    history_title: str
    product_name: str
    mode: str
    status: str
    progress_percent: int
    progress_message: str
    error_message: str | None = None
    platforms: list[str]
    funnel_stats: dict[str, Any]
    video_count: int = 0
    created_at: datetime
    updated_at: datetime


class ScanSessionDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    history_title: str
    product_name: str
    mode: str
    status: str
    progress_percent: int
    progress_message: str
    error_message: str | None = None
    user_instruction: str
    platforms: list[str]
    filter_config: dict[str, Any]
    product_dna: dict[str, Any] | None = None
    product_assets: list[dict[str, Any]]
    funnel_stats: dict[str, Any]
    videos: list[VideoRecordOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    password: str


class AuthStatusOut(BaseModel):
    password_required: bool
    authenticated: bool


class ConfigCheckOut(BaseModel):
    tikhub_configured: bool
    youtube_api_configured: bool
    ai_provider: Literal["gemini", "openai_compatible"]
    ai_configured: bool
    ai_fast_model: str
    ai_deep_model: str
    ai_custom_base_url: bool
    database_kind: str
    database_warning: str | None = None
    ffmpeg_available: bool
    mock_mode: bool
    password_protected: bool
    # V2.0 One-Click Generation capabilities
    default_image_provider: Literal["gemini", "openai"] = "gemini"
    gemini_image_configured: bool = False
    gemini_image_model: str = "gemini-2.5-flash-image"
    openai_image_configured: bool = False
    openai_image_model: str = "gpt-image-2.6-sunburst"
    kling_configured: bool = False
    kling_model_name: str = "kling-v2-5-turbo"


class GeneratedAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    session_id: str
    asset_type: str
    slot_index: int
    shot_no: int | None = None
    scene_title: str = ""
    provider: str = ""
    model_name: str = ""
    status: str = "completed"
    prompt_used: str = ""
    external_task_id: str | None = None
    source_image_asset_id: str | None = None
    mime_type: str = "image/jpeg"
    file_url: str = ""
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class StudioStateOut(BaseModel):
    video_id: str
    session_id: str
    product_name: str
    has_product_reference: bool
    product_reference_preview: str | None = None
    default_image_provider: Literal["gemini", "openai"] = "gemini"
    gemini_image_configured: bool = False
    openai_image_configured: bool = False
    kling_configured: bool = False
    ffmpeg_available: bool = False
    assets: list[GeneratedAssetOut] = Field(default_factory=list)


class GenerateImageRequest(BaseModel):
    slot_index: int = 0
    shot_no: int | None = None
    scene_title: str = ""
    prompt: str
    provider: Literal["gemini", "openai"] | None = None
    model_override: str = ""
    aspect_ratio: str = "9:16"
    use_character_ref: bool = True


class GenerateAllImagesRequest(BaseModel):
    provider: Literal["gemini", "openai"] | None = None
    model_override: str = ""
    only_missing: bool = True
    include_real_shoot_shots: bool = True
    include_poster: bool = True
    use_character_ref: bool = True


class RevisePlanRequest(BaseModel):
    feedback: str


class LockPlanRequest(BaseModel):
    locked: bool = True


class GenerateVideoClipRequest(BaseModel):
    slot_index: int = 1
    shot_no: int = 1
    scene_title: str = ""
    source_image_asset_id: str
    prompt: str
    negative_prompt: str = ""
    duration_sec: int = 5
    model_override: str = ""
    enable_sound: bool = False


class GenerateAllVideosRequest(BaseModel):
    only_missing: bool = True
    duration_sec: int = 5
    include_real_shoot_shots: bool = True
    model_override: str = ""
    enable_sound: bool = False


class StitchFinalVideoRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    include_images_as_motion: bool = True
    image_clip_duration: float = 3.5
    enable_voiceover: bool = False
    voiceover_text: str = ""
    voiceover_voice: str = "zh-CN-YunxiNeural"
    bgm_mode: Literal["none", "ambient_chill", "upbeat_pulse", "custom"] = "none"
    bgm_asset_id: str = ""
    bgm_volume: float = 0.20
