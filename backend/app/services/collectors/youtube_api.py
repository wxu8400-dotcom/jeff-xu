from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from ...config import Settings, get_settings
from .base import BaseCollector, CandidateVideo

logger = logging.getLogger(__name__)


def _parse_iso8601_duration(duration: str) -> int | None:
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return None
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s


class YouTubeOfficialCollector(BaseCollector):
    """Official free YouTube Data API v3 Shorts collector."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.youtube_api_key.strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def search(
        self,
        platform: str,
        queries: list[str],
        *,
        limit_per_query: int = 12,
        date_range_days: int = 30,
    ) -> list[CandidateVideo]:
        if platform != "youtube" or not self.api_key:
            return []

        published_after = (
            datetime.now(timezone.utc) - timedelta(days=max(date_range_days, 7))
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        video_ids: list[str] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            for q in queries[:3]:
                for use_date_filter in (True, False):
                    params = {
                        "part": "id",
                        "q": q,
                        "type": "video",
                        "videoDuration": "short",
                        "order": "viewCount",
                        "maxResults": min(limit_per_query, 15),
                        "key": self.api_key,
                    }
                    if use_date_filter and date_range_days > 0:
                        params["publishedAfter"] = published_after
                    try:
                        resp = await client.get(
                            "https://www.googleapis.com/youtube/v3/search",
                            params=params,
                        )
                        if resp.status_code != 200:
                            logger.warning("YouTube search API HTTP %s: %s", resp.status_code, resp.text[:200])
                            break
                        items = resp.json().get("items", [])
                        added = 0
                        for item in items:
                            vid = (item.get("id") or {}).get("videoId")
                            if vid and vid not in video_ids:
                                video_ids.append(vid)
                                added += 1
                        if added >= 3 or not use_date_filter:
                            break
                    except Exception as exc:
                        logger.warning("YouTube search failed for '%s': %s", q, exc)
                        break

            if not video_ids:
                return []

            results: list[CandidateVideo] = []
            for start in range(0, len(video_ids), 40):
                batch_ids = video_ids[start : start + 40]
                try:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "snippet,statistics,contentDetails",
                            "id": ",".join(batch_ids),
                            "key": self.api_key,
                        },
                    )
                    if resp.status_code != 200:
                        continue
                    for item in resp.json().get("items", []):
                        vid = item.get("id", "")
                        snippet = item.get("snippet") or {}
                        stats = item.get("statistics") or {}
                        details = item.get("contentDetails") or {}
                        dur = _parse_iso8601_duration(details.get("duration", ""))
                        if dur is not None and dur > 75:
                            continue
                        thumbs = snippet.get("thumbnails") or {}
                        cover = (
                            (thumbs.get("high") or {}).get("url")
                            or (thumbs.get("medium") or {}).get("url")
                            or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                        )
                        results.append(
                            CandidateVideo(
                                platform="youtube",
                                platform_video_id=vid,
                                video_url=f"https://www.youtube.com/shorts/{vid}",
                                cover_url=cover,
                                author_name=snippet.get("channelTitle", ""),
                                title=snippet.get("title", ""),
                                caption=snippet.get("description", ""),
                                published_at=snippet.get("publishedAt"),
                                duration_sec=dur,
                                views=int(stats.get("viewCount") or 0),
                                likes=int(stats.get("likeCount") or 0),
                                comments=int(stats.get("commentCount") or 0),
                            )
                        )
                except Exception as exc:
                    logger.warning("YouTube videos.list failed: %s", exc)
            return results

    async def fetch_by_id(self, video_id: str, video_url: str = "") -> CandidateVideo | None:
        """Fetch exact metadata & cover thumbnail for a single YouTube video/Short by ID."""
        if not self.api_key or not video_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0)) as client:
                resp = await client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={
                        "part": "snippet,statistics,contentDetails",
                        "id": video_id,
                        "key": self.api_key,
                    },
                )
                if resp.status_code != 200:
                    return None
                items = resp.json().get("items") or []
                if not items:
                    return None
                item = items[0]
                snippet = item.get("snippet") or {}
                stats = item.get("statistics") or {}
                details = item.get("contentDetails") or {}
                dur = _parse_iso8601_duration(details.get("duration", ""))
                thumbs = snippet.get("thumbnails") or {}
                cover = (
                    (thumbs.get("high") or {}).get("url")
                    or (thumbs.get("medium") or {}).get("url")
                    or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                )
                return CandidateVideo(
                    platform="youtube",
                    platform_video_id=video_id,
                    video_url=video_url or f"https://www.youtube.com/shorts/{video_id}",
                    cover_url=cover,
                    author_name=snippet.get("channelTitle", ""),
                    title=snippet.get("title", ""),
                    caption=snippet.get("description", ""),
                    published_at=snippet.get("publishedAt"),
                    duration_sec=dur,
                    views=int(stats.get("viewCount") or 0),
                    likes=int(stats.get("likeCount") or 0),
                    comments=int(stats.get("commentCount") or 0),
                )
        except Exception as exc:
            logger.warning("YouTube fetch_by_id failed for %s: %s", video_id, exc)
            return None
