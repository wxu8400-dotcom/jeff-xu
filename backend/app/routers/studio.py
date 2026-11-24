from __future__ import annotations

import asyncio
import base64
import logging
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, defer

from ..auth import require_auth
from ..config import get_settings
from ..database import get_db, get_session_factory
from ..models import GeneratedAsset, ScanSession, VideoRecord
from ..schemas import (
    GenerateAllImagesRequest,
    GenerateAllVideosRequest,
    GenerateImageRequest,
    GenerateVideoClipRequest,
    GeneratedAssetOut,
    StitchFinalVideoRequest,
    StudioStateOut,
)
from ..services.audio_engine import (
    generate_builtin_bgm_mp3,
    generate_tts_voiceover,
    mix_audio_into_mp4,
)
from ..services.media_generator import (
    decode_data_url_image,
    generate_kling_video_clip,
    generate_product_image,
)
from ..services.product_parser import _resize_jpeg
from ..services.video_processor import is_ffmpeg_available
from ..services.video_stitcher import stitch_media_items_to_mp4

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/studio",
    tags=["studio"],
    dependencies=[Depends(require_auth)],
)

_studio_tasks: set[asyncio.Task] = set()


def _track_task(task: asyncio.Task) -> None:
    _studio_tasks.add(task)
    task.add_done_callback(_studio_tasks.discard)


def _serialize_asset(asset: GeneratedAsset) -> GeneratedAssetOut:
    return GeneratedAssetOut(
        id=asset.id,
        video_id=asset.video_id,
        session_id=asset.session_id,
        asset_type=asset.asset_type,
        slot_index=asset.slot_index,
        shot_no=asset.shot_no,
        scene_title=asset.scene_title,
        provider=asset.provider,
        model_name=asset.model_name,
        status=asset.status,
        prompt_used=asset.prompt_used,
        external_task_id=asset.external_task_id,
        source_image_asset_id=asset.source_image_asset_id,
        mime_type=asset.mime_type,
        file_url=f"/api/studio/assets/{asset.id}/file",
        duration_sec=asset.duration_sec,
        width=asset.width,
        height=asset.height,
        error_message=asset.error_message,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def _extract_product_ref_images(session: ScanSession) -> tuple[list[tuple[bytes, str]], str | None]:
    refs: list[tuple[bytes, str]] = []
    preview: str | None = None
    for asset in session.product_assets or []:
        if not isinstance(asset, dict):
            continue
        raw_url = asset.get("reference_image") or asset.get("thumbnail")
        if raw_url and not preview:
            preview = str(raw_url)
        decoded = decode_data_url_image(raw_url)
        if decoded:
            refs.append(decoded)
            if len(refs) >= 2:
                break
    return refs, preview


def _get_video_and_session(db: Session, video_id: str) -> tuple[VideoRecord, ScanSession]:
    video = db.get(VideoRecord, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频记录不存在")
    session = db.get(ScanSession, video.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="所属扫描任务不存在")
    return video, session


def _infer_shot_production_mode(shot: dict[str, Any], is_ai_video: bool) -> str:
    raw = str(shot.get("production_mode") or "").strip().lower()
    if raw in ("ai", "real_shoot"):
        return raw
    if is_ai_video:
        return "ai"
    text = (
        str(shot.get("adapted_visual_for_product") or "")
        + " "
        + str(shot.get("original_visual") or "")
    ).lower()
    if any(k in text for k in ("手持", "握持", "安装", "手部", "开箱", "实测", "hand", "unbox")):
        return "real_shoot"
    return "ai"


def _build_image_slot_blueprints(
    video: VideoRecord,
    session: ScanSession,
    *,
    include_poster: bool = True,
    include_real_shoot_shots: bool = True,
) -> list[dict[str, Any]]:
    """Build deterministic generation slots for poster (slot 0) + every storyboard shot (slots 1..N)."""
    analysis = video.analysis_json or {}
    dna = session.product_dna or {}
    pname = str(dna.get("product_name") or session.product_name or "the product")
    pform = str(dna.get("physical_form") or "")
    img_prompts = list(analysis.get("chatgpt_images_prompts") or [])
    storyboard = list(analysis.get("storyboard") or [])

    slots: list[dict[str, Any]] = []

    # Slot 0: Hero Poster
    if include_poster and img_prompts:
        p0 = img_prompts[0]
        slots.append(
            {
                "slot_index": 0,
                "shot_no": None,
                "scene_title": str(p0.get("scene_title") or "爆款主视觉海报（封面图）"),
                "prompt": str(p0.get("prompt_en") or p0.get("prompt_cn") or ""),
                "aspect_ratio": str(p0.get("aspect_ratio") or "9:16"),
                "production_mode": "ai",
            }
        )

    # Slots 1..N: Every storyboard shot
    for idx, shot in enumerate(storyboard, start=1):
        shot_no = int(shot.get("shot_no") or idx)
        mode = _infer_shot_production_mode(shot, bool(video.is_ai_generated))
        if not include_real_shoot_shots and mode == "real_shoot":
            continue

        # Match prompt from chatgpt_images_prompts[idx] if available, else synthesize high-fidelity prompt
        matched_prompt = img_prompts[idx] if idx < len(img_prompts) else None
        if matched_prompt and (matched_prompt.get("prompt_en") or matched_prompt.get("prompt_cn")):
            prompt_text = str(matched_prompt.get("prompt_en") or matched_prompt.get("prompt_cn"))
            scene_title = str(matched_prompt.get("scene_title") or f"分镜 {shot_no} 首帧图")
            aspect = str(matched_prompt.get("aspect_ratio") or "9:16")
        else:
            visual = str(shot.get("adapted_visual_for_product") or shot.get("original_visual") or "")
            shot_size = str(shot.get("shot_size") or "商业特写")
            prompt_text = (
                f"Keep the exact product from the uploaded reference image ({pname}, {pform}, "
                f"preserving its exact shape, color, material, and details 100% unchanged). "
                f"Commercial storyboard keyframe for Shot {shot_no} ({shot_size}): {visual}. "
                f"Photorealistic commercial advertising lighting, crisp focus, high-end cinema look, "
                f"vertical 9:16 composition, no watermark, no random text."
            )
            scene_title = f"分镜 {shot_no} 首帧图（{shot_size}）"
            aspect = "9:16"

        slots.append(
            {
                "slot_index": shot_no,
                "shot_no": shot_no,
                "scene_title": scene_title,
                "prompt": prompt_text,
                "aspect_ratio": aspect,
                "production_mode": mode,
            }
        )

    return slots


def _build_kling_prompt_for_shot(
    video: VideoRecord,
    session: ScanSession,
    shot_no: int,
) -> tuple[str, str, str]:
    analysis = video.analysis_json or {}
    dna = session.product_dna or {}
    pname = str(dna.get("product_name") or session.product_name or "产品")
    for kp in analysis.get("kling_prompts") or []:
        if int(kp.get("shot_no") or 0) == shot_no:
            return (
                str(kp.get("scene_title") or f"分镜 {shot_no} AI 视频"),
                str(kp.get("prompt_en") or kp.get("prompt_cn") or ""),
                str(kp.get("negative_prompt") or "blurry, distorted, morphing, watermark, text"),
            )
    for shot in analysis.get("storyboard") or []:
        if int(shot.get("shot_no") or 0) == shot_no:
            cam = str(shot.get("camera_movement") or "smooth slow push-in")
            vis = str(shot.get("adapted_visual_for_product") or "")
            return (
                f"分镜 {shot_no} AI 视频",
                f"Keep the exact {pname} completely solid and undistorted. {vis}. Camera movement: {cam}. Smooth natural cinematic motion, realistic commercial lighting, ultra-crisp 4K quality.",
                "变形, 模糊, 产品扭曲, 闪烁, 穿模, 多余手指, 水印, 杂乱文字",
            )
    return (
        f"分镜 {shot_no} AI 视频",
        f"Smooth cinematic commercial camera push-in showcasing {pname} with realistic lighting and zero distortion.",
        "变形, 模糊, 闪烁, 水印, 杂乱文字",
    )


async def _run_image_job(
    *,
    asset_id: str,
    prompt: str,
    ref_images: list[tuple[bytes, str]],
    provider: str,
    model_override: str = "",
    aspect_ratio: str,
    scene_title: str,
    product_name: str,
) -> None:
    cfg = get_settings()
    factory = get_session_factory()
    try:
        res = await generate_product_image(
            prompt=prompt,
            ref_images=ref_images,
            provider=provider,
            model_override=model_override,
            aspect_ratio=aspect_ratio,
            scene_title=scene_title,
            product_name=product_name,
            settings=cfg,
        )
        db = factory()
        try:
            row = db.get(GeneratedAsset, asset_id)
            if row:
                row.status = "completed"
                row.provider = res.provider
                row.model_name = res.model_name
                row.mime_type = res.mime_type
                row.file_data = res.image_bytes
                row.width = res.width
                row.height = res.height
                row.error_message = None
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.exception("Image generation failed for asset %s: %s", asset_id, exc)
        db = factory()
        try:
            row = db.get(GeneratedAsset, asset_id)
            if row:
                row.status = "failed"
                row.error_message = str(exc)
                db.commit()
        finally:
            db.close()


async def _run_kling_video_job(
    *,
    asset_id: str,
    image_bytes: bytes,
    prompt: str,
    negative_prompt: str,
    duration_sec: int,
    model_override: str = "",
    enable_sound: bool = False,
) -> None:
    cfg = get_settings()
    factory = get_session_factory()
    try:
        res = await generate_kling_video_clip(
            image_bytes=image_bytes,
            prompt=prompt,
            negative_prompt=negative_prompt,
            duration_sec=duration_sec,
            model_override=model_override,
            enable_sound=enable_sound,
            settings=cfg,
        )
        db = factory()
        try:
            row = db.get(GeneratedAsset, asset_id)
            if row:
                row.status = "completed"
                row.provider = res.provider
                row.model_name = res.model_name
                row.mime_type = res.mime_type
                row.file_data = res.video_bytes
                row.media_url = res.media_url
                row.external_task_id = res.external_task_id
                row.duration_sec = res.duration_sec
                row.error_message = None
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.exception("Kling video generation failed for asset %s: %s", asset_id, exc)
        db = factory()
        try:
            row = db.get(GeneratedAsset, asset_id)
            if row:
                row.status = "failed"
                row.error_message = str(exc)
                db.commit()
        finally:
            db.close()


@router.get("/videos/{video_id}/assets", response_model=StudioStateOut)
def get_studio_state(
    video_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> StudioStateOut:
    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    refs, preview = _extract_product_ref_images(session)

    stmt = (
        select(GeneratedAsset)
        .options(defer(GeneratedAsset.file_data))
        .where(GeneratedAsset.video_id == video.id)
        .order_by(desc(GeneratedAsset.created_at))
    )
    rows = list(db.scalars(stmt).all())

    return StudioStateOut(
        video_id=video.id,
        session_id=session.id,
        product_name=session.product_name,
        has_product_reference=bool(refs),
        product_reference_preview=preview,
        default_image_provider=cfg.default_image_provider,
        gemini_image_configured=cfg.gemini_image_configured(),
        openai_image_configured=cfg.openai_image_configured(),
        kling_configured=cfg.kling_configured(),
        ffmpeg_available=is_ffmpeg_available(),
        assets=[_serialize_asset(r) for r in rows],
    )


@router.post("/videos/{video_id}/product-reference")
async def upload_product_reference_image(
    video_id: str,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Allow updating/adding a crisp product reference image directly inside the Studio."""
    video, session = _get_video_and_session(db, video_id)
    raw = await file.read()
    if not raw or len(raw) < 200:
        raise HTTPException(status_code=400, detail="请上传有效的商品图片文件")
    try:
        ref_bytes = _resize_jpeg(raw, max_side=1024, quality=86)
        thumb_bytes = _resize_jpeg(raw, max_side=280, quality=70)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"图片解析失败：{exc}") from exc

    ref_url = f"data:image/jpeg;base64,{base64.b64encode(ref_bytes).decode('ascii')}"
    thumb_url = f"data:image/jpeg;base64,{base64.b64encode(thumb_bytes).decode('ascii')}"
    existing = list(session.product_assets or [])
    existing.insert(
        0,
        {
            "filename": file.filename or "product_reference.jpg",
            "kind": "image",
            "size_kb": round(len(raw) / 1024, 1),
            "thumbnail": thumb_url,
            "reference_image": ref_url,
        },
    )
    session.product_assets = existing
    db.commit()
    return {"ok": True, "video_id": video.id, "product_reference_preview": ref_url}


@router.post("/videos/{video_id}/generate-image", response_model=GeneratedAssetOut)
async def generate_single_image(
    video_id: str,
    body: GenerateImageRequest,
    db: Annotated[Session, Depends(get_db)],
) -> GeneratedAssetOut:
    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    provider = body.provider or cfg.default_image_provider
    if provider == "gemini" and not cfg.gemini_image_configured():
        raise HTTPException(status_code=400, detail="尚未配置 GEMINI_API_KEY")
    if provider == "openai" and not cfg.openai_image_configured():
        raise HTTPException(
            status_code=400,
            detail="尚未配置 OPENAI_API_KEY / OPENAI_IMAGE_API_KEY，请在 Render 环境变量中配置或切换为 Gemini 生图",
        )

    chosen_model = (
        body.model_override.strip()
        or (cfg.gemini_image_model if provider == "gemini" else cfg.openai_image_model)
    )
    refs, _ = _extract_product_ref_images(session)
    asset = GeneratedAsset(
        video_id=video.id,
        session_id=session.id,
        asset_type="image",
        slot_index=body.slot_index,
        shot_no=body.shot_no,
        scene_title=body.scene_title or (f"分镜 {body.shot_no}" if body.shot_no else "主视觉海报"),
        provider=provider,
        model_name=chosen_model,
        status="processing",
        prompt_used=body.prompt,
        mime_type="image/jpeg",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    # Single image runs directly (or fast in mock) so user sees immediate result on click
    await _run_image_job(
        asset_id=asset.id,
        prompt=body.prompt,
        ref_images=refs,
        provider=provider,
        model_override=body.model_override.strip(),
        aspect_ratio=body.aspect_ratio or "9:16",
        scene_title=asset.scene_title,
        product_name=session.product_name,
    )
    db.refresh(asset)
    if asset.status == "failed":
        raise HTTPException(status_code=502, detail=asset.error_message or "生图失败")
    return _serialize_asset(asset)


@router.post("/videos/{video_id}/generate-all-images", response_model=list[GeneratedAssetOut])
async def generate_all_images(
    video_id: str,
    body: GenerateAllImagesRequest,
    db: Annotated[Session, Depends(get_db)],
) -> list[GeneratedAssetOut]:
    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    provider = body.provider or cfg.default_image_provider
    if provider == "gemini" and not cfg.gemini_image_configured():
        raise HTTPException(status_code=400, detail="尚未配置 GEMINI_API_KEY")
    if provider == "openai" and not cfg.openai_image_configured():
        raise HTTPException(
            status_code=400,
            detail="尚未配置 OPENAI_API_KEY / OPENAI_IMAGE_API_KEY，请在 Render 环境变量中配置或切换为 Gemini 生图",
        )

    refs, _ = _extract_product_ref_images(session)
    blueprints = _build_image_slot_blueprints(
        video,
        session,
        include_poster=body.include_poster,
        include_real_shoot_shots=body.include_real_shoot_shots,
    )

    existing_slots: set[int] = set()
    if body.only_missing:
        stmt = (
            select(GeneratedAsset)
            .options(defer(GeneratedAsset.file_data))
            .where(
                GeneratedAsset.video_id == video.id,
                GeneratedAsset.asset_type == "image",
                GeneratedAsset.status.in_(["completed", "processing"]),
            )
        )
        for row in db.scalars(stmt).all():
            existing_slots.add(row.slot_index)

    chosen_model = (
        body.model_override.strip()
        or (cfg.gemini_image_model if provider == "gemini" else cfg.openai_image_model)
    )
    created: list[tuple[GeneratedAsset, dict[str, Any]]] = []
    for bp in blueprints:
        if body.only_missing and bp["slot_index"] in existing_slots:
            continue
        asset = GeneratedAsset(
            video_id=video.id,
            session_id=session.id,
            asset_type="image",
            slot_index=bp["slot_index"],
            shot_no=bp["shot_no"],
            scene_title=bp["scene_title"],
            provider=provider,
            model_name=chosen_model,
            status="processing",
            prompt_used=bp["prompt"],
            mime_type="image/jpeg",
        )
        db.add(asset)
        created.append((asset, bp))

    db.commit()
    for asset, _ in created:
        db.refresh(asset)

    async def _batch_runner(jobs: list[tuple[str, dict[str, Any]]]) -> None:
        for aid, bp in jobs:
            await _run_image_job(
                asset_id=aid,
                prompt=bp["prompt"],
                ref_images=refs,
                provider=provider,
                model_override=body.model_override.strip(),
                aspect_ratio=bp["aspect_ratio"],
                scene_title=bp["scene_title"],
                product_name=session.product_name,
            )

    if created:
        job_specs = [(a.id, bp) for a, bp in created]
        task = asyncio.create_task(_batch_runner(job_specs))
        _track_task(task)

    return [_serialize_asset(a) for a, _ in created]


@router.post("/videos/{video_id}/generate-video-clip", response_model=GeneratedAssetOut)
async def generate_single_video_clip(
    video_id: str,
    body: GenerateVideoClipRequest,
    db: Annotated[Session, Depends(get_db)],
) -> GeneratedAssetOut:
    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    if not cfg.kling_configured():
        raise HTTPException(
            status_code=400,
            detail="尚未配置可灵 Kling API Key（请在 Render 环境变量配置 KLING_API_KEY，或官方 KLING_ACCESS_KEY + KLING_SECRET_KEY）。提示：即使暂不配置可灵，也可直接点「一键合并成片」将生成好的分镜图自动转为推镜动态成片！",
        )

    src_img = db.get(GeneratedAsset, body.source_image_asset_id)
    if not src_img or src_img.video_id != video.id or not src_img.file_data:
        raise HTTPException(status_code=400, detail="请先为该分镜生成首帧商品图，再调用可灵图生视频")

    chosen_kling_model = body.model_override.strip() or cfg.kling_model_name
    asset = GeneratedAsset(
        video_id=video.id,
        session_id=session.id,
        asset_type="video_clip",
        slot_index=body.slot_index,
        shot_no=body.shot_no,
        scene_title=body.scene_title or f"分镜 {body.shot_no} 可灵 AI 视频",
        provider="kling",
        model_name=chosen_kling_model,
        status="processing",
        prompt_used=body.prompt,
        source_image_asset_id=src_img.id,
        mime_type="video/mp4",
        duration_sec=float(body.duration_sec),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    task = asyncio.create_task(
        _run_kling_video_job(
            asset_id=asset.id,
            image_bytes=bytes(src_img.file_data),
            prompt=body.prompt,
            negative_prompt=body.negative_prompt,
            duration_sec=body.duration_sec,
            model_override=body.model_override.strip(),
            enable_sound=body.enable_sound,
        )
    )
    _track_task(task)
    return _serialize_asset(asset)


@router.post("/videos/{video_id}/generate-all-videos", response_model=list[GeneratedAssetOut])
async def generate_all_video_clips(
    video_id: str,
    body: GenerateAllVideosRequest,
    db: Annotated[Session, Depends(get_db)],
) -> list[GeneratedAssetOut]:
    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    if not cfg.kling_configured():
        raise HTTPException(
            status_code=400,
            detail="尚未配置可灵 Kling API Key（KLING_API_KEY 或 KLING_ACCESS_KEY + KLING_SECRET_KEY）",
        )

    stmt = (
        select(GeneratedAsset)
        .where(GeneratedAsset.video_id == video.id)
        .order_by(desc(GeneratedAsset.created_at))
    )
    all_assets = list(db.scalars(stmt).all())

    # Latest completed image per storyboard shot_no (>= 1)
    latest_img_by_shot: dict[int, GeneratedAsset] = {}
    existing_vid_shots: set[int] = set()
    for row in all_assets:
        if row.asset_type == "image" and row.status == "completed" and row.shot_no and row.file_data:
            latest_img_by_shot.setdefault(row.shot_no, row)
        if row.asset_type in ("video_clip", "uploaded_clip") and row.status in ("completed", "processing") and row.shot_no:
            existing_vid_shots.add(row.shot_no)

    storyboard = list((video.analysis_json or {}).get("storyboard") or [])
    created_jobs: list[tuple[GeneratedAsset, bytes, str, str]] = []

    for idx, shot in enumerate(storyboard, start=1):
        shot_no = int(shot.get("shot_no") or idx)
        mode = _infer_shot_production_mode(shot, bool(video.is_ai_generated))
        if not body.include_real_shoot_shots and mode == "real_shoot":
            continue
        if body.only_missing and shot_no in existing_vid_shots:
            continue
        img_row = latest_img_by_shot.get(shot_no)
        if not img_row or not img_row.file_data:
            continue
        title, k_prompt, k_neg = _build_kling_prompt_for_shot(video, session, shot_no)
        chosen_kling_model = body.model_override.strip() or cfg.kling_model_name
        asset = GeneratedAsset(
            video_id=video.id,
            session_id=session.id,
            asset_type="video_clip",
            slot_index=shot_no,
            shot_no=shot_no,
            scene_title=title,
            provider="kling",
            model_name=chosen_kling_model,
            status="processing",
            prompt_used=k_prompt,
            source_image_asset_id=img_row.id,
            mime_type="video/mp4",
            duration_sec=float(body.duration_sec),
        )
        db.add(asset)
        created_jobs.append((asset, bytes(img_row.file_data), k_prompt, k_neg))

    if not created_jobs:
        raise HTTPException(
            status_code=400,
            detail="请先点击「一键生成全部分镜商品图」生成首帧图，然后再一键生成可灵视频（或所有分镜已生成完毕）",
        )

    db.commit()
    for asset, _, _, _ in created_jobs:
        db.refresh(asset)

    async def _batch_kling_runner(jobs: list[tuple[str, bytes, str, str]]) -> None:
        for aid, img_bytes, pr, neg in jobs:
            await _run_kling_video_job(
                asset_id=aid,
                image_bytes=img_bytes,
                prompt=pr,
                negative_prompt=neg,
                duration_sec=body.duration_sec,
                model_override=body.model_override.strip(),
                enable_sound=body.enable_sound,
            )

    task = asyncio.create_task(
        _batch_kling_runner([(a.id, b, p, n) for a, b, p, n in created_jobs])
    )
    _track_task(task)
    return [_serialize_asset(a) for a, _, _, _ in created_jobs]


@router.post("/videos/{video_id}/upload-real-clip", response_model=GeneratedAssetOut)
async def upload_real_shoot_clip(
    video_id: str,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    shot_no: int = Form(...),
    scene_title: str = Form(default=""),
) -> GeneratedAssetOut:
    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    data = await file.read()
    max_bytes = min(cfg.max_upload_mb, 40) * 1024 * 1024
    if not data or len(data) < 500:
        raise HTTPException(status_code=400, detail="请上传有效的手机实拍视频文件（MP4/MOV/WebM）")
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="单个实拍片段请控制在 40MB 以内",
        )

    asset = GeneratedAsset(
        video_id=video.id,
        session_id=session.id,
        asset_type="uploaded_clip",
        slot_index=shot_no,
        shot_no=shot_no,
        scene_title=scene_title.strip() or f"分镜 {shot_no} 手机实拍片段",
        provider="user_upload",
        model_name=file.filename or "real_shoot.mp4",
        status="completed",
        prompt_used="",
        mime_type=file.content_type or "video/mp4",
        file_data=data,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_asset(asset)


@router.post("/videos/{video_id}/upload-bgm", response_model=GeneratedAssetOut)
async def upload_custom_bgm(
    video_id: str,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
) -> GeneratedAssetOut:
    video, session = _get_video_and_session(db, video_id)
    data = await file.read()
    if not data or len(data) < 500:
        raise HTTPException(status_code=400, detail="请上传有效的音频文件（MP3 / M4A / WAV）")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="BGM 音频文件请控制在 15MB 以内",
        )
    asset = GeneratedAsset(
        video_id=video.id,
        session_id=session.id,
        asset_type="bgm_audio",
        slot_index=-2,
        shot_no=None,
        scene_title=file.filename or "自定义 BGM.mp3",
        provider="user_upload",
        model_name=file.filename or "bgm.mp3",
        status="completed",
        prompt_used="",
        mime_type=file.content_type or "audio/mpeg",
        file_data=data,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_asset(asset)


@router.post("/videos/{video_id}/stitch-final", response_model=GeneratedAssetOut)
async def stitch_final_video(
    video_id: str,
    body: StitchFinalVideoRequest,
    db: Annotated[Session, Depends(get_db)],
) -> GeneratedAssetOut:
    """Stitch all ready clips in storyboard order into one 9:16 vertical MP4,
    optionally mixing 100% free AI voiceover (edge-tts) and royalty-free/custom BGM."""
    if not is_ffmpeg_available():
        raise HTTPException(status_code=400, detail="当前环境未检测到 FFmpeg，无法合成成片")

    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    stmt = (
        select(GeneratedAsset)
        .where(
            GeneratedAsset.video_id == video.id,
            GeneratedAsset.status == "completed",
            GeneratedAsset.asset_type.in_(["video_clip", "uploaded_clip", "image", "bgm_audio"]),
        )
        .order_by(desc(GeneratedAsset.created_at))
    )
    completed = list(db.scalars(stmt).all())
    by_id = {r.id: r for r in completed}

    ordered_media: list[tuple[str, bytes, float]] = []
    used_labels: list[str] = []

    if body.asset_ids:
        for aid in body.asset_ids:
            row = by_id.get(aid)
            if not row or not row.file_data:
                continue
            if row.asset_type in ("video_clip", "uploaded_clip"):
                ordered_media.append(("video", bytes(row.file_data), row.duration_sec or 5.0))
                used_labels.append(row.scene_title or f"镜头{row.shot_no}")
            elif row.asset_type == "image" and body.include_images_as_motion:
                ordered_media.append(("image", bytes(row.file_data), body.image_clip_duration))
                used_labels.append(row.scene_title or f"镜头{row.shot_no}")
    else:
        latest_upload: dict[int, GeneratedAsset] = {}
        latest_ai_vid: dict[int, GeneratedAsset] = {}
        latest_img: dict[int, GeneratedAsset] = {}
        for row in completed:
            if not row.file_data or not row.shot_no or row.shot_no < 1:
                continue
            if row.asset_type == "uploaded_clip":
                latest_upload.setdefault(row.shot_no, row)
            elif row.asset_type == "video_clip":
                latest_ai_vid.setdefault(row.shot_no, row)
            elif row.asset_type == "image":
                latest_img.setdefault(row.shot_no, row)

        shot_nos = sorted(
            set(latest_upload.keys())
            | set(latest_ai_vid.keys())
            | (set(latest_img.keys()) if body.include_images_as_motion else set())
        )
        for sno in shot_nos:
            if sno in latest_upload:
                r = latest_upload[sno]
                ordered_media.append(("video", bytes(r.file_data or b""), r.duration_sec or 5.0))
                used_labels.append(f"分镜{sno}(实拍)")
            elif sno in latest_ai_vid:
                r = latest_ai_vid[sno]
                ordered_media.append(("video", bytes(r.file_data or b""), r.duration_sec or 5.0))
                used_labels.append(f"分镜{sno}(可灵AI)")
            elif body.include_images_as_motion and sno in latest_img:
                r = latest_img[sno]
                ordered_media.append(("image", bytes(r.file_data or b""), body.image_clip_duration))
                used_labels.append(f"分镜{sno}(AI图转动态)")

    if not ordered_media:
        raise HTTPException(
            status_code=400,
            detail="暂无可拼接的分镜素材，请先点击「一键生成全部分镜商品图」或上传实拍视频片段",
        )

    try:
        final_bytes, total_dur = await asyncio.to_thread(
            stitch_media_items_to_mp4, ordered_media
        )
    except Exception as exc:
        logger.exception("FFmpeg stitch failed for video %s: %s", video_id, exc)
        raise HTTPException(status_code=500, detail=f"成片合成失败：{exc}") from exc

    # Optional Audio Mixing: 100% Free AI Voiceover + BGM
    voiceover_bytes: bytes | None = None
    bgm_bytes: bytes | None = None
    audio_tags: list[str] = []

    if body.enable_voiceover:
        copy = (video.analysis_json or {}).get("copywriting") or {}
        default_script = (
            copy.get("adapted_script_en")
            if body.voiceover_voice.startswith("en-")
            else copy.get("adapted_script_cn")
        ) or copy.get("adapted_script_cn") or copy.get("adapted_script_en") or ""
        vo_text = (body.voiceover_text or default_script).strip()
        if vo_text:
            try:
                voiceover_bytes = await generate_tts_voiceover(
                    vo_text,
                    voice=body.voiceover_voice,
                    mock_mode=cfg.enable_mock_mode,
                )
                audio_tags.append(f"AI配音({body.voiceover_voice})")
            except Exception as exc:
                logger.warning("Voiceover skipped due to error: %s", exc)
                raise HTTPException(status_code=502, detail=str(exc)) from exc

    if body.bgm_mode == "custom":
        bgm_row = by_id.get(body.bgm_asset_id) if body.bgm_asset_id else next(
            (r for r in completed if r.asset_type == "bgm_audio" and r.file_data), None
        )
        if bgm_row and bgm_row.file_data:
            bgm_bytes = bytes(bgm_row.file_data)
            audio_tags.append(f"BGM({bgm_row.scene_title[:16]})")
    elif body.bgm_mode in ("ambient_chill", "upbeat_pulse"):
        bgm_bytes = await asyncio.to_thread(
            generate_builtin_bgm_mp3, body.bgm_mode, total_dur
        )
        audio_tags.append(
            "内置商业轻节奏BGM" if body.bgm_mode == "upbeat_pulse" else "内置极简氛围BGM"
        )

    if voiceover_bytes or bgm_bytes:
        try:
            final_bytes = await asyncio.to_thread(
                mix_audio_into_mp4,
                final_bytes,
                voiceover_bytes=voiceover_bytes,
                bgm_bytes=bgm_bytes,
                keep_original_audio=True,
                bgm_volume=max(0.05, min(float(body.bgm_volume or 0.20), 0.80)),
            )
        except Exception as exc:
            logger.exception("Audio mix failed for video %s: %s", video_id, exc)
            raise HTTPException(status_code=500, detail=f"声音混音失败：{exc}") from exc

    summary_label = " + ".join(used_labels)
    if audio_tags:
        summary_label += " | 音频：" + " + ".join(audio_tags)

    final_asset = GeneratedAsset(
        video_id=video.id,
        session_id=session.id,
        asset_type="final_video",
        slot_index=-1,
        shot_no=None,
        scene_title=f"{session.product_name} · 复刻成片（{len(ordered_media)} 镜合集）",
        provider="ffmpeg_stitch",
        model_name="ffmpeg-9x16-h264",
        status="completed",
        prompt_used=summary_label,
        mime_type="video/mp4",
        file_data=final_bytes,
        duration_sec=total_dur,
        width=720,
        height=1280,
    )
    db.add(final_asset)
    db.commit()
    db.refresh(final_asset)
    return _serialize_asset(final_asset)


@router.delete("/assets/{asset_id}")
def delete_studio_asset(
    asset_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    stmt = (
        select(GeneratedAsset)
        .options(defer(GeneratedAsset.file_data))
        .where(GeneratedAsset.id == asset_id)
    )
    row = db.scalars(stmt).first()
    if not row:
        raise HTTPException(status_code=404, detail="素材不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


def _iter_bytes_chunks(buf: bytes, start: int, end: int, chunk_size: int = 262_144):
    pos = start
    while pos <= end:
        nxt = min(pos + chunk_size, end + 1)
        yield buf[pos:nxt]
        pos = nxt


@router.get("/assets/{asset_id}/file")
async def get_studio_asset_file(
    asset_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    download: bool = Query(default=False),
) -> Response:
    row = db.get(GeneratedAsset, asset_id)
    if not row:
        raise HTTPException(status_code=404, detail="素材不存在")

    data = bytes(row.file_data) if row.file_data else None
    if not data and row.media_url and row.media_url.startswith("http"):
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(row.media_url)
            if resp.status_code == 200:
                data = resp.content

    if not data:
        raise HTTPException(status_code=404, detail="素材文件尚未生成完毕")

    total_len = len(data)
    mime = row.mime_type or "application/octet-stream"
    ext = "mp4" if "video" in mime else ("mp3" if "audio" in mime else "jpg")
    safe_name = (row.scene_title or row.id).replace("/", "-").replace("\\", "-").replace('"', "")[:60]
    ascii_fallback = f"viral-radar-{row.id[:8]}.{ext}"

    base_headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
    }
    if download:
        encoded = quote(f"{safe_name}.{ext}")
        base_headers["Content-Disposition"] = (
            f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'
        )

    # Full HTTP Range (206 Partial Content) support — required by Safari/Chrome/iOS <video> & resumable downloads!
    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes=") and not download:
        spec = range_header[len("bytes=") :].split(",")[0].strip()
        start_s, _, end_s = spec.partition("-")
        try:
            if start_s == "":
                suffix_len = int(end_s)
                start = max(0, total_len - suffix_len)
                end = total_len - 1
            else:
                start = int(start_s)
                end = int(end_s) if end_s else total_len - 1
            if start < 0 or start >= total_len or end < start:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{total_len}"},
                )
            end = min(end, total_len - 1)
            chunk_len = end - start + 1
            headers_206 = {
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{total_len}",
                "Content-Length": str(chunk_len),
            }
            return StreamingResponse(
                _iter_bytes_chunks(data, start, end),
                status_code=206,
                media_type=mime,
                headers=headers_206,
            )
        except ValueError:
            pass

    headers_200 = {
        **base_headers,
        "Content-Length": str(total_len),
    }
    return StreamingResponse(
        _iter_bytes_chunks(data, 0, total_len - 1),
        status_code=200,
        media_type=mime,
        headers=headers_200,
    )
