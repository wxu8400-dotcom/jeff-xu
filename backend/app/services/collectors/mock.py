from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import BaseCollector, CandidateVideo


class MockCollector(BaseCollector):
    """Deterministic multi-platform mock collector used ONLY when ENABLE_MOCK_MODE=true."""

    async def search(
        self,
        platform: str,
        queries: list[str],
        *,
        limit_per_query: int = 12,
    ) -> list[CandidateVideo]:
        now = datetime.now(timezone.utc)
        q_hint = queries[0] if queries else "viral product"

        data_map: dict[str, list[CandidateVideo]] = {
            "tiktok": [
                CandidateVideo(
                    platform="tiktok",
                    platform_video_id="7410001001",
                    video_url="https://www.tiktok.com/@aestheticfinds/video/7410001001",
                    cover_url="https://placehold.co/360x640/1e293b/38bdf8?text=TikTok+Viral+Unboxing",
                    author_name="@aestheticfinds",
                    title=f"POV: This viral gadget replaced 3 things on my desk ({q_hint})",
                    caption="Wait for the close-up shot! Unboxing this must-have aesthetic gadget #tiktokmademebuyit #amazonfinds",
                    published_at=(now - timedelta(days=3)).isoformat(),
                    duration_sec=24,
                    views=1_850_000,
                    likes=164_000,
                    comments=2_310,
                    shares=18_900,
                ),
                CandidateVideo(
                    platform="tiktok",
                    platform_video_id="7410001002",
                    video_url="https://www.tiktok.com/@aicommercial_lab/video/7410001002",
                    cover_url="https://placehold.co/360x640/312e81/c084fc?text=TikTok+AI+CGI+Ad",
                    author_name="@aicommercial_lab",
                    title="AI CGI 3D Floating Product Commercial Made with Kling AI",
                    caption="Surreal macro AI product reveal in 15 seconds #klingai #aicommercial #productdesign",
                    published_at=(now - timedelta(days=5)).isoformat(),
                    duration_sec=16,
                    views=2_420_000,
                    likes=218_000,
                    comments=4_120,
                    shares=31_400,
                ),
                CandidateVideo(
                    platform="tiktok",
                    platform_video_id="7410001003",
                    video_url="https://www.tiktok.com/@nycstreettalk/video/7410001003",
                    cover_url="https://placehold.co/360x640/334155/f87171?text=Street+Interview",
                    author_name="@nycstreettalk",
                    title="NYC Street Interview asking strangers about their rent",
                    caption="Funny street interview podcast clip #streetinterview #nyc",
                    published_at=(now - timedelta(days=2)).isoformat(),
                    duration_sec=42,
                    views=3_100_000,
                    likes=290_000,
                    comments=5_400,
                    shares=12_000,
                ),
            ],
            "instagram": [
                CandidateVideo(
                    platform="instagram",
                    platform_video_id="C9xViralReel01",
                    video_url="https://www.instagram.com/reel/C9xViralReel01/",
                    cover_url="https://placehold.co/360x640/0f172a/f472b6?text=IG+Reels+Aesthetic",
                    author_name="minimal.tech.daily",
                    title="Aesthetic minimalist desk review — cleanest gadget of 2026",
                    caption="Hands-on close up review with crisp morning light #reels #aesthetic #productreview",
                    published_at=(now - timedelta(days=4)).isoformat(),
                    duration_sec=21,
                    views=980_000,
                    likes=89_500,
                    comments=1_290,
                    shares=14_200,
                ),
                CandidateVideo(
                    platform="instagram",
                    platform_video_id="C9xLowView02",
                    video_url="https://www.instagram.com/reel/C9xLowView02/",
                    cover_url="https://placehold.co/360x640/1e293b/94a3b8?text=Low+Views",
                    author_name="small_account",
                    title="Quick test video",
                    caption="Small test post",
                    published_at=(now - timedelta(days=6)).isoformat(),
                    duration_sec=18,
                    views=1_200,
                    likes=45,
                    comments=2,
                    shares=1,
                ),
            ],
            "youtube": [
                CandidateVideo(
                    platform="youtube",
                    platform_video_id="dQw4Short01",
                    video_url="https://www.youtube.com/shorts/dQw4Short01",
                    cover_url="https://placehold.co/360x640/172554/fb7185?text=YouTube+Shorts+Test",
                    author_name="GadgetLab Shorts",
                    title="3-Second Real Test: Why Everyone Is Obsessed With This Gadget #shorts",
                    caption="Satisfying side-by-side product test & unboxing #shorts #viralgadgets",
                    published_at=(now - timedelta(days=7)).isoformat(),
                    duration_sec=28,
                    views=1_460_000,
                    likes=112_000,
                    comments=1_850,
                    shares=9_200,
                ),
            ],
        }
        return data_map.get(platform, [])[:limit_per_query]
