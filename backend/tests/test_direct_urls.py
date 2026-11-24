from __future__ import annotations

import asyncio
import time

from app.config import Settings
from app.routers.scans import _extract_urls_from_text
from app.services.collectors.tikhub import TikHubCollector
from app.services.pipeline import _detect_platform_from_url, _resolve_direct_url_candidate


def _wait_scan_done(client, session_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/api/scans/{session_id}").json()
        if detail["status"] in ("completed", "failed"):
            return detail
        time.sleep(0.1)
    raise AssertionError("Scan did not complete in time")


def test_extract_urls_from_mobile_share_texts_and_detect_platforms():
    raw = """
    这个沙发广告太绝了！https://vt.tiktok.com/ZS2abcXYZ/ 赶紧看！
    Check out this reel: https://www.instagram.com/reel/DRhvwVLAHAG/?igsh=abc,
    https://youtube.com/shorts/dQw4w9WgXcQ?si=999
    """
    urls = _extract_urls_from_text(raw)
    assert urls == [
        "https://vt.tiktok.com/ZS2abcXYZ/",
        "https://www.instagram.com/reel/DRhvwVLAHAG/?igsh=abc",
        "https://youtube.com/shorts/dQw4w9WgXcQ?si=999",
    ]

    assert _detect_platform_from_url("https://www.tiktok.com/@creator/video/7412345678901234567") == (
        "tiktok",
        "7412345678901234567",
    )
    assert _detect_platform_from_url("https://vt.tiktok.com/ZS2abcXYZ/")[0] == "tiktok"
    assert _detect_platform_from_url("https://www.instagram.com/reels/DRhvwVLAHAG/") == (
        "instagram",
        "DRhvwVLAHAG",
    )
    assert _detect_platform_from_url("https://youtu.be/dQw4w9WgXcQ") == (
        "youtube",
        "dQw4w9WgXcQ",
    )
    assert _detect_platform_from_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ") == (
        "youtube",
        "dQw4w9WgXcQ",
    )


def test_tikhub_single_url_payload_parsers_for_tk_ins_yt():
    collector = TikHubCollector(Settings(TIKHUB_API_KEY="test-key"))

    # 1) TikTok hybrid/video_data response
    tk_cand = collector._parse_hybrid_single_payload(
        {
            "code": 200,
            "data": {
                "aweme_id": "7412345678901234567",
                "desc": "Real person modern living room makeover",
                "share_url": "https://www.tiktok.com/@home/video/7412345678901234567",
                "duration": 18000,
                "author": {"nickname": "HomeStudio", "unique_id": "homestudio"},
                "statistics": {"play_count": 1200000, "digg_count": 85000},
                "video_data": {
                    "nwm_video_url_HQ": "https://cdn.tiktok.com/no_watermark_hq.mp4"
                },
                "cover_data": {
                    "origin_cover": {"url_list": ["https://cdn.tiktok.com/cover.jpg"]}
                },
            },
        },
        "https://vt.tiktok.com/ZS2abcXYZ/",
    )
    assert tk_cand is not None
    assert tk_cand.platform == "tiktok"
    assert tk_cand.download_url == "https://cdn.tiktok.com/no_watermark_hq.mp4"
    assert tk_cand.cover_url == "https://cdn.tiktok.com/cover.jpg"
    assert tk_cand.views == 1200000
    assert tk_cand.duration_sec == 18

    # 2) Instagram GraphQL xdt_shortcode_media response
    ig_list = collector._parse_instagram_payload(
        {
            "code": 200,
            "data": {
                "xdt_shortcode_media": {
                    "shortcode": "DRhvwVLAHAG",
                    "video_url": "https://scontent.cdninstagram.com/v/reel.mp4",
                    "display_url": "https://scontent.cdninstagram.com/v/cover.jpg",
                    "video_play_count": 560000,
                    "edge_media_preview_like": {"count": 29000},
                    "edge_media_to_caption": {
                        "edges": [{"node": {"text": "Cinematic sofa reveal"}}]
                    },
                    "owner": {"username": "design_reel"},
                }
            },
        }
    )
    assert len(ig_list) == 1
    assert ig_list[0].platform == "instagram"
    assert ig_list[0].platform_video_id == "DRhvwVLAHAG"
    assert ig_list[0].download_url == "https://scontent.cdninstagram.com/v/reel.mp4"
    assert ig_list[0].views == 560000

    # 3) YouTube web_v2/get_video_info_v2 response with progressive MP4 format
    yt_cand = collector._parse_youtube_single_payload(
        {
            "code": 200,
            "data": {
                "video_id": "dQw4w9WgXcQ",
                "title": "Luxury Lifestyle Commercial",
                "view_count": "890000",
                "like_count": "42000",
                "length_seconds": 25,
                "streamingData": {
                    "formats": [
                        {
                            "itag": 18,
                            "mimeType": 'video/mp4; codecs="avc1.42001E"',
                            "height": 360,
                            "audioQuality": "AUDIO_QUALITY_LOW",
                            "url": "https://rr1.googlevideo.com/videoplayback?itag=18",
                        }
                    ]
                },
            },
        },
        "dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    )
    assert yt_cand is not None
    assert yt_cand.platform == "youtube"
    assert yt_cand.download_url == "https://rr1.googlevideo.com/videoplayback?itag=18"
    assert yt_cand.cover_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert yt_cand.views == 890000


def test_direct_urls_endpoint_accepts_share_texts_for_all_three_platforms(make_client):
    with make_client(password="", mock_mode=True) as client:
        resp = client.post(
            "/api/scans/analyze-urls",
            data={
                "product_name_override": "cc 沙发",
                "product_text": "焦糖色现代真皮双人沙发",
                "urls": (
                    "看这条爆款 https://vt.tiktok.com/ZS2abcXYZ/\n"
                    "https://www.instagram.com/reel/DRhvwVLAHAG/\n"
                    "https://www.youtube.com/shorts/dQw4w9WgXcQ"
                ),
            },
        )
        assert resp.status_code == 200
        detail = _wait_scan_done(client, resp.json()["session_id"])
        assert detail["status"] == "completed"
        assert len(detail["videos"]) == 3
        platforms = {v["platform"] for v in detail["videos"]}
        assert platforms == {"tiktok", "instagram", "youtube"}
