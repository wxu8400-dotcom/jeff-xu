from __future__ import annotations

import asyncio
import json
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..auth import require_auth
from ..config import get_settings
from ..database import get_db
from ..models import ScanSession, VideoRecord
from ..schemas import ScanSessionDetail, ScanSessionSummary
from ..services.exporter import export_session_json, export_session_markdown
from ..services.pipeline import event_broker, format_history_title, run_radar_pipeline
from ..services.product_parser import UploadedRawFile, parse_product_materials

router = APIRouter(
    prefix="/api/scans",
    tags=["scans"],
    dependencies=[Depends(require_auth)],
)

_active_tasks: set[asyncio.Task] = set()


async def _read_uploads(files: list[UploadFile] | None) -> list[UploadedRawFile]:
    if not files:
        return []
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    raw_files: list[UploadedRawFile] = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"文件 {f.filename} 超过 {settings.max_upload_mb}MB 上限",
            )
        raw_files.append(
            UploadedRawFile(
                filename=f.filename or "unnamed",
                content_type=f.content_type or "application/octet-stream",
                data=data,
            )
        )
    return raw_files


def _parse_platforms(raw: str) -> list[str]:
    allowed = {"tiktok", "instagram", "youtube"}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            cleaned = [str(p).lower() for p in parsed if str(p).lower() in allowed]
            if cleaned:
                return cleaned
    except Exception:
        pass
    cleaned = [p.strip().lower() for p in raw.split(",") if p.strip().lower() in allowed]
    return cleaned or ["tiktok", "instagram", "youtube"]


@router.post("")
async def create_radar_scan(
    db: Annotated[Session, Depends(get_db)],
    files: list[UploadFile] | None = File(default=None),
    product_text: str = Form(default=""),
    product_name_override: str = Form(default=""),
    user_instruction: str = Form(default=""),
    platforms: str = Form(default='["tiktok","instagram","youtube"]'),
    min_views: int = Form(default=100000),
    min_likes: int = Form(default=5000),
    date_range_days: int = Form(default=30),
    target_count: int = Form(default=5),
    auto_relax: bool = Form(default=True),
) -> dict[str, str]:
    raw_files = await _read_uploads(files)
    if not raw_files and not product_text.strip() and not product_name_override.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请至少上传一份产品资料（图片/视频/文档）或输入产品文字说明",
        )

    bundle = await asyncio.to_thread(parse_product_materials, raw_files, product_text)
    plat_list = _parse_platforms(platforms)
    initial_name = product_name_override.strip() or "解析中产品"
    filter_cfg = {
        "min_views": max(0, min_views),
        "min_likes": max(0, min_likes),
        "date_range_days": max(0, date_range_days),
        "target_count": max(1, min(target_count, 10)),
        "auto_relax": auto_relax,
    }

    session = ScanSession(
        history_title=format_history_title(initial_name),
        product_name=initial_name,
        mode="radar",
        status="queued",
        progress_percent=5,
        progress_message="雷达任务已启动，准备解析产品资料...",
        user_instruction=user_instruction.strip(),
        platforms=plat_list,
        filter_config=filter_cfg,
        product_assets=bundle.assets_meta,
        funnel_stats={
            "collected": 0,
            "after_hard_filter": 0,
            "after_screening": 0,
            "analyzed": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_cny": 0.0,
        },
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    task = asyncio.create_task(
        run_radar_pipeline(
            session_id=session.id,
            product_bundle=bundle,
            product_name_override=product_name_override,
            user_instruction=user_instruction.strip(),
            platforms=plat_list,
            filter_config=filter_cfg,
        )
    )
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

    return {"session_id": session.id, "history_title": session.history_title}


@router.post("/analyze-urls")
async def create_direct_url_scan(
    db: Annotated[Session, Depends(get_db)],
    files: list[UploadFile] | None = File(default=None),
    urls: str = Form(...),
    product_text: str = Form(default=""),
    product_name_override: str = Form(default=""),
    user_instruction: str = Form(default=""),
) -> dict[str, str]:
    url_list = [u.strip() for u in urls.replace(",", "\n").splitlines() if u.strip().startswith("http")]
    if not url_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请粘贴至少 1 条有效的 TikTok / Instagram / YouTube 视频链接",
        )
    raw_files = await _read_uploads(files)
    if not raw_files and not product_text.strip() and not product_name_override.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请上传产品资料或填写产品说明，以便生成可替换方案与提示词",
        )

    bundle = await asyncio.to_thread(parse_product_materials, raw_files, product_text)
    initial_name = product_name_override.strip() or "解析中产品"
    session = ScanSession(
        history_title=format_history_title(initial_name),
        product_name=initial_name,
        mode="direct_urls",
        status="queued",
        progress_percent=5,
        progress_message="指定链接直拆任务已启动...",
        user_instruction=user_instruction.strip(),
        platforms=["tiktok", "instagram", "youtube"],
        filter_config={"direct_urls": url_list[:5]},
        product_assets=bundle.assets_meta,
        funnel_stats={
            "collected": len(url_list[:5]),
            "after_hard_filter": len(url_list[:5]),
            "after_screening": len(url_list[:5]),
            "analyzed": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_cny": 0.0,
        },
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    task = asyncio.create_task(
        run_radar_pipeline(
            session_id=session.id,
            product_bundle=bundle,
            product_name_override=product_name_override,
            user_instruction=user_instruction.strip(),
            platforms=["tiktok", "instagram", "youtube"],
            filter_config={"target_count": len(url_list[:5])},
            direct_urls=url_list[:5],
        )
    )
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

    return {"session_id": session.id, "history_title": session.history_title}


@router.get("/{session_id}/events")
async def stream_scan_events(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    sess = db.get(ScanSession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="扫描任务不存在")

    initial_payload = {
        "session_id": sess.id,
        "status": sess.status,
        "progress_percent": sess.progress_percent,
        "progress_message": sess.progress_message,
        "error_message": sess.error_message,
        "product_name": sess.product_name,
        "history_title": sess.history_title,
        "funnel_stats": sess.funnel_stats,
    }

    async def event_generator():
        yield f"data: {json.dumps(initial_payload, ensure_ascii=False)}\n\n"
        if initial_payload["status"] in ("completed", "failed"):
            return

        queue = event_broker.subscribe(session_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("status") in ("completed", "failed"):
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            event_broker.unsubscribe(session_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=list[ScanSessionSummary])
def list_history(
    db: Annotated[Session, Depends(get_db)],
    q: str = Query(default=""),
    limit: int = Query(default=60, ge=1, le=200),
) -> list[ScanSessionSummary]:
    stmt = select(ScanSession).order_by(desc(ScanSession.created_at)).limit(limit)
    if q.strip():
        like_pat = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                ScanSession.history_title.ilike(like_pat),
                ScanSession.product_name.ilike(like_pat),
                ScanSession.user_instruction.ilike(like_pat),
            )
        )
    sessions = list(db.scalars(stmt).all())
    if not sessions:
        return []

    counts_stmt = (
        select(VideoRecord.session_id, func.count(VideoRecord.id))
        .where(VideoRecord.session_id.in_([s.id for s in sessions]))
        .group_by(VideoRecord.session_id)
    )
    count_map = dict(db.execute(counts_stmt).all())

    return [
        ScanSessionSummary(
            id=s.id,
            history_title=s.history_title,
            product_name=s.product_name,
            mode=s.mode,
            status=s.status,
            progress_percent=s.progress_percent,
            progress_message=s.progress_message,
            error_message=s.error_message,
            platforms=s.platforms or [],
            funnel_stats=s.funnel_stats or {},
            video_count=int(count_map.get(s.id, 0)),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


@router.get("/{session_id}", response_model=ScanSessionDetail)
def get_scan_detail(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ScanSessionDetail:
    stmt = (
        select(ScanSession)
        .options(selectinload(ScanSession.videos))
        .where(ScanSession.id == session_id)
    )
    sess = db.scalars(stmt).first()
    if not sess:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    return ScanSessionDetail.model_validate(sess)


@router.delete("/{session_id}")
def delete_scan(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    sess = db.get(ScanSession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    db.delete(sess)
    db.commit()
    return {"ok": True}


@router.get("/{session_id}/export")
def export_scan(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    format: str = Query(default="md", pattern="^(md|json)$"),
) -> Response:
    stmt = (
        select(ScanSession)
        .options(selectinload(ScanSession.videos))
        .where(ScanSession.id == session_id)
    )
    sess = db.scalars(stmt).first()
    if not sess:
        raise HTTPException(status_code=404, detail="历史记录不存在")

    safe_title = sess.history_title.replace("/", "-").replace("\\", "-")
    encoded_name = quote(f"{safe_title}.{format}")
    if format == "json":
        content = export_session_json(sess)
        media_type = "application/json; charset=utf-8"
    else:
        content = export_session_markdown(sess)
        media_type = "text/markdown; charset=utf-8"

    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"
        },
    )
