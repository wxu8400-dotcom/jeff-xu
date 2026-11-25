from __future__ import annotations

import asyncio
import base64
import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
from sqlalchemy.orm.attributes import flag_modified

from ..auth import require_auth
from ..config import DATA_DIR, get_settings
from ..database import get_db, get_session_factory
from ..models import DirectorMemory, GeneratedAsset, ScanSession, VideoRecord
from ..schemas import (
    CreateDirectorMemoryRequest,
    DirectorMemoryOut,
    DirectorRevisionResponse,
    ExtractLastFrameRequest,
    GenerateAllImagesRequest,
    GenerateAllVideosRequest,
    GenerateImageRequest,
    GenerateVideoClipRequest,
    GeneratedAssetOut,
    LockPlanRequest,
    ProductDNA,
    PromptReviewResponse,
    RefineImageRequest,
    RefinedImagePromptResponse,
    RevisePlanRequest,
    StitchFinalVideoRequest,
    StudioStateOut,
    UpdateDirectorMemoryRequest,
)
from ..services.ai_client import UnifiedAIClient
from ..services.audio_engine import (
    align_source_audio_to_duration,
    generate_builtin_bgm_mp3,
    generate_kling_video_to_audio,
    generate_tts_voiceover,
    mix_audio_into_mp4,
)
from ..services.director_memory import (
    VALID_CATEGORIES,
    load_director_memory_block,
    save_learned_memories,
)
from ..services.media_generator import (
    decode_data_url_image,
    generate_kling_video_clip,
    generate_product_image,
)
from ..services.pack_parser import is_placeholder_text, parse_structured_production_pack
from ..services.product_parser import _resize_jpeg
from ..services.prompts import (
    build_director_revision_prompt,
    build_image_refinement_prompt,
    build_prompt_audit_and_revision_prompt,
    build_prompt_review_only_prompt,
)
from ..services.video_processor import (
    is_ffmpeg_available,
    load_source_audio_bytes,
    load_source_evidence_images,
)
from ..services.video_stitcher import (
    extract_last_frame_jpeg,
    parse_planned_shot_duration_sec,
    stitch_media_items_to_mp4,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/studio",
    tags=["studio"],
    dependencies=[Depends(require_auth)],
)

_studio_tasks: set[asyncio.Task] = set()
MEDIA_DIR = DATA_DIR / "media"
# Only mirror compact images (<= 450KB) into DB file_data; NEVER store multi-MB MP4s in Postgres
# so Neon Free Tier storage (512MB) and network transfer (5GB/mo) never get exhausted!
MAX_DB_BLOB_BYTES = 450_000


def _ext_for_mime(mime_type: str | None) -> str:
    m = (mime_type or "").lower()
    if "video" in m:
        return "mp4"
    if "audio" in m:
        return "mp3"
    return "jpg"


def _media_path(asset_id: str, mime_type: str | None) -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR / f"{asset_id}.{_ext_for_mime(mime_type)}"


def _save_asset_media(asset: GeneratedAsset, data: bytes) -> None:
    """Save media to local disk (fast zero-egress streaming) and mirror small images in DB."""
    path = _media_path(asset.id, asset.mime_type)
    path.write_bytes(data)
    if asset.asset_type == "image" and len(data) <= MAX_DB_BLOB_BYTES:
        asset.file_data = data
    else:
        asset.file_data = None


def _delete_local_media(asset_id: str) -> None:
    if not MEDIA_DIR.exists():
        return
    for ext in ("mp4", "jpg", "mp3", "png", "webp"):
        p = MEDIA_DIR / f"{asset_id}.{ext}"
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def _find_local_media_path(asset_id: str, mime_type: str | None) -> Path | None:
    p = _media_path(asset_id, mime_type)
    if p.exists() and p.stat().st_size > 0:
        return p
    return None


async def _load_asset_bytes(row: GeneratedAsset, db: Session) -> bytes | None:
    local = _find_local_media_path(row.id, row.mime_type)
    if local is not None:
        return local.read_bytes()
    # Fetch file_data lazily only if local file cache missed
    db_blob = db.execute(
        select(GeneratedAsset.file_data).where(GeneratedAsset.id == row.id)
    ).scalar_one_or_none()
    if db_blob:
        raw = bytes(db_blob)
        _media_path(row.id, row.mime_type).write_bytes(raw)
        return raw
    if row.media_url and row.media_url.startswith("http"):
        try:
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
                resp = await client.get(row.media_url)
                if resp.status_code == 200 and len(resp.content) > 200:
                    _media_path(row.id, row.mime_type).write_bytes(resp.content)
                    return resp.content
        except Exception as exc:
            logger.warning("Failed to fetch remote media_url for %s: %s", row.id, exc)
    return None


def _iter_file_chunks(path: Path, start: int, end: int, chunk_size: int = 262_144):
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


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


def _extract_product_ref_images(
    session: ScanSession,
) -> tuple[list[tuple[bytes, str]], str | None]:
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
            if len(refs) >= 5:
                break
    return refs, preview


def _extract_product_ref_previews(session: ScanSession) -> list[str]:
    previews: list[str] = []
    for asset in session.product_assets or []:
        if not isinstance(asset, dict):
            continue
        raw_url = asset.get("thumbnail") or asset.get("reference_image")
        if isinstance(raw_url, str) and raw_url.startswith("data:image/"):
            previews.append(raw_url)
            if len(previews) >= 5:
                break
    return previews


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
        p0_en = str(p0.get("prompt_en") or "")
        p0_cn = str(p0.get("prompt_cn") or "")
        p0_final = p0_cn if is_placeholder_text(p0_en) and p0_cn else (p0_en or p0_cn)
        slots.append(
            {
                "slot_index": 0,
                "shot_no": None,
                "scene_title": str(p0.get("scene_title") or "爆款主视觉海报（封面图）"),
                "prompt": p0_final,
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

        # Match prompt from chatgpt_images_prompts[idx] if available, rejecting any placeholder text
        matched_prompt = img_prompts[idx] if idx < len(img_prompts) else None
        raw_en = str((matched_prompt or {}).get("prompt_en") or "")
        raw_cn = str((matched_prompt or {}).get("prompt_cn") or "")
        if matched_prompt and (not is_placeholder_text(raw_en) or not is_placeholder_text(raw_cn)):
            prompt_text = raw_cn if is_placeholder_text(raw_en) and raw_cn else (raw_en or raw_cn)
            scene_title = str(matched_prompt.get("scene_title") or f"分镜 {shot_no} 首帧图")
            aspect = str(matched_prompt.get("aspect_ratio") or "9:16")
        else:
            visual = str(shot.get("adapted_visual_for_product") or shot.get("original_visual") or "")
            shot_size = str(shot.get("shot_size") or "商业镜头")
            action = str(shot.get("replication_action") or "insert_product").lower()
            if action == "keep_scene":
                prompt_text = (
                    f"Photorealistic vertical 9:16 cinematic frame for Shot {shot_no} ({shot_size}): {visual}. "
                    f"Natural cinema lighting, crisp focus, no watermark, no random text."
                )
            else:
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
                row.width = res.width
                row.height = res.height
                row.error_message = None
                _save_asset_media(row, res.image_bytes)
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
                row.media_url = res.media_url
                row.external_task_id = res.external_task_id
                row.duration_sec = res.duration_sec
                row.error_message = None
                _save_asset_media(row, res.video_bytes)
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


def _build_recommended_sfx_prompt(video: VideoRecord) -> str:
    analysis = video.analysis_json or {}
    cues: list[str] = []
    plan = analysis.get("director_plan") or {}
    eg = plan.get("editing_guidelines") or {}
    for tip in list(eg.get("audio_and_overlay_tips") or [])[:2]:
        s = str(tip or "").strip()
        if s and "Logo" not in s and "联系方式" not in s:
            cues.append(s)
    for shot in list(analysis.get("storyboard") or [])[:6]:
        if isinstance(shot, dict):
            sfx = str(shot.get("audio_sfx") or "").strip()
            if sfx and sfx not in cues:
                cues.append(sfx)
    if not cues:
        bgm = str((analysis.get("shooting_requirements") or {}).get("bgm_style") or "").strip()
        if bgm:
            cues.append(bgm)
    return "；".join(cues)[:190]


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

    has_src_audio = (MEDIA_DIR / f"source_audio_{video.id}.mp3").exists()

    return StudioStateOut(
        video_id=video.id,
        session_id=session.id,
        product_name=session.product_name,
        has_product_reference=bool(refs),
        product_reference_preview=preview,
        product_reference_previews=_extract_product_ref_previews(session),
        default_image_provider=cfg.default_image_provider,
        gemini_image_configured=cfg.gemini_image_configured(),
        openai_image_configured=cfg.openai_image_configured(),
        kling_configured=cfg.kling_configured(),
        ffmpeg_available=is_ffmpeg_available(),
        has_source_audio=has_src_audio,
        recommended_sfx_prompt=_build_recommended_sfx_prompt(video),
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


CN_TZ = timezone(timedelta(hours=8))


async def _find_character_reference_image(
    video: VideoRecord,
    db: Session,
    *,
    exclude_slot: int | None = None,
) -> tuple[bytes, str] | None:
    """Return the first completed generated image from an earlier person shot so
    subsequent person shots keep the exact same original AI character face & outfit."""
    analysis = video.analysis_json or {}
    person_slots = [
        int(s.get("shot_no") or idx)
        for idx, s in enumerate(analysis.get("storyboard") or [], start=1)
        if s.get("has_person") and int(s.get("shot_no") or idx) != exclude_slot
    ]
    if not person_slots:
        return None
    stmt = (
        select(GeneratedAsset)
        .options(defer(GeneratedAsset.file_data))
        .where(
            GeneratedAsset.video_id == video.id,
            GeneratedAsset.asset_type == "image",
            GeneratedAsset.status == "completed",
            GeneratedAsset.slot_index.in_(person_slots),
        )
        .order_by(GeneratedAsset.slot_index.asc(), desc(GeneratedAsset.created_at))
    )
    row = db.scalars(stmt).first()
    if not row:
        return None
    raw = await _load_asset_bytes(row, db)
    if raw:
        return raw, row.mime_type or "image/jpeg"
    return None


async def _prepare_shot_image_inputs(
    *,
    video: VideoRecord,
    session: ScanSession,
    db: Session,
    slot_index: int,
    shot_no: int | None,
    prompt: str,
    product_refs: list[tuple[bytes, str]],
    use_character_ref: bool = True,
) -> tuple[str, list[tuple[bytes, str]]]:
    """Build exact prompt + reference image list respecting 1:1 plot continuity:
    - Only attach product reference on Poster (slot 0) or shots where the product actually appears
      (replication_action != 'keep_scene'). Pure plot-setup shots stay faithful without forced product!
    - On shots with people (`has_person=True`), inject unified AI character profile and optionally
      attach an earlier generated character frame to lock face & outfit consistency across shots.
    """
    analysis = video.analysis_json or {}
    director_plan = analysis.get("director_plan") or {}
    char_en = str(director_plan.get("ai_character_profile_en") or "").strip()

    shot_obj: dict[str, Any] | None = None
    if shot_no is not None:
        for idx, s in enumerate(analysis.get("storyboard") or [], start=1):
            if int(s.get("shot_no") or idx) == shot_no:
                shot_obj = s
                break

    action = str((shot_obj or {}).get("replication_action") or "insert_product").lower()
    has_person = bool((shot_obj or {}).get("has_person", False))
    include_product = slot_index == 0 or action != "keep_scene"

    final_refs: list[tuple[bytes, str]] = []
    prompt_additions: list[str] = []

    if include_product and product_refs:
        # Attach up to 3 multi-angle product reference images so generated frames preserve
        # front/side/detail fidelity faithfully — while STRICTLY isolating the product from
        # any showroom/wall/curtain/plant background in the uploaded product photos.
        final_refs.extend(product_refs[:3])
        prompt_additions.append(
            "ISOLATE PRODUCT ONLY: Extract ONLY the target product itself from the attached product reference photo(s); "
            "COMPLETELY IGNORE and NEVER copy any walls, slatted panels, curtains, tables, plants, floors, or showroom background from the product photo."
        )

    if has_person:
        if char_en and char_en[:24].lower() not in prompt.lower():
            prompt_additions.append(
                f"Consistent original AI character (NOT copying any real person from the original video): {char_en}."
            )
        if use_character_ref:
            char_ref = await _find_character_reference_image(
                video, db, exclude_slot=slot_index
            )
            if char_ref:
                final_refs.append(char_ref)
                prompt_additions.append(
                    "CRITICAL CHARACTER CONSISTENCY: Keep the exact same AI character's face, hairstyle, age, and outfit from the attached character reference image."
                )

    final_prompt = prompt.strip()
    if prompt_additions:
        final_prompt = " ".join(prompt_additions) + "\n\n" + final_prompt
    return final_prompt, final_refs


def _serialize_memory(row: DirectorMemory) -> DirectorMemoryOut:
    return DirectorMemoryOut(
        id=row.id,
        category=row.category,
        product_scope=row.product_scope,
        rule_summary=row.rule_summary,
        example_snippet=row.example_snippet or "",
        source_video_title=row.source_video_title or "",
        confidence_hits=row.confidence_hits or 1,
        is_active=bool(row.is_active),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/memories", response_model=list[DirectorMemoryOut])
def list_director_memories(
    db: Annotated[Session, Depends(get_db)],
) -> list[DirectorMemoryOut]:
    rows = list(
        db.scalars(
            select(DirectorMemory)
            .order_by(
                desc(DirectorMemory.is_active),
                desc(DirectorMemory.confidence_hits),
                desc(DirectorMemory.updated_at),
            )
            .limit(100)
        ).all()
    )
    return [_serialize_memory(r) for r in rows]


@router.post("/memories", response_model=DirectorMemoryOut)
def create_director_memory(
    body: CreateDirectorMemoryRequest,
    db: Annotated[Session, Depends(get_db)],
) -> DirectorMemoryOut:
    summary = body.rule_summary.strip()
    if len(summary) < 4:
        raise HTTPException(status_code=400, detail="请填写至少 4 个字的导演偏好规则")
    cat = body.category if body.category in VALID_CATEGORIES else "product_replacement"
    row = DirectorMemory(
        category=cat,
        product_scope=(body.product_scope or "global").strip()[:80] or "global",
        rule_summary=summary,
        example_snippet=(body.example_snippet or "").strip()[:300],
        source_video_title="手动添加长期偏好",
        confidence_hits=1,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_memory(row)


@router.patch("/memories/{memory_id}", response_model=DirectorMemoryOut)
def update_director_memory(
    memory_id: str,
    body: UpdateDirectorMemoryRequest,
    db: Annotated[Session, Depends(get_db)],
) -> DirectorMemoryOut:
    row = db.get(DirectorMemory, memory_id)
    if not row:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    if body.rule_summary is not None and body.rule_summary.strip():
        row.rule_summary = body.rule_summary.strip()
    if body.category is not None and body.category in VALID_CATEGORIES:
        row.category = body.category
    if body.product_scope is not None:
        row.product_scope = body.product_scope.strip()[:80] or "global"
    if body.example_snippet is not None:
        row.example_snippet = body.example_snippet.strip()[:300]
    if body.is_active is not None:
        row.is_active = body.is_active
    db.commit()
    db.refresh(row)
    return _serialize_memory(row)


@router.delete("/memories/{memory_id}")
def delete_director_memory(
    memory_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    row = db.get(DirectorMemory, memory_id)
    if not row:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


_NO_PRODUCT_MARKERS = (
    "没有成品",
    "无成品",
    "没有可见沙发",
    "没有可见产品",
    "不出现产品",
    "不出现成品",
    "没有产品",
    "no finished product",
    "no finished sofa",
    "without the finished product",
    "before the product appears",
)


def _extract_prompt_doc_bytes_text(filename: str, raw: bytes) -> str:
    """Extract plain text from uploaded .txt / .md / .docx production pack files."""
    if not raw:
        return ""
    lower = (filename or "").lower()
    if lower.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
            paragraphs: list[str] = []
            for p in root.iter():
                if p.tag.endswith("}p"):
                    texts = [
                        t.text
                        for t in p.iter()
                        if t.tag.endswith("}t") and t.text
                    ]
                    line = "".join(texts).strip()
                    if line:
                        paragraphs.append(line)
            return "\n".join(paragraphs).strip()
        except Exception as exc:
            logger.warning("Failed to parse .docx prompt file %s: %s", filename, exc)
            return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore").strip()


def _apply_no_product_shot_guard(
    storyboard_list: list[dict[str, Any]],
    image_prompts_list: list[dict[str, Any]],
) -> None:
    """Deterministic anti-leak guard: if a shot explicitly states '没有成品沙发 / 没有可见产品'
    (e.g. raw leather / volcano before transformation), force replication_action='keep_scene'
    so the finished product photo is NOT attached when generating that keyframe."""
    for idx, shot in enumerate(storyboard_list):
        if not isinstance(shot, dict):
            continue
        img_p = (
            image_prompts_list[idx + 1]
            if idx + 1 < len(image_prompts_list) and isinstance(image_prompts_list[idx + 1], dict)
            else {}
        )
        combined = " ".join(
            str(x or "")
            for x in (
                shot.get("adapted_visual_for_product"),
                shot.get("original_visual"),
                img_p.get("prompt_cn"),
                img_p.get("prompt_en"),
            )
        ).lower()
        if any(marker in combined for marker in _NO_PRODUCT_MARKERS):
            shot["replication_action"] = "keep_scene"


def _collect_source_evidence_for_audit(
    video: VideoRecord,
    curr_plan: dict[str, Any],
) -> tuple[list[tuple[bytes, str]], list[float]]:
    """Load persisted timestamped Contact Sheet + HD keyframes from disk; if unavailable
    (e.g. legacy video record), fall back to decoding saved keyframe_previews."""
    ev_images, ev_timestamps = load_source_evidence_images(
        video.id, MEDIA_DIR, max_key_frames=6
    )
    if ev_images:
        return ev_images, ev_timestamps

    fallback_imgs: list[tuple[bytes, str]] = []
    for raw_url in list(curr_plan.get("keyframe_previews") or [])[:6]:
        decoded = decode_data_url_image(raw_url)
        if decoded:
            fallback_imgs.append(decoded)
    fallback_ts = [float(t) for t in (curr_plan.get("keyframe_timestamps") or [])]
    return fallback_imgs, fallback_ts


def _merge_revision_into_analysis(
    *,
    curr_analysis: dict[str, Any],
    curr_plan: dict[str, Any],
    rev_res: DirectorRevisionResponse,
    user_summary_text: str,
    new_history: list[dict[str, Any]],
) -> dict[str, Any]:
    if rev_res.analysis is not None:
        updated_dict = rev_res.analysis.model_dump()
    else:
        updated_dict = dict(curr_analysis)

    updated_plan = dict(updated_dict.get("director_plan") or curr_plan)
    if curr_plan.get("original_video_prompt_cn"):
        updated_plan["original_video_prompt_cn"] = curr_plan["original_video_prompt_cn"]
    if curr_plan.get("original_video_prompt_en"):
        updated_plan["original_video_prompt_en"] = curr_plan["original_video_prompt_en"]
    if curr_plan.get("keyframe_previews"):
        updated_plan["keyframe_previews"] = curr_plan["keyframe_previews"]
    if curr_plan.get("keyframe_timestamps"):
        updated_plan["keyframe_timestamps"] = curr_plan["keyframe_timestamps"]

    if rev_res.prompt_audit_report is not None:
        updated_plan["prompt_audit_report"] = rev_res.prompt_audit_report.model_dump()
    if rev_res.editing_guidelines is not None:
        updated_plan["editing_guidelines"] = rev_res.editing_guidelines.model_dump()
    if rev_res.global_reference_prompt_cn.strip():
        updated_plan["global_reference_prompt_cn"] = rev_res.global_reference_prompt_cn.strip()
    if rev_res.global_reference_prompt_en.strip():
        updated_plan["global_reference_prompt_en"] = rev_res.global_reference_prompt_en.strip()
    if rev_res.current_master_prompt_cn.strip():
        updated_plan["current_master_prompt_cn"] = rev_res.current_master_prompt_cn.strip()
    if rev_res.current_master_prompt_en.strip():
        updated_plan["current_master_prompt_en"] = rev_res.current_master_prompt_en.strip()
    if rev_res.negative_constraints.strip():
        updated_plan["negative_constraints"] = rev_res.negative_constraints.strip()
    if rev_res.ai_character_profile_cn.strip():
        updated_plan["ai_character_profile_cn"] = rev_res.ai_character_profile_cn.strip()
    if rev_res.ai_character_profile_en.strip():
        updated_plan["ai_character_profile_en"] = rev_res.ai_character_profile_en.strip()

    if not updated_plan.get("current_master_prompt_cn"):
        updated_plan["current_master_prompt_cn"] = (
            updated_plan.get("global_reference_prompt_cn") or user_summary_text
        )

    if rev_res.storyboard:
        updated_dict["storyboard"] = [s.model_dump() for s in rev_res.storyboard]
    if rev_res.chatgpt_images_prompts:
        updated_dict["chatgpt_images_prompts"] = [
            p.model_dump() for p in rev_res.chatgpt_images_prompts
        ]
    if updated_dict.get("storyboard"):
        _apply_no_product_shot_guard(
            updated_dict["storyboard"],
            updated_dict.get("chatgpt_images_prompts") or [],
        )
    if rev_res.kling_prompts:
        neg_default = updated_plan.get("negative_constraints") or ""
        k_list = []
        for k in rev_res.kling_prompts:
            kd = k.model_dump()
            if neg_default and not str(kd.get("negative_prompt") or "").strip():
                kd["negative_prompt"] = neg_default
            k_list.append(kd)
        updated_dict["kling_prompts"] = k_list
    if rev_res.adapted_script_cn.strip() or rev_res.adapted_script_en.strip():
        copy_dict = dict(updated_dict.get("copywriting") or {})
        if rev_res.adapted_script_cn.strip():
            copy_dict["adapted_script_cn"] = rev_res.adapted_script_cn.strip()
        if rev_res.adapted_script_en.strip():
            copy_dict["adapted_script_en"] = rev_res.adapted_script_en.strip()
        updated_dict["copywriting"] = copy_dict

    updated_plan["has_user_customized"] = True
    updated_plan["revision_status"] = "draft"
    updated_plan["revision_history"] = new_history
    updated_dict["director_plan"] = updated_plan
    return updated_dict


@router.post("/videos/{video_id}/review-prompt")
async def review_product_replaced_prompt(
    video_id: str,
    db: Annotated[Session, Depends(get_db)],
    product_replaced_prompt_text: str = Form(default=""),
    storyboard_text: str = Form(default=""),
    prompt_file: UploadFile | None = File(default=None),
    storyboard_file: UploadFile | None = File(default=None),
    prompt_images: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    """Step 2A (Deep Understanding & Review ONLY): User provides two core inputs:
    1) Video Requirements Prompt (file and/or text)
    2) Storyboard Content (file and/or text)
    (Plus optional screenshots.) AI deeply understands both files with reference to the original
    video's creative direction (NOT forcing rigid 1:1 copying), focusing on natural motion,
    continuity, and controllability, returning checkable suggestions + editing guidelines."""
    req_parts: list[str] = []
    if prompt_file is not None and prompt_file.filename:
        doc_raw = await prompt_file.read()
        doc_text = _extract_prompt_doc_bytes_text(prompt_file.filename, doc_raw)
        if doc_text:
            req_parts.append(doc_text)
    if product_replaced_prompt_text.strip():
        req_parts.append(product_replaced_prompt_text.strip())

    sb_parts: list[str] = []
    if storyboard_file is not None and storyboard_file.filename:
        sb_raw = await storyboard_file.read()
        sb_text = _extract_prompt_doc_bytes_text(storyboard_file.filename, sb_raw)
        if sb_text:
            sb_parts.append(sb_text)
    if storyboard_text.strip():
        sb_parts.append(storyboard_text.strip())

    sections: list[str] = []
    if req_parts:
        sections.append("【文件 1：视频要求提示词】\n" + "\n\n".join(req_parts))
    if sb_parts:
        sections.append("【文件 2：分镜内容】\n" + "\n\n".join(sb_parts))
    prompt_text = "\n\n".join(sections).strip()

    prompt_shots_bytes: list[tuple[bytes, str]] = []
    for pf in (prompt_images or [])[:8]:
        raw = await pf.read()
        if not raw or len(raw) < 200:
            continue
        resized = _resize_jpeg(raw, max_side=1400, quality=85)
        prompt_shots_bytes.append((resized, "image/jpeg"))

    if not prompt_text and not prompt_shots_bytes:
        raise HTTPException(
            status_code=400,
            detail="请上传「视频要求提示词」和/或「分镜内容」文件（或直接粘贴文本/上传截图）",
        )

    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    ai = UnifiedAIClient(cfg)

    try:
        dna = ProductDNA.model_validate(
            session.product_dna or {"product_name": session.product_name}
        )
    except Exception:
        dna = ProductDNA(product_name=session.product_name)

    curr_analysis = dict(video.analysis_json or {})
    curr_plan = dict(curr_analysis.get("director_plan") or {})
    source_ev_images, source_timestamps = _collect_source_evidence_for_audit(
        video, curr_plan
    )
    product_refs, _ = _extract_product_ref_images(session)
    selected_product_refs = product_refs[:3]

    review_prompt = build_prompt_review_only_prompt(
        product_dna=dna,
        current_analysis=curr_analysis,
        product_replaced_prompt_text=prompt_text,
        source_frame_count=len(source_ev_images),
        source_timestamps=source_timestamps,
        prompt_screenshot_count=len(prompt_shots_bytes),
        product_photo_count=len(selected_product_refs),
    )

    combined_images: list[tuple[bytes, str]] = (
        source_ev_images + prompt_shots_bytes + selected_product_refs
    )

    try:
        review_res, _usage = await ai.generate_structured(
            prompt=review_prompt,
            schema_cls=PromptReviewResponse,
            tier="deep",
            images=combined_images,
            mock_context={"current_analysis": curr_analysis},
        )
    except Exception as exc:
        logger.exception("Prompt review failed for video %s: %s", video_id, exc)
        raise HTTPException(
            status_code=502, detail=f"对照原片逐帧核对失败：{exc}"
        ) from exc

    return {
        "ok": True,
        "review": review_res.model_dump(),
    }


@router.post("/videos/{video_id}/audit-revise")
async def audit_and_revise_prompt(
    video_id: str,
    db: Annotated[Session, Depends(get_db)],
    reference_prompt_text: str = Form(default=""),
    storyboard_text: str = Form(default=""),
    modification_notes: str = Form(default=""),
    prompt_file: UploadFile | None = File(default=None),
    storyboard_file: UploadFile | None = File(default=None),
    prompt_images: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    """Deep 2-file understanding & 4-part controllable shot decomposition:
    Ingests File 1 (Video Requirements Prompt) + File 2 (Storyboard Content) + optional screenshots
    + product photos (+ source video inspiration frames), and produces a natural, shot-isolated
    4-part production package ready for sequential image & Kling generation."""
    req_parts: list[str] = []
    if prompt_file is not None and prompt_file.filename:
        doc_raw = await prompt_file.read()
        doc_text = _extract_prompt_doc_bytes_text(prompt_file.filename, doc_raw)
        if doc_text:
            req_parts.append(doc_text)
    if reference_prompt_text.strip():
        req_parts.append(reference_prompt_text.strip())

    sb_parts: list[str] = []
    if storyboard_file is not None and storyboard_file.filename:
        sb_raw = await storyboard_file.read()
        sb_text = _extract_prompt_doc_bytes_text(storyboard_file.filename, sb_raw)
        if sb_text:
            sb_parts.append(sb_text)
    if storyboard_text.strip():
        sb_parts.append(storyboard_text.strip())

    sections: list[str] = []
    if req_parts:
        sections.append("【文件 1：视频要求提示词】\n" + "\n\n".join(req_parts))
    if sb_parts:
        sections.append("【文件 2：分镜内容】\n" + "\n\n".join(sb_parts))
    ref_text = "\n\n".join(sections).strip()
    mod_notes = modification_notes.strip()

    prompt_shots_bytes: list[tuple[bytes, str]] = []
    for pf in (prompt_images or [])[:8]:
        raw = await pf.read()
        if not raw or len(raw) < 200:
            continue
        resized = _resize_jpeg(raw, max_side=1400, quality=85)
        prompt_shots_bytes.append((resized, "image/jpeg"))

    if not ref_text and not mod_notes and not prompt_shots_bytes:
        raise HTTPException(
            status_code=400,
            detail="请至少提供参考提示词（文字或截图）或写下你想修改的内容",
        )

    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    ai = UnifiedAIClient(cfg)

    try:
        dna = ProductDNA.model_validate(
            session.product_dna or {"product_name": session.product_name}
        )
    except Exception:
        dna = ProductDNA(product_name=session.product_name)

    curr_analysis = dict(video.analysis_json or {})
    curr_plan = dict(curr_analysis.get("director_plan") or {})
    history = list(curr_plan.get("revision_history") or [])

    memory_block = load_director_memory_block(
        db,
        product_name=dna.product_name,
        category=dna.category,
    )

    source_ev_images, source_timestamps = _collect_source_evidence_for_audit(
        video, curr_plan
    )
    product_refs, _ = _extract_product_ref_images(session)
    selected_product_refs = product_refs[:3]

    audit_prompt = build_prompt_audit_and_revision_prompt(
        product_dna=dna,
        current_analysis=curr_analysis,
        reference_prompt_text=ref_text,
        modification_notes=mod_notes,
        source_frame_count=len(source_ev_images),
        source_timestamps=source_timestamps,
        prompt_screenshot_count=len(prompt_shots_bytes),
        product_photo_count=len(selected_product_refs),
        revision_history=history,
        director_memory_block=memory_block,
    )

    combined_images: list[tuple[bytes, str]] = (
        source_ev_images + prompt_shots_bytes + selected_product_refs
    )
    user_summary = mod_notes or (
        f"核对提示词截图（{len(prompt_shots_bytes)}张）"
        if prompt_shots_bytes
        else ref_text[:120]
    )

    # Deterministic structured pack parser: if the user uploaded structured multi-shot files
    # (e.g. 【镜头01｜...】..【镜头07｜...】), parse ALL N shots 100% faithfully in Python so an LLM
    # can NEVER drop shots or emit placeholder strings!
    parsed_pack = parse_structured_production_pack(ref_text, product_name=dna.product_name)
    is_direct_decompose = (
        parsed_pack is not None
        and (
            not mod_notes
            or "100% 深度理解并保留" in mod_notes
            or "无需改动剧情" in mod_notes
        )
    )

    def _pack_to_revision_response(pack: dict[str, Any]) -> DirectorRevisionResponse:
        return DirectorRevisionResponse(
            director_reply=(
                f"已 100% 精准拆解你的结构化双文件：完整保留全部 {pack['shot_count']} 个独立镜头"
                f"（零删减、零占位词、无成品镜头已自动防串镜），请确认后直接进入步骤 2 生成关键图片！"
            ),
            changed_shots=[s.shot_no for s in pack["storyboard"]],
            prompt_audit_report=pack["audit_report"],
            editing_guidelines=pack["editing_guidelines"],
            global_reference_prompt_cn=pack["global_reference_prompt_cn"],
            global_reference_prompt_en=pack["global_reference_prompt_cn"],
            current_master_prompt_cn=pack["master_summary"],
            current_master_prompt_en=pack["master_summary"],
            negative_constraints=pack["negative_constraints"],
            ai_character_profile_cn=pack["ai_character_profile_cn"],
            ai_character_profile_en=pack["ai_character_profile_cn"],
            storyboard=pack["storyboard"],
            chatgpt_images_prompts=pack["chatgpt_images_prompts"],
            kling_prompts=pack["kling_prompts"],
            learned_memories=[],
            analysis=None,
        )

    if is_direct_decompose and parsed_pack is not None:
        rev_res = _pack_to_revision_response(parsed_pack)
    else:
        try:
            rev_res, _usage = await ai.generate_structured(
                prompt=audit_prompt,
                schema_cls=DirectorRevisionResponse,
                tier="deep",
                images=combined_images,
                mock_context={
                    "current_analysis": curr_analysis,
                    "user_feedback": user_summary,
                },
            )
        except Exception as exc:
            if parsed_pack is not None:
                logger.warning("LLM audit failed, falling back to deterministic pack parser: %s", exc)
                rev_res = _pack_to_revision_response(parsed_pack)
            else:
                logger.exception("Prompt audit & revision failed for video %s: %s", video_id, exc)
                raise HTTPException(
                    status_code=502, detail=f"深度拆解并生成新版提示词失败：{exc}"
                ) from exc

        # Hard P0 quality guard: if LLM dropped shots or emitted ANY placeholder string,
        # immediately substitute the deterministic structured parse!
        if parsed_pack is not None:
            llm_shots = rev_res.storyboard or []
            llm_imgs = rev_res.chatgpt_images_prompts or []
            has_placeholder = any(
                is_placeholder_text(s.adapted_visual_for_product) for s in llm_shots
            ) or any(
                is_placeholder_text(p.prompt_en) and is_placeholder_text(p.prompt_cn)
                for p in llm_imgs
            )
            if len(llm_shots) < parsed_pack["shot_count"] or has_placeholder:
                logger.warning(
                    "LLM output failed P0 guard (shots=%d vs expected=%d, placeholder=%s); "
                    "using deterministic pack parser!",
                    len(llm_shots),
                    parsed_pack["shot_count"],
                    has_placeholder,
                )
                rev_res = _pack_to_revision_response(parsed_pack)

    saved_memories = save_learned_memories(
        db,
        rev_res.learned_memories or [],
        source_video_title=video.title or session.product_name,
    )
    learned_summaries = [m.rule_summary for m in saved_memories]

    now_str = datetime.now(CN_TZ).strftime("%H:%M")
    new_history = list(history)
    new_history.append({"role": "user", "message": user_summary, "timestamp": now_str})
    new_history.append(
        {
            "role": "director",
            "message": rev_res.director_reply,
            "changed_shots": rev_res.changed_shots,
            "learned_memories": learned_summaries,
            "timestamp": now_str,
        }
    )

    updated_dict = _merge_revision_into_analysis(
        curr_analysis=curr_analysis,
        curr_plan=curr_plan,
        rev_res=rev_res,
        user_summary_text=user_summary,
        new_history=new_history,
    )

    video.analysis_json = updated_dict
    flag_modified(video, "analysis_json")
    db.commit()
    db.refresh(video)

    return {
        "ok": True,
        "director_reply": rev_res.director_reply,
        "prompt_audit_report": (
            rev_res.prompt_audit_report.model_dump()
            if rev_res.prompt_audit_report
            else None
        ),
        "changed_shots": rev_res.changed_shots,
        "learned_memories": [
            _serialize_memory(m).model_dump(mode="json") for m in saved_memories
        ],
        "analysis_json": video.analysis_json,
    }


@router.post("/videos/{video_id}/revise-plan")
async def revise_director_plan(
    video_id: str,
    body: RevisePlanRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Multi-turn AI Director co-creation: revise 1:1 storyboard, replacement AI character,
    product placement, and synced image/Kling/voiceover prompts BEFORE spending image/video credits.
    Automatically extracts & reinforces reusable long-term director memories."""
    feedback = body.feedback.strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="请输入你想修改的意见或想法")

    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    ai = UnifiedAIClient(cfg)

    try:
        dna = ProductDNA.model_validate(session.product_dna or {"product_name": session.product_name})
    except Exception:
        dna = ProductDNA(product_name=session.product_name)

    curr_analysis = dict(video.analysis_json or {})
    curr_plan = dict(curr_analysis.get("director_plan") or {})
    history = list(curr_plan.get("revision_history") or [])

    memory_block = load_director_memory_block(
        db,
        product_name=dna.product_name,
        category=dna.category,
    )

    rev_prompt = build_director_revision_prompt(
        product_dna=dna,
        current_analysis=curr_analysis,
        user_feedback=feedback,
        revision_history=history,
        director_memory_block=memory_block,
    )

    product_refs, _ = _extract_product_ref_images(session)

    try:
        rev_res, _usage = await ai.generate_structured(
            prompt=rev_prompt,
            schema_cls=DirectorRevisionResponse,
            tier="deep",
            # Pass up to 4 multi-angle uploaded product photos so AI sees front/side/detail angles!
            images=product_refs[:4],
            mock_context={
                "current_analysis": curr_analysis,
                "user_feedback": feedback,
            },
        )
    except Exception as exc:
        logger.exception("Director plan revision failed for video %s: %s", video_id, exc)
        raise HTTPException(status_code=502, detail=f"AI 导演修改方案失败：{exc}") from exc

    saved_memories = save_learned_memories(
        db,
        rev_res.learned_memories or [],
        source_video_title=video.title or session.product_name,
    )
    learned_summaries = [m.rule_summary for m in saved_memories]

    now_str = datetime.now(CN_TZ).strftime("%H:%M")
    new_history = list(history)
    new_history.append({"role": "user", "message": feedback, "timestamp": now_str})
    new_history.append(
        {
            "role": "director",
            "message": rev_res.director_reply,
            "changed_shots": rev_res.changed_shots,
            "learned_memories": learned_summaries,
            "timestamp": now_str,
        }
    )

    updated_dict = _merge_revision_into_analysis(
        curr_analysis=curr_analysis,
        curr_plan=curr_plan,
        rev_res=rev_res,
        user_summary_text=feedback,
        new_history=new_history,
    )

    video.analysis_json = updated_dict
    flag_modified(video, "analysis_json")
    db.commit()
    db.refresh(video)

    return {
        "ok": True,
        "director_reply": rev_res.director_reply,
        "prompt_audit_report": (
            rev_res.prompt_audit_report.model_dump()
            if rev_res.prompt_audit_report
            else None
        ),
        "changed_shots": rev_res.changed_shots,
        "learned_memories": [_serialize_memory(m).model_dump(mode="json") for m in saved_memories],
        "analysis_json": video.analysis_json,
    }


@router.post("/videos/{video_id}/lock-plan")
def lock_director_plan(
    video_id: str,
    body: LockPlanRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Lock (or unlock) the finalized video prompt before launching image/video generation."""
    video, _session = _get_video_and_session(db, video_id)
    analysis = dict(video.analysis_json or {})
    plan = dict(analysis.get("director_plan") or {})
    if body.master_prompt_cn is not None and body.master_prompt_cn.strip():
        plan["current_master_prompt_cn"] = body.master_prompt_cn.strip()
        plan["has_user_customized"] = True
    if body.master_prompt_en is not None and body.master_prompt_en.strip():
        plan["current_master_prompt_en"] = body.master_prompt_en.strip()
    if body.global_reference_prompt_cn is not None and body.global_reference_prompt_cn.strip():
        plan["global_reference_prompt_cn"] = body.global_reference_prompt_cn.strip()
        plan["has_user_customized"] = True
    if body.negative_constraints is not None and body.negative_constraints.strip():
        plan["negative_constraints"] = body.negative_constraints.strip()
    plan["revision_status"] = "locked" if body.locked else "draft"
    analysis["director_plan"] = plan
    video.analysis_json = analysis
    flag_modified(video, "analysis_json")
    db.commit()
    db.refresh(video)
    return {
        "ok": True,
        "revision_status": plan["revision_status"],
        "analysis_json": video.analysis_json,
    }


@router.post("/videos/{video_id}/refine-image", response_model=GeneratedAssetOut)
async def refine_single_image(
    video_id: str,
    body: RefineImageRequest,
    db: Annotated[Session, Depends(get_db)],
) -> GeneratedAssetOut:
    """Apply a user's Chinese visual correction (e.g. '换更年轻的欧美金发贵妇', '光线调亮', '沙发放大')
    to a specific generated frame's prompt and immediately re-generate ONLY that single image."""
    feedback = body.feedback.strip()
    if not feedback:
        raise HTTPException(status_code=400, detail="请填写你对这张图的修改意见")

    cfg = get_settings()
    video, session = _get_video_and_session(db, video_id)
    provider = body.provider or cfg.default_image_provider
    if provider == "gemini" and not cfg.gemini_image_configured():
        raise HTTPException(status_code=400, detail="尚未配置 GEMINI_API_KEY")
    if provider == "openai" and not cfg.openai_image_configured():
        raise HTTPException(
            status_code=400, detail="尚未配置 OPENAI_IMAGE_API_KEY 或 OPENAI_API_KEY"
        )

    analysis = dict(video.analysis_json or {})
    plan = dict(analysis.get("director_plan") or {})
    dna = session.product_dna or {}
    pname = str(dna.get("product_name") or session.product_name or "产品")
    pform = str(dna.get("physical_form") or "")
    char_en = str(plan.get("ai_character_profile_en") or "")

    # Determine base prompt from request or stored slot prompt
    base_prompt = body.base_prompt.strip()
    img_prompts = list(analysis.get("chatgpt_images_prompts") or [])
    if not base_prompt and 0 <= body.slot_index < len(img_prompts):
        base_prompt = str(
            img_prompts[body.slot_index].get("prompt_en")
            or img_prompts[body.slot_index].get("prompt_cn")
            or ""
        )

    ai = UnifiedAIClient(cfg)
    refine_prompt = build_image_refinement_prompt(
        product_name=pname,
        product_form=pform,
        base_prompt=base_prompt,
        user_feedback=feedback,
        character_profile_en=char_en,
    )
    try:
        refined, _usage = await ai.generate_structured(
            prompt=refine_prompt,
            schema_cls=RefinedImagePromptResponse,
            tier="fast",
            mock_context={"base_prompt": base_prompt, "feedback": feedback},
        )
        new_prompt_en = refined.refined_prompt_en.strip() or f"{base_prompt}. User fix: {feedback}"
        new_prompt_cn = refined.refined_prompt_cn.strip()
    except Exception as exc:
        logger.warning("Image prompt refinement fallback for slot %s: %s", body.slot_index, exc)
        new_prompt_en = f"{base_prompt}\nCRITICAL USER VISUAL FIX: {feedback}."
        new_prompt_cn = feedback

    # Persist refined prompt into the slot so subsequent regenerations keep the fix
    if 0 <= body.slot_index < len(img_prompts) and isinstance(img_prompts[body.slot_index], dict):
        slot_dict = dict(img_prompts[body.slot_index])
        slot_dict["prompt_en"] = new_prompt_en
        if new_prompt_cn:
            slot_dict["prompt_cn"] = new_prompt_cn
        img_prompts[body.slot_index] = slot_dict
        analysis["chatgpt_images_prompts"] = img_prompts
        video.analysis_json = analysis
        flag_modified(video, "analysis_json")
        db.commit()

    product_refs, _ = _extract_product_ref_images(session)
    # If user explicitly asked to change the person/character on this image, don't force old character ref!
    changing_person = any(
        k in feedback for k in ("人物", "长相", "脸", "发型", "年龄", "贵妇", "女生", "男生", "换成", "换人", "模特")
    )
    final_prompt, final_refs = await _prepare_shot_image_inputs(
        video=video,
        session=session,
        db=db,
        slot_index=body.slot_index,
        shot_no=body.shot_no,
        prompt=new_prompt_en,
        product_refs=product_refs,
        use_character_ref=body.use_character_ref and not changing_person,
    )

    asset = GeneratedAsset(
        video_id=video.id,
        session_id=session.id,
        asset_type="image",
        slot_index=body.slot_index,
        shot_no=body.shot_no,
        scene_title=body.scene_title or f"画面 {body.slot_index}",
        provider=provider,
        model_name=body.model_override
        or (cfg.gemini_image_model if provider == "gemini" else cfg.openai_image_model),
        status="processing",
        prompt_used=final_prompt,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    await _run_image_job(
        asset_id=asset.id,
        prompt=final_prompt,
        ref_images=final_refs,
        provider=provider,
        model_override=body.model_override,
        aspect_ratio=body.aspect_ratio,
        scene_title=asset.scene_title,
        product_name=session.product_name,
    )
    db.refresh(asset)
    return _serialize_asset(asset)


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
    product_refs, _ = _extract_product_ref_images(session)
    final_prompt, final_refs = await _prepare_shot_image_inputs(
        video=video,
        session=session,
        db=db,
        slot_index=body.slot_index,
        shot_no=body.shot_no,
        prompt=body.prompt,
        product_refs=product_refs,
        use_character_ref=body.use_character_ref,
    )
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
        prompt_used=final_prompt,
        mime_type="image/jpeg",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    # Single image runs directly (or fast in mock) so user sees immediate result on click
    await _run_image_job(
        asset_id=asset.id,
        prompt=final_prompt,
        ref_images=final_refs,
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

    product_refs, _ = _extract_product_ref_images(session)
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
        factory = get_session_factory()
        for aid, bp in jobs:
            job_db = factory()
            try:
                v_row = job_db.get(VideoRecord, video.id)
                s_row = job_db.get(ScanSession, session.id)
                if v_row and s_row:
                    shot_prompt, shot_refs = await _prepare_shot_image_inputs(
                        video=v_row,
                        session=s_row,
                        db=job_db,
                        slot_index=bp["slot_index"],
                        shot_no=bp["shot_no"],
                        prompt=bp["prompt"],
                        product_refs=product_refs,
                        use_character_ref=body.use_character_ref,
                    )
                else:
                    shot_prompt, shot_refs = bp["prompt"], product_refs
            finally:
                job_db.close()

            await _run_image_job(
                asset_id=aid,
                prompt=shot_prompt,
                ref_images=shot_refs,
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

    src_img = db.scalars(
        select(GeneratedAsset)
        .options(defer(GeneratedAsset.file_data))
        .where(GeneratedAsset.id == body.source_image_asset_id)
    ).first()
    src_bytes = await _load_asset_bytes(src_img, db) if src_img and src_img.video_id == video.id else None
    if not src_img or not src_bytes:
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
            image_bytes=src_bytes,
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
    )
    db.add(asset)
    db.flush()
    _save_asset_media(asset, data)
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
    )
    db.add(asset)
    db.flush()
    _save_asset_media(asset, data)
    db.commit()
    db.refresh(asset)
    return _serialize_asset(asset)


@router.post("/videos/{video_id}/extract-last-frame", response_model=GeneratedAssetOut)
async def extract_last_frame_for_next_shot(
    video_id: str,
    body: ExtractLastFrameRequest,
    db: Annotated[Session, Depends(get_db)],
) -> GeneratedAssetOut:
    """Universal continuity rule: extract the crisp last frame of any completed video clip
    (typically Shot N-1) and save it as the first-frame image of target_shot_no (Shot N),
    eliminating scene/background/camera jumps across consecutive shots in ANY video."""
    if not is_ffmpeg_available():
        raise HTTPException(status_code=400, detail="当前环境未检测到 FFmpeg，无法提取尾帧")
    video, session = _get_video_and_session(db, video_id)
    src_vid = db.scalars(
        select(GeneratedAsset)
        .options(defer(GeneratedAsset.file_data))
        .where(GeneratedAsset.id == body.source_video_asset_id)
    ).first()
    if not src_vid or src_vid.video_id != video.id:
        raise HTTPException(status_code=404, detail="源视频片段不存在")
    raw_vid = await _load_asset_bytes(src_vid, db)
    if not raw_vid:
        raise HTTPException(status_code=400, detail="源视频片段文件尚未就绪")

    try:
        jpg_bytes = await asyncio.to_thread(extract_last_frame_jpeg, raw_vid)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提取尾帧失败：{exc}") from exc

    asset = GeneratedAsset(
        video_id=video.id,
        session_id=session.id,
        asset_type="image",
        slot_index=body.target_shot_no,
        shot_no=body.target_shot_no,
        scene_title=body.scene_title.strip()
        or f"分镜 {body.target_shot_no} 首帧（继承分镜 {src_vid.shot_no or ''} 尾帧）",
        provider="ffmpeg_last_frame",
        model_name="last-frame-inherit",
        status="completed",
        prompt_used=f"继承自 {src_vid.scene_title or src_vid.id} 尾帧，保持场景与构图 100% 连续",
        mime_type="image/jpeg",
    )
    db.add(asset)
    db.flush()
    _save_asset_media(asset, jpg_bytes)
    db.commit()
    db.refresh(asset)
    return _serialize_asset(asset)


@router.post("/videos/{video_id}/stitch-final", response_model=GeneratedAssetOut)
async def stitch_final_video(
    video_id: str,
    body: StitchFinalVideoRequest,
    request: Request,
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
        .options(defer(GeneratedAsset.file_data))
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

    # Build universal per-shot planned duration map from storyboard time_range (e.g. '约3秒', '1.5-3秒')
    planned_dur_by_shot: dict[int, float] = {}
    for idx, shot in enumerate(list((video.analysis_json or {}).get("storyboard") or []), start=1):
        if isinstance(shot, dict):
            sno = int(shot.get("shot_no") or idx)
            planned_dur_by_shot[sno] = parse_planned_shot_duration_sec(
                str(shot.get("time_range") or ""),
                default=3.0,
            )

    def _target_dur_for_row(row: GeneratedAsset, fallback: float) -> float:
        if body.trim_to_planned_duration and row.shot_no and row.shot_no in planned_dur_by_shot:
            return planned_dur_by_shot[row.shot_no]
        return fallback

    if body.asset_ids:
        for aid in body.asset_ids:
            row = by_id.get(aid)
            if not row:
                continue
            raw_bytes = await _load_asset_bytes(row, db)
            if not raw_bytes:
                continue
            if row.asset_type in ("video_clip", "uploaded_clip"):
                ordered_media.append(
                    ("video", raw_bytes, _target_dur_for_row(row, row.duration_sec or 5.0))
                )
                used_labels.append(row.scene_title or f"镜头{row.shot_no}")
            elif row.asset_type == "image" and body.include_images_as_motion:
                ordered_media.append(
                    ("image", raw_bytes, _target_dur_for_row(row, body.image_clip_duration))
                )
                used_labels.append(row.scene_title or f"镜头{row.shot_no}")
    else:
        latest_upload: dict[int, GeneratedAsset] = {}
        latest_ai_vid: dict[int, GeneratedAsset] = {}
        latest_img: dict[int, GeneratedAsset] = {}
        for row in completed:
            if not row.shot_no or row.shot_no < 1:
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
                raw = await _load_asset_bytes(r, db)
                if raw:
                    ordered_media.append(("video", raw, _target_dur_for_row(r, r.duration_sec or 5.0)))
                    used_labels.append(f"分镜{sno}(实拍)")
                    continue
            if sno in latest_ai_vid:
                r = latest_ai_vid[sno]
                raw = await _load_asset_bytes(r, db)
                if raw:
                    ordered_media.append(("video", raw, _target_dur_for_row(r, r.duration_sec or 5.0)))
                    used_labels.append(f"分镜{sno}(可灵AI)")
                    continue
            if body.include_images_as_motion and sno in latest_img:
                r = latest_img[sno]
                raw = await _load_asset_bytes(r, db)
                if raw:
                    ordered_media.append(("image", raw, _target_dur_for_row(r, body.image_clip_duration)))
                    used_labels.append(f"分镜{sno}(AI图转动态)")

    if not ordered_media:
        raise HTTPException(
            status_code=400,
            detail="暂无可拼接的分镜素材，请先逐镜生成分镜商品图或上传实拍视频片段",
        )

    try:
        final_bytes, total_dur = await asyncio.to_thread(
            stitch_media_items_to_mp4,
            ordered_media,
            trim_videos_to_duration=body.trim_to_planned_duration,
        )
    except Exception as exc:
        logger.exception("FFmpeg stitch failed for video %s: %s", video_id, exc)
        raise HTTPException(status_code=500, detail=f"成片合成失败：{exc}") from exc

    # Automatic Audio & SFX Matching:
    # 1) Match original video's real SFX track (tempo-aligned) or Kling Video-to-Audio AI Foley
    # 2) Optional free AI Voiceover + BGM
    sfx_track_bytes: bytes | None = None
    voiceover_bytes: bytes | None = None
    bgm_bytes: bytes | None = None
    audio_tags: list[str] = []

    sfx_mode = body.sfx_mode or "auto_match_source"
    if sfx_mode != "none":
        src_audio = load_source_audio_bytes(video.id, MEDIA_DIR)
        sfx_prompt_text = (body.sfx_prompt or _build_recommended_sfx_prompt(video)).strip()

        # Engine B: Kling Video-to-Audio AI Foley (when explicitly chosen & public URL is reachable)
        if (
            sfx_mode == "kling_v2a"
            and cfg.kling_configured()
            and not cfg.enable_mock_mode
            and not cfg.app_password.strip()
            and 3.0 <= total_dur <= 20.0
        ):
            temp_asset = GeneratedAsset(
                video_id=video.id,
                session_id=session.id,
                asset_type="final_video",
                slot_index=-9,
                shot_no=None,
                scene_title="sfx_temp",
                provider="ffmpeg_stitch",
                model_name="temp",
                status="processing",
                mime_type="video/mp4",
            )
            db.add(temp_asset)
            db.flush()
            _save_asset_media(temp_asset, final_bytes)
            db.commit()
            public_base = str(request.base_url).rstrip("/")
            if public_base.startswith("http") and "localhost" not in public_base and "127.0.0.1" not in public_base:
                kling_v2a_mp4 = await generate_kling_video_to_audio(
                    video_url=f"{public_base}/api/studio/assets/{temp_asset.id}/file",
                    sound_effect_prompt=sfx_prompt_text,
                    asmr_mode=True,
                    api_key=cfg.resolved_kling_api_key(),
                    base_url=cfg.kling_base_url,
                )
                if kling_v2a_mp4:
                    final_bytes = kling_v2a_mp4
                    audio_tags.append("AI逐帧拟音(Kling V2A)")
            _delete_local_media(temp_asset.id)
            db.delete(temp_asset)
            db.commit()

        # Engine A (Primary / Automatic Fallback): Original Video Real Audio Track Tempo-Aligned
        if not audio_tags and src_audio:
            try:
                sfx_track_bytes = await asyncio.to_thread(
                    align_source_audio_to_duration, src_audio, total_dur
                )
                audio_tags.append("原视频同款音效智能对齐")
            except Exception as exc:
                logger.warning("Source audio alignment skipped: %s", exc)
        elif not audio_tags and sfx_mode == "auto_match_source" and body.bgm_mode == "none":
            # Fallback cinematic ambience pad when original video had no audio track
            try:
                sfx_track_bytes = await asyncio.to_thread(
                    generate_builtin_bgm_mp3, "ambient_chill", total_dur
                )
                audio_tags.append("智能电影氛围音效兜底")
            except Exception:
                pass

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
            (r for r in completed if r.asset_type == "bgm_audio"), None
        )
        if bgm_row:
            bgm_bytes = await _load_asset_bytes(bgm_row, db)
            if bgm_bytes:
                audio_tags.append(f"BGM({bgm_row.scene_title[:16]})")
    elif body.bgm_mode in ("ambient_chill", "upbeat_pulse"):
        bgm_bytes = await asyncio.to_thread(
            generate_builtin_bgm_mp3, body.bgm_mode, total_dur
        )
        audio_tags.append(
            "内置商业轻节奏BGM" if body.bgm_mode == "upbeat_pulse" else "内置极简氛围BGM"
        )

    if sfx_track_bytes or voiceover_bytes or bgm_bytes:
        try:
            final_bytes = await asyncio.to_thread(
                mix_audio_into_mp4,
                final_bytes,
                sfx_track_bytes=sfx_track_bytes,
                voiceover_bytes=voiceover_bytes,
                bgm_bytes=bgm_bytes,
                keep_original_audio=True,
                sfx_volume=0.90,
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
        duration_sec=total_dur,
        width=720,
        height=1280,
    )
    db.add(final_asset)
    db.flush()
    _save_asset_media(final_asset, final_bytes)
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
    _delete_local_media(row.id)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/assets/{asset_id}/file")
async def get_studio_asset_file(
    asset_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    download: bool = Query(default=False),
) -> Response:
    # Always defer file_data first so streaming from local disk costs ZERO database egress!
    row = db.scalars(
        select(GeneratedAsset)
        .options(defer(GeneratedAsset.file_data))
        .where(GeneratedAsset.id == asset_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="素材不存在")

    local_path = _find_local_media_path(row.id, row.mime_type)
    if local_path is None:
        raw = await _load_asset_bytes(row, db)
        if raw:
            local_path = _find_local_media_path(row.id, row.mime_type)

    if local_path is None or not local_path.exists():
        raise HTTPException(status_code=404, detail="素材文件尚未生成完毕或已过期，请重新合成")

    total_len = local_path.stat().st_size
    mime = row.mime_type or "application/octet-stream"
    ext = _ext_for_mime(mime)
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
                _iter_file_chunks(local_path, start, end),
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
        _iter_file_chunks(local_path, 0, total_len - 1),
        status_code=200,
        media_type=mime,
        headers=headers_200,
    )
