from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from ...config import Settings, get_settings
from .base import BaseCollector, CandidateVideo

logger = logging.getLogger(__name__)


def _to_int(val: Any) -> int:
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return max(0, int(val))
    s = str(val).strip().upper().replace(",", "")
    if not s:
        return 0
    mult = 1
    if s.endswith("K"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1_000_000
        s = s[:-1]
    elif s.endswith("B"):
        mult = 1_000_000_000
        s = s[:-1]
    elif s.endswith("W") or s.endswith("万"):
        mult = 10_000
        s = s[:-1]
    try:
        return max(0, int(float(s) * mult))
    except ValueError:
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else 0


def _parse_duration_str(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        num = int(val)
        return num // 1000 if num > 10_000 else num
    s = str(val).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        try:
            nums = [int(p) for p in parts]
            if len(nums) == 2:
                return nums[0] * 60 + nums[1]
            if len(nums) == 3:
                return nums[0] * 3600 + nums[1] * 60 + nums[2]
        except ValueError:
            return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _first_str(*values: Any) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item.strip():
                    return item.strip()
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    return item["url"].strip()
    return ""


class TikHubCollector(BaseCollector):
    """Unified TikHub collector for TikTok, Instagram Reels, and YouTube Shorts."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base_url = self.settings.tikhub_base_url.rstrip("/")
        self.api_key = self.settings.tikhub_api_key.strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        for attempt in range(3):
            try:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    payload = resp.json()
                    if isinstance(payload, dict):
                        return payload
                if resp.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(1.2 * (attempt + 1))
                    continue
                logger.warning("TikHub %s returned HTTP %s", path, resp.status_code)
                return None
            except Exception as exc:
                logger.warning("TikHub %s attempt %d error: %s", path, attempt + 1, exc)
                await asyncio.sleep(1.0 * (attempt + 1))
        return None

    async def search(
        self,
        platform: str,
        queries: list[str],
        *,
        limit_per_query: int = 12,
    ) -> list[CandidateVideo]:
        if not self.api_key:
            return []

        results: list[CandidateVideo] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0)) as client:
            for query in queries[:3]:
                q = query.strip()
                if not q:
                    continue
                try:
                    if platform == "tiktok":
                        items = await self._search_tiktok(client, q, limit_per_query)
                    elif platform == "instagram":
                        items = await self._search_instagram(client, q, limit_per_query)
                    elif platform == "youtube":
                        items = await self._search_youtube(client, q, limit_per_query)
                    else:
                        items = []
                    results.extend(items)
                except Exception as exc:
                    logger.warning("TikHub %s search '%s' failed: %s", platform, q, exc)
        return results

    async def _search_tiktok(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[CandidateVideo]:
        endpoints = [
            (
                "/api/v1/tiktok/app/v3/fetch_video_search_result",
                {"keyword": query, "offset": 0, "count": limit, "sort_type": 1},
            ),
            (
                "/api/v1/tiktok/app/v3/fetch_general_search_result",
                {"keyword": query, "offset": 0, "count": limit, "sort_type": 1},
            ),
            (
                "/api/v1/tiktok/web/fetch_search_video",
                {"keyword": query, "offset": 0, "count": limit},
            ),
        ]
        for path, params in endpoints:
            payload = await self._request_json(client, path, params)
            if not payload:
                continue
            parsed = self._parse_tiktok_payload(payload)
            if parsed:
                return parsed[:limit]
        return []

    def _parse_tiktok_payload(self, payload: dict[str, Any]) -> list[CandidateVideo]:
        candidates: list[CandidateVideo] = []
        raw_items: list[dict[str, Any]] = []

        def _collect_tiktok_nodes(obj: Any) -> None:
            if isinstance(obj, list):
                for el in obj:
                    _collect_tiktok_nodes(el)
            elif isinstance(obj, dict):
                if "aweme_info" in obj and isinstance(obj["aweme_info"], dict):
                    raw_items.append(obj["aweme_info"])
                    return
                if ("aweme_id" in obj or ("id" in obj and ("statistics" in obj or "stats" in obj))) and (
                    "video" in obj or "desc" in obj
                ):
                    raw_items.append(obj)
                    return
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        _collect_tiktok_nodes(v)

        _collect_tiktok_nodes(payload)
        seen_ids: set[str] = set()
        for aweme in raw_items:
            vid = str(aweme.get("aweme_id") or aweme.get("id") or "").strip()
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            stats = aweme.get("statistics") or aweme.get("stats") or {}
            author = aweme.get("author") or {}
            video_obj = aweme.get("video") or {}
            unique_id = _first_str(author.get("unique_id"), author.get("uniqueId"), "user")
            share_url = _first_str(
                aweme.get("share_url"),
                (aweme.get("share_info") or {}).get("share_url"),
                f"https://www.tiktok.com/@{unique_id}/video/{vid}",
            )
            play_addr = video_obj.get("play_addr") or {}
            cover_obj = video_obj.get("origin_cover") or video_obj.get("cover") or {}
            download_url = _first_str(
                play_addr.get("url_list"),
                video_obj.get("playAddr"),
                video_obj.get("downloadAddr"),
            )
            cover_url = _first_str(
                cover_obj.get("url_list"),
                video_obj.get("cover") if isinstance(video_obj.get("cover"), str) else "",
            )
            desc = _first_str(aweme.get("desc"), aweme.get("title"))
            candidates.append(
                CandidateVideo(
                    platform="tiktok",
                    platform_video_id=vid,
                    video_url=share_url,
                    download_url=download_url or None,
                    cover_url=cover_url or None,
                    author_name=_first_str(author.get("nickname"), unique_id),
                    title=desc[:140],
                    caption=desc,
                    published_at=str(aweme.get("create_time") or aweme.get("createTime") or ""),
                    duration_sec=_parse_duration_str(
                        video_obj.get("duration") or aweme.get("duration")
                    ),
                    views=_to_int(
                        stats.get("play_count") or stats.get("playCount") or aweme.get("play_count")
                    ),
                    likes=_to_int(
                        stats.get("digg_count")
                        or stats.get("diggCount")
                        or stats.get("like_count")
                    ),
                    comments=_to_int(
                        stats.get("comment_count") or stats.get("commentCount")
                    ),
                    shares=_to_int(stats.get("share_count") or stats.get("shareCount")),
                )
            )
        return candidates

    async def _search_instagram(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[CandidateVideo]:
        hashtag = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "", query).lower()
        endpoints = [
            ("/api/v1/instagram/v2/search_reels", {"keyword": query}),
            ("/api/v1/instagram/v2/fetch_hashtag_posts", {"keyword": hashtag or query, "feed_type": "top"}),
            ("/api/v1/instagram/v3/get_hashtag_posts", {"tag": hashtag or query}),
            ("/api/v1/instagram/v1/fetch_hashtag_posts", {"hashtag": hashtag or query}),
        ]
        for path, params in endpoints:
            payload = await self._request_json(client, path, params)
            if not payload:
                continue
            parsed = self._parse_instagram_payload(payload)
            if parsed:
                return parsed[:limit]
        return []

    def _parse_instagram_payload(self, payload: dict[str, Any]) -> list[CandidateVideo]:
        candidates: list[CandidateVideo] = []
        raw_items: list[dict[str, Any]] = []

        def _collect_nodes(obj: Any) -> None:
            if isinstance(obj, list):
                for el in obj:
                    _collect_nodes(el)
            elif isinstance(obj, dict):
                if any(k in obj for k in ("code", "shortcode", "video_versions", "play_count")):
                    raw_items.append(obj)
                for key in ("data", "items", "reels", "medias", "sections", "layout_content", "nodes"):
                    if key in obj:
                        _collect_nodes(obj[key])
                if "media" in obj and isinstance(obj["media"], dict):
                    _collect_nodes(obj["media"])

        _collect_nodes(payload)
        seen_ids: set[str] = set()
        for item in raw_items:
            code = _first_str(item.get("code"), item.get("shortcode"))
            vid = str(item.get("pk") or item.get("id") or code or "").strip()
            if not vid or vid in seen_ids:
                continue
            seen_ids.add(vid)
            video_versions = item.get("video_versions") or []
            download_url = _first_str(
                video_versions,
                item.get("video_url"),
            )
            img_candidates = (item.get("image_versions2") or {}).get("candidates") or []
            cover_url = _first_str(
                img_candidates,
                item.get("thumbnail_url"),
                item.get("display_url"),
            )
            caption_obj = item.get("caption")
            caption_text = (
                caption_obj.get("text", "")
                if isinstance(caption_obj, dict)
                else str(caption_obj or "")
            )
            user = item.get("user") or item.get("owner") or {}
            video_url = (
                f"https://www.instagram.com/reel/{code}/"
                if code
                else _first_str(item.get("url"), f"https://www.instagram.com/p/{vid}/")
            )
            views = _to_int(
                item.get("play_count")
                or item.get("ig_play_count")
                or item.get("view_count")
                or item.get("video_view_count")
            )
            likes = _to_int(item.get("like_count") or item.get("likes"))
            if views == 0 and likes > 0:
                views = likes * 15
            candidates.append(
                CandidateVideo(
                    platform="instagram",
                    platform_video_id=code or vid,
                    video_url=video_url,
                    download_url=download_url or None,
                    cover_url=cover_url or None,
                    author_name=_first_str(user.get("username"), user.get("full_name")),
                    title=caption_text[:140] or f"Instagram Reel {code or vid}",
                    caption=caption_text,
                    published_at=str(item.get("taken_at") or item.get("taken_at_timestamp") or ""),
                    duration_sec=_parse_duration_str(item.get("video_duration")),
                    views=views,
                    likes=likes,
                    comments=_to_int(item.get("comment_count")),
                    shares=_to_int(item.get("reshare_count")),
                )
            )
        return candidates

    async def _search_youtube(
        self, client: httpx.AsyncClient, query: str, limit: int
    ) -> list[CandidateVideo]:
        endpoints = [
            ("/api/v1/youtube/web_v2/get_shorts_search_v2", {"keyword": query, "sort_by": "view_count"}),
            ("/api/v1/youtube/web_v2/get_shorts_search", {"search_query": query}),
            ("/api/v1/youtube/web/search_video", {"search_query": f"{query} shorts"}),
        ]
        for path, params in endpoints:
            payload = await self._request_json(client, path, params)
            if not payload:
                continue
            parsed = self._parse_youtube_payload(payload)
            if parsed:
                return parsed[:limit]
        return []

    def _parse_youtube_payload(self, payload: dict[str, Any]) -> list[CandidateVideo]:
        candidates: list[CandidateVideo] = []
        raw_items: list[dict[str, Any]] = []

        def _collect_yt_nodes(obj: Any) -> None:
            if isinstance(obj, list):
                for el in obj:
                    _collect_yt_nodes(el)
            elif isinstance(obj, dict):
                if any(k in obj for k in ("video_id", "videoId")) and any(
                    k in obj for k in ("title", "headline", "number_of_views", "view_count", "views", "viewCountText")
                ):
                    raw_items.append(obj)
                    return
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        _collect_yt_nodes(v)

        _collect_yt_nodes(payload)
        seen_ids: set[str] = set()
        for item in raw_items:
            vid = _first_str(item.get("video_id"), item.get("videoId"), item.get("id"))
            if not vid or len(vid) > 20 or vid in seen_ids:
                continue
            seen_ids.add(vid)
            dur = _parse_duration_str(
                item.get("video_length") or item.get("duration") or item.get("lengthText")
            )
            is_short = (dur is None or dur <= 75) or "short" in str(item.get("url", "")).lower()
            video_url = (
                f"https://www.youtube.com/shorts/{vid}"
                if is_short
                else f"https://www.youtube.com/watch?v={vid}"
            )
            thumbs = item.get("thumbnails") or []
            cover_url = _first_str(thumbs, item.get("thumbnail"), f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg")
            views = _to_int(
                item.get("number_of_views")
                or item.get("view_count")
                or item.get("views")
                or item.get("viewCountText")
            )
            likes = _to_int(item.get("like_count") or item.get("likes"))
            if likes == 0 and views > 0:
                likes = int(views * 0.04)
            title = _first_str(item.get("title"), item.get("headline"), item.get("description"))
            candidates.append(
                CandidateVideo(
                    platform="youtube",
                    platform_video_id=vid,
                    video_url=video_url,
                    download_url=None,
                    cover_url=cover_url or None,
                    author_name=_first_str(item.get("author"), (item.get("channel") or {}).get("name")),
                    title=title[:140],
                    caption=_first_str(item.get("description"), title),
                    published_at=_first_str(item.get("published_time"), item.get("published_at")),
                    duration_sec=dur,
                    views=views,
                    likes=likes,
                )
            )
        return candidates
