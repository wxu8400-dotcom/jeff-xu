from __future__ import annotations

import io
import time

from PIL import Image

from app.config import Settings
from app.services.media_generator import _build_gemini_image_client, build_kling_auth_token
from app.services.video_processor import is_ffmpeg_available
from app.services.video_stitcher import image_to_motion_clip


def _make_sample_jpg() -> bytes:
    img = Image.new("RGB", (320, 320), (240, 244, 248))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _wait_scan_done(client, session_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/api/scans/{session_id}").json()
        if detail["status"] in ("completed", "failed"):
            return detail
        time.sleep(0.1)
    raise AssertionError("Scan did not complete in time")


def _wait_assets_done(client, video_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/studio/videos/{video_id}/assets").json()
        pending = [a for a in state["assets"] if a["status"] in ("pending", "processing")]
        if not pending:
            return state
        time.sleep(0.15)
    raise AssertionError("Studio assets did not finish processing in time")


def test_kling_jwt_and_bearer_auth_builder():
    # Relay Bearer mode
    cfg_relay = Settings(KLING_API_KEY="relay-secret-token")
    assert build_kling_auth_token(cfg_relay) == "relay-secret-token"

    # Official AK/SK HS256 JWT mode
    cfg_official = Settings(KLING_ACCESS_KEY="ak_test_123", KLING_SECRET_KEY="sk_test_456")
    jwt_token = build_kling_auth_token(cfg_official)
    parts = jwt_token.split(".")
    assert len(parts) == 3
    assert all(len(p) > 5 for p in parts)


def test_gemini_image_client_uses_v1beta_api_version():
    cfg = Settings(GEMINI_API_KEY="dummy-key-123")
    client = _build_gemini_image_client(cfg)
    assert client._api_client._http_options.api_version == "v1beta"


def test_v2_studio_full_all_ai_and_hybrid_stitch_pipeline(make_client):
    with make_client(password="", mock_mode=True) as client:
        _run_v2_studio_pipeline_assertions(client)


def _run_v2_studio_pipeline_assertions(client):

    # 1. Start a mock scan with an uploaded product photo
    sample_jpg = _make_sample_jpg()
    resp = client.post(
        "/api/scans",
        data={
            "product_text": "白色极简 LED 线性灯，铝合金机身，防眩光PC罩",
            "product_name_override": "LED 线性灯",
            "platforms": '["tiktok"]',
            "min_views": "50000",
            "min_likes": "2000",
            "target_count": "3",
        },
        files=[("files", ("led_light.jpg", sample_jpg, "image/jpeg"))],
    )
    assert resp.status_code == 200
    detail = _wait_scan_done(client, resp.json()["session_id"])
    assert detail["status"] == "completed"
    assert len(detail["videos"]) >= 1
    video_id = detail["videos"][0]["id"]

    # 2. Check Studio initial state remembers uploaded product reference image automatically
    state = client.get(f"/api/studio/videos/{video_id}/assets").json()
    assert state["has_product_reference"] is True
    assert state["product_reference_preview"].startswith("data:image/jpeg;base64,")
    assert state["gemini_image_configured"] is True
    assert state["openai_image_configured"] is True
    assert state["kling_configured"] is True

    # 3. Switch between Gemini and OpenAI for single image generation
    img_gemini = client.post(
        f"/api/studio/videos/{video_id}/generate-image",
        json={
            "slot_index": 0,
            "shot_no": None,
            "scene_title": "主视觉海报",
            "prompt": "Hero commercial poster for LED linear light",
            "provider": "gemini",
            "aspect_ratio": "9:16",
        },
    )
    assert img_gemini.status_code == 200
    assert img_gemini.json()["provider"] == "gemini"
    assert img_gemini.json()["status"] == "completed"

    # Download image bytes check
    img_dl = client.get(img_gemini.json()["file_url"])
    assert img_dl.status_code == 200
    assert img_dl.headers["content-type"].startswith("image/")
    assert len(img_dl.content) > 500

    # 4. Generate ALL storyboard shot images including real_shoot shots ("全片 100% AI 生成") using OpenAI provider
    batch_imgs = client.post(
        f"/api/studio/videos/{video_id}/generate-all-images",
        json={
            "provider": "openai",
            "only_missing": True,
            "include_real_shoot_shots": True,
            "include_poster": True,
        },
    )
    assert batch_imgs.status_code == 200
    # Mock storyboard has 4 shots (2 ai + 2 real_shoot), poster slot 0 was already generated
    assert len(batch_imgs.json()) == 4
    state = _wait_assets_done(client, video_id)
    completed_shot_imgs = [
        a for a in state["assets"] if a["asset_type"] == "image" and a["shot_no"] is not None and a["status"] == "completed"
    ]
    assert len(completed_shot_imgs) == 4
    assert all(a["provider"] == "openai" for a in completed_shot_imgs)

    if is_ffmpeg_available():
        # 5. Generate Kling AI video clip for shot 1
        shot1_img = next(a for a in completed_shot_imgs if a["shot_no"] == 1)
        vid1 = client.post(
            f"/api/studio/videos/{video_id}/generate-video-clip",
            json={
                "slot_index": 1,
                "shot_no": 1,
                "scene_title": "分镜1 可灵AI",
                "source_image_asset_id": shot1_img["id"],
                "prompt": "Smooth slow push-in showcasing LED linear light",
                "duration_sec": 5,
            },
        )
        assert vid1.status_code == 200
        state = _wait_assets_done(client, video_id)
        kling_clips = [a for a in state["assets"] if a["asset_type"] == "video_clip" and a["status"] == "completed"]
        assert len(kling_clips) == 1

        # 6. Upload a smartphone real-shoot clip for shot 2 (hybrid mix!)
        real_mp4 = image_to_motion_clip(sample_jpg, duration_sec=2.0)
        up_resp = client.post(
            f"/api/studio/videos/{video_id}/upload-real-clip",
            data={"shot_no": "2", "scene_title": "分镜2 手机实拍"},
            files={"file": ("phone_shot2.mp4", real_mp4, "video/mp4")},
        )
        assert up_resp.status_code == 200
        assert up_resp.json()["asset_type"] == "uploaded_clip"

        # 7. Stitch final 9:16 MP4 combining Kling AI clip (shot 1) + uploaded real clip (shot 2) + AI motion images (shots 3 & 4)
        stitch_resp = client.post(
            f"/api/studio/videos/{video_id}/stitch-final",
            json={"include_images_as_motion": True, "image_clip_duration": 2.0},
        )
        assert stitch_resp.status_code == 200
        final_asset = stitch_resp.json()
        assert final_asset["asset_type"] == "final_video"
        assert final_asset["status"] == "completed"
        assert final_asset["duration_sec"] >= 6.0
        assert "分镜1(可灵AI)" in final_asset["prompt_used"]
        assert "分镜2(实拍)" in final_asset["prompt_used"]
        assert "分镜3(AI图转动态)" in final_asset["prompt_used"]

        mp4_dl = client.get(f"{final_asset['file_url']}?download=1")
        assert mp4_dl.status_code == 200
        assert mp4_dl.headers["content-type"] == "video/mp4"
        assert len(mp4_dl.content) > 5000
