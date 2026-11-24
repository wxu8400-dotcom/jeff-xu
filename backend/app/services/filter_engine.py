from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .collectors.base import CandidateVideo
from .viral_templates import is_cartoon_or_animation_text


@dataclass
class FilterOutcome:
    selected: list[CandidateVideo]
    total_input: int
    deduped_count: int
    relaxed_applied: bool
    note: str


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.isdigit():
        try:
            ts = int(raw)
            if ts > 10**12:
                ts = ts // 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _heat_score(video: CandidateVideo) -> float:
    views_term = math.log10(max(video.views, 0) + 1)
    likes_term = math.log10(max(video.likes, 0) + 1)
    eng = video.engagement_rate()
    return views_term * 0.50 + likes_term * 0.35 + min(eng, 25.0) * 0.15


def run_hard_filter(
    candidates: Iterable[CandidateVideo],
    *,
    min_views: int = 50000,
    min_likes: int = 2000,
    date_range_days: int = 30,
    target_count: int = 5,
    auto_relax: bool = True,
    max_per_platform: int = 10,
    max_total: int = 25,
) -> FilterOutcome:
    raw_list = list(candidates)
    seen: set[tuple[str, str]] = set()
    deduped: list[CandidateVideo] = []
    excluded_cartoon = 0
    for cand in raw_list:
        key = (cand.platform.lower(), str(cand.platform_video_id))
        if key not in seen:
            seen.add(key)
            if is_cartoon_or_animation_text(cand.title, cand.caption):
                excluded_cartoon += 1
                continue
            deduped.append(cand)

    def _apply(v_min: int, l_min: int, days: int) -> list[CandidateVideo]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None
        passed: list[CandidateVideo] = []
        for cand in deduped:
            if cand.duration_sec is not None and not (4 <= cand.duration_sec <= 150):
                continue
            if cand.views < v_min or cand.likes < l_min:
                continue
            if cutoff is not None:
                pub_dt = _parse_iso_datetime(cand.published_at)
                if pub_dt is not None and pub_dt < cutoff:
                    continue
            passed.append(cand)
        return passed

    filtered = _apply(min_views, min_likes, date_range_days)
    relaxed = False
    cartoon_suffix = (
        f"（已自动屏蔽 {excluded_cartoon} 条动漫/卡通/定格动画视频）"
        if excluded_cartoon > 0
        else ""
    )
    note = f"严格阈值（播放 ≥ {min_views:,}，点赞 ≥ {min_likes:,}）筛选后保留 {len(filtered)} 条{cartoon_suffix}"

    if auto_relax and len(filtered) < max(target_count, 3):
        for factor, day_mult in [(0.7, 1.5), (0.4, 2.5), (0.0, 0)]:
            relaxed_v = int(min_views * factor)
            relaxed_l = int(min_likes * factor)
            relaxed_days = int(date_range_days * day_mult) if day_mult > 0 else 0
            attempt = _apply(relaxed_v, relaxed_l, relaxed_days)
            if len(attempt) > len(filtered):
                filtered = attempt
                relaxed = True
                note = (
                    f"严格阈值下候选较少，已自动放宽至（播放 ≥ {relaxed_v:,}，点赞 ≥ {relaxed_l:,}）保留 {len(filtered)} 条{cartoon_suffix}"
                )
            if len(filtered) >= max(target_count * 2, 6):
                break

    by_platform: dict[str, list[CandidateVideo]] = {}
    for cand in filtered:
        by_platform.setdefault(cand.platform, []).append(cand)

    balanced: list[CandidateVideo] = []
    for plat_list in by_platform.values():
        plat_list.sort(key=_heat_score, reverse=True)
        balanced.extend(plat_list[:max_per_platform])

    balanced.sort(key=_heat_score, reverse=True)
    selected = balanced[:max_total]

    return FilterOutcome(
        selected=selected,
        total_input=len(raw_list),
        deduped_count=len(deduped),
        relaxed_applied=relaxed,
        note=note,
    )
