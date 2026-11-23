from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CandidateVideo:
    platform: str  # tiktok | instagram | youtube
    platform_video_id: str
    video_url: str
    title: str = ""
    caption: str = ""
    author_name: str = ""
    cover_url: str | None = None
    download_url: str | None = None
    published_at: str | None = None
    duration_sec: int | None = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0

    def engagement_rate(self) -> float:
        if self.views <= 0:
            return 0.0
        return round((self.likes / self.views) * 100.0, 2)


class BaseCollector(ABC):
    @abstractmethod
    async def search(
        self,
        platform: str,
        queries: list[str],
        *,
        limit_per_query: int = 12,
    ) -> list[CandidateVideo]:
        raise NotImplementedError
