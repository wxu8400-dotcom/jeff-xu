from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import Settings, get_settings
from ..database import get_session_factory
from ..models import ScanSession, VideoRecord
from ..schemas import (
    PreliminaryScreeningBatch,
    ProductDNA,
    VideoDeepAnalysis,
)
from .ai_client import TokenUsage, UnifiedAIClient, estimate_cost_cny
from .collectors.base import CandidateVideo
from .collectors.mock import MockCollector
from .collectors.tikhub import TikHubCollector
from .collectors.youtube_api import YouTubeOfficialCollector
from .director_memory import load_director_memory_block
from .filter_engine import run_hard_filter
from .product_parser import ParsedProductBundle, _resize_jpeg
from .prompts import (
    build_deep_analysis_prompt,
    build_preliminary_screening_prompt,
    build_product_dna_prompt,
)
from .video_processor import download_and_compress_video, extract_filmstrip_previews
from .viral_templates import (
    is_cartoon_or_animation_text,
    item_matches_same_category,
    normalize_creative_styles,
    resolve_platform_queries,
)

logger = logging.getLogger(__name__)

CN_TZ = timezone(timedelta(hours=8))


def format_history_title(product_name: str, dt: datetime | None = None) -> str:
    ts = (dt or datetime.now(CN_TZ)).astimezone(CN_TZ)
    clean_name = (product_name or "未命名产品").strip()[:80]
    return f"{ts.strftime('%Y-%m-%d %H:%M')} · {clean_name}"


class EventBroker:
    """In-memory SSE pub/sub broker per scan session."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        subs = self._subscribers.get(session_id, [])
        if q in subs:
            subs.remove(q)
        if not subs and session_id in self._subscribers:
            del self._subscribers[session_id]

    def publish(self, session_id: str, event: dict[str, Any]) -> None:
        for q in list(self._subscribers.get(session_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


event_broker = EventBroker()


async def _fetch_cover_thumbnail(url: str | None) -> tuple[bytes, str] | None:
    if not url or not url.startswith("http"):
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 500:
                resized = _resize_jpeg(resp.content, max_side=384, quality=65)
                return resized, "image/jpeg"
    except Exception:
        return None
    return None


def _detect_platform_from_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    if "tiktok" in host or "douyin" in host:
        m = re.search(r"/(?:video|photo|v)/(\d+)", path)
        if not m:
            m = re.search(r"/(\d{15,22})", path)
        return "tiktok", (m.group(1) if m else re.sub(r"\W+", "", path)[-16:] or "tk_link")
    if "instagram" in host or "instagr.am" in host:
        m = re.search(r"/(?:reel|reels|p|tv)/([^/?#]+)", path)
        return "instagram", (m.group(1) if m else re.sub(r"\W+", "", path)[-16:] or "ig_link")
    if "youtube" in host or "youtu.be" in host:
        m = re.search(r"/(?:shorts|live|embed)/([^/?#]+)", path)
        if m:
            return "youtube", m.group(1)
        m2 = re.search(r"[?&]v=([^&]+)", url)
        if m2:
            return "youtube", m2.group(1)
        if "youtu.be" in host and path.strip("/"):
            return "youtube", path.strip("/").split("/")[0]
        return "youtube", "yt_link"
    return "tiktok", re.sub(r"\W+", "", url)[-16:] or "custom_link"


async def _expand_short_url(url: str) -> str:
    """Resolve mobile short redirect links (vt.tiktok.com / vm.tiktok.com / tiktok.com/t/ / instagr.am / youtu.be)."""
    lower = url.lower()
    is_short = any(
        h in lower
        for h in (
            "vt.tiktok.com",
            "vm.tiktok.com",
            "tiktok.com/t/",
            "v.douyin.com",
            "instagr.am",
            "youtu.be/",
        )
    )
    if not is_short:
        return url
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=5.0),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                )
            },
        ) as client:
            resp = await client.get(url)
            final = str(resp.url)
            if final.startswith("http"):
                return final
    except Exception as exc:
        logger.debug("Short URL expansion skipped for %s: %s", url, exc)
    return url


async def _resolve_direct_url_candidate(
    raw_url: str,
    cfg: Settings,
    warnings: list[str],
) -> CandidateVideo:
    """Resolve a user-pasted TikTok / Instagram / YouTube link into real metadata + direct MP4 URL
    using TikHub single-video APIs and YouTube Official API so native video analysis never runs blind."""
    clean_u = raw_url.strip()
    plat, vid = _detect_platform_from_url(clean_u)

    if cfg.enable_mock_mode:
        return CandidateVideo(
            platform=plat,
            platform_video_id=vid,
            video_url=clean_u,
            title=f"{plat.upper()} 指定视频 ({vid})",
        )

    expanded = await _expand_short_url(clean_u)
    exp_plat, exp_vid = _detect_platform_from_url(expanded)
    if exp_plat:
        plat = exp_plat
    if exp_vid and exp_vid not in ("tk_link", "ig_link", "yt_link", "custom_link"):
        vid = exp_vid

    tikhub = TikHubCollector(cfg)
    yt_official = YouTubeOfficialCollector(cfg)

    resolved: CandidateVideo | None = None
    if tikhub.is_configured():
        try:
            # Pass original URL first (TikHub share_url/hybrid handles short URLs natively),
            # and fallback to expanded canonical URL if different.
            resolved = await tikhub.fetch_by_url(
                clean_u, platform_hint=plat, video_id_hint=vid
            )
            if (resolved is None or not resolved.download_url) and expanded != clean_u:
                alt = await tikhub.fetch_by_url(
                    expanded, platform_hint=plat, video_id_hint=vid
                )
                if alt and (resolved is None or alt.download_url):
                    resolved = alt
        except Exception as exc:
            logger.warning("TikHub direct URL resolve failed for %s: %s", clean_u, exc)

    if plat == "youtube" and vid and vid != "yt_link":
        if (resolved is None or not resolved.title or not resolved.cover_url) and yt_official.is_configured():
            try:
                yt_meta = await yt_official.fetch_by_id(vid, video_url=expanded or clean_u)
                if yt_meta:
                    if resolved is None:
                        resolved = yt_meta
                    else:
                        if not resolved.title or resolved.title.startswith("YOUTUBE"):
                            resolved.title = yt_meta.title
                        if not resolved.caption:
                            resolved.caption = yt_meta.caption
                        if not resolved.cover_url:
                            resolved.cover_url = yt_meta.cover_url
                        if not resolved.author_name:
                            resolved.author_name = yt_meta.author_name
                        if resolved.views == 0:
                            resolved.views = yt_meta.views
                        if resolved.likes == 0:
                            resolved.likes = yt_meta.likes
                        if resolved.duration_sec is None:
                            resolved.duration_sec = yt_meta.duration_sec
            except Exception as exc:
                logger.warning("YouTube official fetch_by_id failed for %s: %s", vid, exc)

    if resolved is not None:
        if not resolved.video_url:
            resolved.video_url = expanded or clean_u
        if plat == "youtube" and not resolved.cover_url and resolved.platform_video_id:
            resolved.cover_url = f"https://i.ytimg.com/vi/{resolved.platform_video_id}/hqdefault.jpg"
        return resolved

    fallback_cover = (
        f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        if plat == "youtube" and vid and vid != "yt_link"
        else None
    )
    warnings.append(
        f"链接 {clean_u[:56]} 未从高速通道解析到无水印直链，将尝试备用下载器抓取画面"
    )
    return CandidateVideo(
        platform=plat,
        platform_video_id=vid,
        video_url=expanded or clean_u,
        cover_url=fallback_cover,
        title=f"{plat.upper()} 指定视频 ({vid})",
    )


def _update_session(
    session_id: str,
    *,
    status: str | None = None,
    progress_percent: int | None = None,
    progress_message: str | None = None,
    error_message: str | None = None,
    product_name: str | None = None,
    history_title: str | None = None,
    product_dna: dict[str, Any] | None = None,
    funnel_stats: dict[str, Any] | None = None,
) -> None:
    factory = get_session_factory()
    db = factory()
    try:
        sess = db.get(ScanSession, session_id)
        if not sess:
            return
        if status is not None:
            sess.status = status
        if progress_percent is not None:
            sess.progress_percent = progress_percent
        if progress_message is not None:
            sess.progress_message = progress_message
        if error_message is not None:
            sess.error_message = error_message
        if product_name is not None:
            sess.product_name = product_name
        if history_title is not None:
            sess.history_title = history_title
        if product_dna is not None:
            sess.product_dna = product_dna
        if funnel_stats is not None:
            sess.funnel_stats = dict(funnel_stats)
        db.commit()

        event_broker.publish(
            session_id,
            {
                "session_id": session_id,
                "status": sess.status,
                "progress_percent": sess.progress_percent,
                "progress_message": sess.progress_message,
                "error_message": sess.error_message,
                "product_name": sess.product_name,
                "history_title": sess.history_title,
                "funnel_stats": sess.funnel_stats,
            },
        )
    finally:
        db.close()


async def run_radar_pipeline(
    *,
    session_id: str,
    product_bundle: ParsedProductBundle,
    product_name_override: str,
    user_instruction: str,
    platforms: list[str],
    filter_config: dict[str, Any],
    direct_urls: list[str] | None = None,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    ai = UnifiedAIClient(cfg)
    total_usage = TokenUsage()
    stats: dict[str, Any] = {
        "collected": 0,
        "after_hard_filter": 0,
        "after_screening": 0,
        "analyzed": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_cny": 0.0,
        "warnings": [],
    }

    def _sync_tokens() -> None:
        stats["input_tokens"] = total_usage.input_tokens
        stats["output_tokens"] = total_usage.output_tokens
        model_name = (
            cfg.gemini_deep_model
            if cfg.ai_provider == "gemini"
            else cfg.openai_deep_model
        )
        stats["estimated_cost_cny"] = estimate_cost_cny(
            total_usage.input_tokens, total_usage.output_tokens, model_name
        )

    try:
        # === STAGE 0: Product DNA Extraction (Runs Once) ===
        _update_session(
            session_id,
            status="extracting_product",
            progress_percent=10,
            progress_message="阶段 1/5：正在解析上传的产品资料并提炼《产品基因卡》...",
            funnel_stats=stats,
        )
        search_strategy = str(filter_config.get("search_strategy", "cross_category"))
        dna_prompt = build_product_dna_prompt(
            extracted_text=product_bundle.combined_text,
            user_instruction=user_instruction,
            product_name_override=product_name_override,
            search_strategy=search_strategy,
        )
        product_dna, dna_usage = await ai.generate_structured(
            prompt=dna_prompt,
            schema_cls=ProductDNA,
            tier="fast",
            images=product_bundle.ai_images,
            mock_context={
                "product_name_override": product_name_override,
                "extracted_text": product_bundle.combined_text,
            },
        )
        total_usage.add(dna_usage)
        _sync_tokens()

        final_product_name = (
            product_name_override.strip() or product_dna.product_name.strip() or "未命名产品"
        )
        product_dna.product_name = final_product_name
        creative_styles = normalize_creative_styles(filter_config.get("creative_styles"))
        product_dna.search_queries = resolve_platform_queries(
            product_dna=product_dna,
            search_strategy=search_strategy,
            creative_styles=creative_styles,
            user_instruction=user_instruction,
        )
        new_history_title = format_history_title(final_product_name)

        _update_session(
            session_id,
            product_name=final_product_name,
            history_title=new_history_title,
            product_dna=product_dna.model_dump(),
            progress_percent=22,
            progress_message=(
                f"《产品基因卡》生成完成：{final_product_name}（已启用纯跨品类爆款视觉模板词，与原产品解耦）"
                if search_strategy == "cross_category"
                else f"《产品基因卡》生成完成：{final_product_name}"
            ),
            funnel_stats=stats,
        )

        # === Branch: Direct URLs Mode vs 3-Platform Radar Mode ===
        if direct_urls:
            clean_urls = [u.strip() for u in direct_urls[:5] if u.strip()]
            _update_session(
                session_id,
                status="collecting",
                progress_percent=34,
                progress_message=f"正在通过高速通道解析你上传的 {len(clean_urls)} 条 TK / INS / YT 视频链接与无水印片源...",
                funnel_stats=stats,
            )
            selected_for_deep: list[tuple[CandidateVideo, int, str]] = []
            for idx_u, raw_url in enumerate(clean_urls, start=1):
                cand = await _resolve_direct_url_candidate(raw_url, cfg, stats["warnings"])
                selected_for_deep.append((cand, 90, "用户指定直拆视频"))
                _update_session(
                    session_id,
                    status="collecting",
                    progress_percent=34 + int((idx_u / max(len(clean_urls), 1)) * 16),
                    progress_message=(
                        f"已解析链接 {idx_u}/{len(clean_urls)}（[{cand.platform.upper()}] "
                        f"{'已获无水印片源' if cand.download_url else '准备备用抓取'}）：{cand.title[:28]}"
                    ),
                    funnel_stats=stats,
                )
            stats["collected"] = len(selected_for_deep)
            stats["after_hard_filter"] = len(selected_for_deep)
            stats["after_screening"] = len(selected_for_deep)
            _update_session(
                session_id,
                status="analyzing",
                progress_percent=52,
                progress_message=f"链接解析完毕，开始下载画面并深度 1:1 拆解 {len(selected_for_deep)} 条视频...",
                funnel_stats=stats,
            )
        else:
            # === STAGE 1: Real-Time 3-Platform Collection (0 Token) ===
            _update_session(
                session_id,
                status="collecting",
                progress_percent=30,
                progress_message="阶段 2/5：正在并发实时搜索 TikTok / Instagram / YouTube 爆款短视频（0 Token）...",
                funnel_stats=stats,
            )
            collected = await _collect_from_platforms(
                platforms=platforms,
                product_dna=product_dna,
                filter_config=filter_config,
                cfg=cfg,
                warnings=stats["warnings"],
            )
            stats["collected"] = len(collected)
            plat_counts: dict[str, int] = {}
            for c in collected:
                plat_counts[c.platform] = plat_counts.get(c.platform, 0) + 1
            stats["platform_counts"] = plat_counts
            plat_summary = " / ".join(f"{k.upper()}:{v}条" for k, v in plat_counts.items()) or "无"

            if not collected:
                _update_session(
                    session_id,
                    status="completed",
                    progress_percent=100,
                    progress_message="未搜索到候选视频，请检查 TikHub 余额/API Key 或查看上方提示信息。",
                    funnel_stats=stats,
                )
                return

            # === STAGE 2: Pure-Code Hard Metric Filter (0 Token) ===
            _update_session(
                session_id,
                status="filtering",
                progress_percent=42,
                progress_message=f"阶段 3/5：已抓取 {len(collected)} 条（{plat_summary}），正在执行 0-Token 播放/点赞过滤...",
                funnel_stats=stats,
            )
            target_count = max(1, min(int(filter_config.get("target_count", 5)), 10))
            filter_out = run_hard_filter(
                collected,
                min_views=int(filter_config.get("min_views", 50000)),
                min_likes=int(filter_config.get("min_likes", 2000)),
                date_range_days=int(filter_config.get("date_range_days", 30)),
                target_count=target_count,
                auto_relax=bool(filter_config.get("auto_relax", True)),
            )
            stats["after_hard_filter"] = len(filter_out.selected)
            if filter_out.relaxed_applied:
                stats["warnings"].append(filter_out.note)

            if not filter_out.selected:
                _update_session(
                    session_id,
                    status="completed",
                    progress_percent=100,
                    progress_message="过滤后无满足播放/点赞阈值的视频，请适当降低阈值后重试。",
                    funnel_stats=stats,
                )
                return

            # === STAGE 3: Low-Cost Replaceability Screening (Text + Low-Res Cover ONLY) ===
            _update_session(
                session_id,
                status="screening",
                progress_percent=54,
                progress_message=f"阶段 4/5：正在对 {len(filter_out.selected)} 条高热候选执行低成本「爆款视觉与可替换性」初筛（不下载视频）...",
                funnel_stats=stats,
            )
            scored_candidates = await _screen_replaceability(
                ai=ai,
                product_dna=product_dna,
                user_instruction=user_instruction,
                candidates=filter_out.selected,
                total_usage=total_usage,
                is_mock=cfg.enable_mock_mode,
                search_strategy=search_strategy,
            )
            _sync_tokens()

            selected_for_deep, excluded_same_cat = select_candidates_for_deep_analysis(
                scored_candidates=scored_candidates,
                product_dna=product_dna,
                search_strategy=search_strategy,
                target_count=target_count,
            )
            if excluded_same_cat > 0:
                stats["warnings"].append(
                    f"跨品类严格模式：已自动过滤 {excluded_same_cat} 条同品类产品视频，仅保留跨品类爆款视觉模板"
                )
            stats["after_screening"] = len(selected_for_deep)

            if not selected_for_deep:
                _update_session(
                    session_id,
                    status="completed",
                    progress_percent=100,
                    progress_message=f"已抓取 {stats['collected']} 条（{plat_summary}），但本轮初筛未找到满足条件的跨品类高可替换爆款。建议切换创意模板风格或重试。",
                    funnel_stats=stats,
                )
                return

        # === STAGE 4: Native Video Deep Analysis & Prompt Generation (Top N ONLY) ===
        total_deep = len(selected_for_deep)
        factory = get_session_factory()

        mem_db = factory()
        try:
            director_memory_block = load_director_memory_block(
                mem_db,
                product_name=product_dna.product_name,
                category=product_dna.category,
            )
        finally:
            mem_db.close()

        for idx, (cand, prelim_score, prelim_item) in enumerate(selected_for_deep, start=1):
            pct = 60 + int(((idx - 1) / max(total_deep, 1)) * 35)
            _update_session(
                session_id,
                status="analyzing",
                progress_percent=pct,
                progress_message=f"阶段 5/5：正在深度拆解第 {idx}/{total_deep} 条高可替换爆款（[{cand.platform.upper()}] {cand.title[:28]}）...",
                funnel_stats=stats,
            )

            compressed_video: bytes | None = None
            cover_images: list[tuple[bytes, str]] = []
            analysis_mode = "native_video"

            if not cfg.enable_mock_mode:
                compressed_video = await download_and_compress_video(
                    video_url=cand.video_url,
                    download_url=cand.download_url,
                )
                if compressed_video is None:
                    analysis_mode = "fallback_frames"
                    cov = await _fetch_cover_thumbnail(cand.cover_url)
                    if cov:
                        cover_images.append(cov)
            else:
                analysis_mode = "native_video"

            video_meta = {
                "platform": cand.platform,
                "video_url": cand.video_url,
                "title": cand.title,
                "caption": cand.caption[:500],
                "author_name": cand.author_name,
                "duration_sec": cand.duration_sec,
                "views": cand.views,
                "likes": cand.likes,
                "preliminary_replaceability_score": prelim_score,
                "original_featured_item": prelim_item,
            }
            deep_prompt = build_deep_analysis_prompt(
                product_dna=product_dna,
                user_instruction=user_instruction,
                video_meta=video_meta,
                analysis_mode=analysis_mode,
                director_memory_block=director_memory_block,
            )

            try:
                deep_res, v_usage = await ai.generate_structured(
                    prompt=deep_prompt,
                    schema_cls=VideoDeepAnalysis,
                    tier="deep",
                    # Pass ONLY original video / cover frames so AI faithfully transcribes the
                    # original video without prematurely hallucinating the user's product!
                    images=cover_images if compressed_video is None else [],
                    video_bytes=compressed_video,
                    mock_context={
                        "product_dna": product_dna,
                        "video_meta": video_meta,
                    },
                )
            except Exception as exc:
                logger.exception("Deep analysis failed for %s: %s", cand.video_url, exc)
                stats["warnings"].append(f"视频 {cand.platform_video_id} 拆解失败：{exc}")
                continue

            # Populate genuine filmstrip previews (starting from 0.15s opening frame!) and
            # ensure current_master_prompt_cn/en are initialized cleanly from original_video_prompt.
            if compressed_video:
                previews = await asyncio.to_thread(
                    extract_filmstrip_previews, compressed_video, 6
                )
                if previews:
                    deep_res.director_plan.keyframe_previews = previews
            elif cover_images:
                import base64 as _b64

                deep_res.director_plan.keyframe_previews = [
                    f"data:{mime};base64,{_b64.b64encode(raw).decode('ascii')}"
                    for raw, mime in cover_images[:1]
                ]

            if not deep_res.director_plan.original_video_prompt_cn:
                deep_res.director_plan.original_video_prompt_cn = (
                    deep_res.director_plan.original_plot_summary
                    or "；".join(s.original_visual for s in deep_res.storyboard if s.original_visual)
                )
            if not deep_res.director_plan.current_master_prompt_cn:
                deep_res.director_plan.current_master_prompt_cn = (
                    deep_res.director_plan.original_video_prompt_cn
                )
            if not deep_res.director_plan.current_master_prompt_en:
                deep_res.director_plan.current_master_prompt_en = (
                    deep_res.director_plan.original_video_prompt_en
                )

            total_usage.add(v_usage)
            _sync_tokens()

            db = factory()
            try:
                record = VideoRecord(
                    session_id=session_id,
                    platform=cand.platform,
                    platform_video_id=cand.platform_video_id,
                    video_url=cand.video_url,
                    download_url=cand.download_url,
                    cover_url=cand.cover_url,
                    author_name=cand.author_name,
                    title=cand.title or cand.platform_video_id,
                    published_at=cand.published_at,
                    duration_sec=cand.duration_sec,
                    views=cand.views,
                    likes=cand.likes,
                    comments=cand.comments,
                    shares=cand.shares,
                    engagement_rate=cand.engagement_rate(),
                    is_ai_generated=deep_res.is_ai_generated,
                    ai_confidence=deep_res.ai_confidence,
                    replaceability_score=deep_res.replaceability.score,
                    original_featured_item=deep_res.replaceability.original_featured_item
                    or prelim_item,
                    analysis_mode=analysis_mode,
                    analysis_json=deep_res.model_dump(),
                    token_usage=v_usage.to_dict(),
                )
                db.add(record)
                db.commit()
            finally:
                db.close()

            stats["analyzed"] += 1
            _update_session(
                session_id,
                progress_percent=60 + int((idx / max(total_deep, 1)) * 35),
                progress_message=f"已完成第 {idx}/{total_deep} 条爆款视频拆解与提示词生成",
                funnel_stats=stats,
            )

        _update_session(
            session_id,
            status="completed",
            progress_percent=100,
            progress_message=(
                f"扫描完成！共抓取 {stats['collected']} 条，经四级漏斗精准收录 {stats['analyzed']} 条高可替换爆款，"
                f"预估成本 ¥{stats['estimated_cost_cny']:.4f}"
            ),
            funnel_stats=stats,
        )
    except Exception as exc:
        logger.exception("Radar pipeline crashed for session %s: %s", session_id, exc)
        _update_session(
            session_id,
            status="failed",
            progress_percent=100,
            progress_message=f"扫描异常中断：{exc}",
            error_message=str(exc),
            funnel_stats=stats,
        )


async def _collect_from_platforms(
    *,
    platforms: list[str],
    product_dna: ProductDNA,
    filter_config: dict[str, Any],
    cfg: Settings,
    warnings: list[str],
) -> list[CandidateVideo]:
    if cfg.enable_mock_mode:
        mock = MockCollector()
        tasks = [
            mock.search(p, _queries_for(product_dna, p), limit_per_query=12)
            for p in platforms
        ]
        nested = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[CandidateVideo] = []
        for item in nested:
            if isinstance(item, list):
                out.extend(item)
        return out

    tikhub = TikHubCollector(cfg)
    yt_official = YouTubeOfficialCollector(cfg)

    async def _run_one(plat: str) -> list[CandidateVideo]:
        queries = _queries_for(product_dna, plat)
        if plat == "youtube" and yt_official.is_configured():
            res = await yt_official.search(
                "youtube",
                queries,
                limit_per_query=12,
                date_range_days=int(filter_config.get("date_range_days", 30)),
            )
            if res:
                return res
        if tikhub.is_configured():
            return await tikhub.search(plat, queries, limit_per_query=12)
        warnings.append(f"{plat.upper()} 未配置采集 Key（请填写 TIKHUB_API_KEY）")
        return []

    nested = await asyncio.gather(
        *[_run_one(p) for p in platforms], return_exceptions=True
    )
    collected: list[CandidateVideo] = []
    for plat, res in zip(platforms, nested):
        if isinstance(res, Exception):
            warnings.append(f"{plat.upper()} 采集出错：{res}")
        elif isinstance(res, list):
            collected.extend(res)
    return collected


def _queries_for(dna: ProductDNA, platform: str) -> list[str]:
    q_map = {
        "tiktok": dna.search_queries.tiktok,
        "instagram": dna.search_queries.instagram,
        "youtube": dna.search_queries.youtube,
    }
    queries = [q for q in (q_map.get(platform) or []) if q.strip()]
    if not queries:
        queries = ["fooh cgi", "3d product animation", "creative commercial"]
    return queries[:3]


class _ScreenedCandidate:
    __slots__ = (
        "candidate",
        "preliminary_score",
        "visual_creativity_score",
        "is_same_category",
        "is_replaceable",
        "original_featured_item",
        "is_cartoon_or_animation",
        "has_realistic_human",
    )

    def __init__(
        self,
        *,
        candidate: CandidateVideo,
        preliminary_score: int,
        visual_creativity_score: int,
        is_same_category: bool,
        is_replaceable: bool,
        original_featured_item: str,
        is_cartoon_or_animation: bool = False,
        has_realistic_human: bool = True,
    ) -> None:
        self.candidate = candidate
        self.preliminary_score = preliminary_score
        self.visual_creativity_score = visual_creativity_score
        self.is_same_category = is_same_category
        self.is_replaceable = is_replaceable
        self.original_featured_item = original_featured_item
        self.is_cartoon_or_animation = is_cartoon_or_animation
        self.has_realistic_human = has_realistic_human

    @property
    def composite_score(self) -> int:
        return int(round(self.visual_creativity_score * 0.55 + self.preliminary_score * 0.45))


def select_candidates_for_deep_analysis(
    *,
    scored_candidates: list[_ScreenedCandidate],
    product_dna: ProductDNA,
    search_strategy: str,
    target_count: int,
) -> tuple[list[tuple[CandidateVideo, int, str]], int]:
    """Select top candidates for Stage 4 deep analysis.

    Always strictly excludes cartoons / anime / 3D dolls / claymation / stop-motion,
    prioritizing live-action real-person and photorealistic AI human short videos.

    In `cross_category` mode:
    - Strictly filters out candidates whose original featured item belongs to the same
      category as the uploaded product (both via AI flag and deterministic item check).
    - Ranks by realistic-human preference + combined viral visual creativity & replaceability score.
    - Balances across platforms (round-robin top from each platform first) so multi-platform
      scans don't get monopolized by a single platform.
    """
    qualified = [
        sc
        for sc in scored_candidates
        if sc.preliminary_score >= 60
        and sc.is_replaceable
        and not sc.is_cartoon_or_animation
        and not is_cartoon_or_animation_text(sc.candidate.title, sc.candidate.caption)
    ]
    excluded_same_cat = 0

    if search_strategy == "cross_category":
        cross_pool: list[_ScreenedCandidate] = []
        for sc in qualified:
            same_cat = sc.is_same_category or item_matches_same_category(
                sc.original_featured_item, product_dna
            )
            if same_cat:
                excluded_same_cat += 1
            else:
                cross_pool.append(sc)
        pool = cross_pool
    else:
        pool = qualified

    if not pool:
        return [], excluded_same_cat

    rank_key = (
        (
            lambda sc: (
                1 if sc.has_realistic_human else 0,
                sc.composite_score,
                sc.preliminary_score,
                sc.candidate.views,
            )
        )
        if search_strategy == "cross_category"
        else (
            lambda sc: (
                1 if sc.has_realistic_human else 0,
                sc.preliminary_score,
                sc.visual_creativity_score,
                sc.candidate.views,
            )
        )
    )

    by_platform: dict[str, list[_ScreenedCandidate]] = {}
    for sc in pool:
        by_platform.setdefault(sc.candidate.platform, []).append(sc)
    for plat_list in by_platform.values():
        plat_list.sort(key=rank_key, reverse=True)

    # Round-robin top pick per platform (ordered by each platform's best score) for diversity
    chosen: list[_ScreenedCandidate] = []
    chosen_ids: set[tuple[str, str]] = set()
    plat_order = sorted(
        by_platform.keys(),
        key=lambda p: rank_key(by_platform[p][0]),
        reverse=True,
    )
    for plat in plat_order:
        if len(chosen) >= target_count:
            break
        top_item = by_platform[plat][0]
        chosen.append(top_item)
        chosen_ids.add((top_item.candidate.platform, top_item.candidate.platform_video_id))

    # Fill remaining slots globally by highest rank
    remaining = sorted(pool, key=rank_key, reverse=True)
    for sc in remaining:
        if len(chosen) >= target_count:
            break
        key = (sc.candidate.platform, sc.candidate.platform_video_id)
        if key in chosen_ids:
            continue
        chosen.append(sc)
        chosen_ids.add(key)

    chosen.sort(key=rank_key, reverse=True)
    result = [
        (
            sc.candidate,
            sc.composite_score if search_strategy == "cross_category" else sc.preliminary_score,
            sc.original_featured_item,
        )
        for sc in chosen[:target_count]
    ]
    return result, excluded_same_cat


async def _screen_replaceability(
    *,
    ai: UnifiedAIClient,
    product_dna: ProductDNA,
    user_instruction: str,
    candidates: list[CandidateVideo],
    total_usage: TokenUsage,
    is_mock: bool,
    search_strategy: str = "cross_category",
) -> list[_ScreenedCandidate]:
    cand_map = {f"{c.platform}:{c.platform_video_id}": c for c in candidates}
    scored: list[_ScreenedCandidate] = []

    batch_size = 5
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        payload_list: list[dict[str, Any]] = []
        cover_images: list[tuple[bytes, str]] = []

        for cand in batch:
            cid = f"{cand.platform}:{cand.platform_video_id}"
            has_cover = False
            if not is_mock and cand.cover_url:
                thumb = await _fetch_cover_thumbnail(cand.cover_url)
                if thumb:
                    cover_images.append(thumb)
                    has_cover = True
            payload_list.append(
                {
                    "candidate_id": cid,
                    "platform": cand.platform,
                    "title": cand.title[:160],
                    "caption": cand.caption[:240],
                    "duration_sec": cand.duration_sec,
                    "views": cand.views,
                    "likes": cand.likes,
                    "has_cover": has_cover,
                }
            )

        prompt = build_preliminary_screening_prompt(
            product_dna=product_dna,
            user_instruction=user_instruction,
            candidates=payload_list,
            search_strategy=search_strategy,
        )
        batch_res, usage = await ai.generate_structured(
            prompt=prompt,
            schema_cls=PreliminaryScreeningBatch,
            tier="fast",
            images=cover_images,
            mock_context={"candidates": payload_list},
        )
        total_usage.add(usage)

        for item in batch_res.results:
            cand = cand_map.get(item.candidate_id)
            if cand:
                scored.append(
                    _ScreenedCandidate(
                        candidate=cand,
                        preliminary_score=item.preliminary_score,
                        visual_creativity_score=item.visual_creativity_score,
                        is_same_category=item.is_same_category,
                        is_replaceable=item.is_replaceable,
                        original_featured_item=item.original_featured_item,
                        is_cartoon_or_animation=item.is_cartoon_or_animation,
                        has_realistic_human=item.has_realistic_human,
                    )
                )

    return scored
