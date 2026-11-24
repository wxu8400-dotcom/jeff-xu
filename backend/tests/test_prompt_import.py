from __future__ import annotations

import io
import time

from PIL import Image


def _make_sample_jpg(color: tuple[int, int, int] = (220, 120, 40)) -> bytes:
    img = Image.new("RGB", (320, 320), color)
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
    raise AssertionError("Prompt import scan did not complete in time")


def _wait_assets_done(client, video_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/studio/videos/{video_id}/assets").json()
        pending = [a for a in state["assets"] if a["status"] in ("pending", "processing")]
        if not pending:
            return state
        time.sleep(0.15)
    raise AssertionError("Studio assets did not finish processing in time")


def test_prompt_screenshot_import_isolates_product_photos_and_generates_end_to_end(make_client):
    with make_client(password="", mock_mode=True) as client:
        # 1. Reject if neither prompt screenshot nor prompt text provided
        bad = client.post(
            "/api/scans/from-prompts",
            data={"product_name_override": "cc 沙发"},
        )
        assert bad.status_code == 400

        # 2. Upload 3 multi-angle product photos + 2 Codex prompt screenshots + optional text
        resp = client.post(
            "/api/scans/from-prompts",
            data={
                "product_name_override": "cc 沙发",
                "product_text": "焦糖橙色奢华真皮双人沙发",
                "prompt_text": "【0-3秒】欧美贵妇坐在豪华客机舱门内展示迷你沙发并抛出...",
            },
            files=[
                ("files", ("sofa_front.jpg", _make_sample_jpg((210, 120, 40)), "image/jpeg")),
                ("files", ("sofa_side.jpg", _make_sample_jpg((200, 115, 35)), "image/jpeg")),
                ("files", ("sofa_detail.jpg", _make_sample_jpg((190, 110, 30)), "image/jpeg")),
                ("prompt_images", ("codex_shot1.jpg", _make_sample_jpg((250, 250, 250)), "image/jpeg")),
                ("prompt_images", ("codex_shot2.jpg", _make_sample_jpg((245, 245, 245)), "image/jpeg")),
            ],
        )
        assert resp.status_code == 200
        detail = _wait_scan_done(client, resp.json()["session_id"])
        assert detail["status"] == "completed"
        assert detail["mode"] == "prompt_import"
        assert len(detail["videos"]) == 1

        video = detail["videos"][0]
        video_id = video["id"]
        assert video["analysis_mode"] == "prompt_import"
        plan = video["analysis_json"]["director_plan"]
        assert plan["revision_status"] == "locked"
        assert plan["has_user_customized"] is True

        # 3. Verify Studio product references contain ONLY the 3 product photos (ZERO Codex screenshots!)
        state = client.get(f"/api/studio/videos/{video_id}/assets").json()
        assert state["has_product_reference"] is True
        assert len(state["product_reference_previews"]) == 3

        # 4. Generate all first-frame images directly from imported prompt
        gen_resp = client.post(
            f"/api/studio/videos/{video_id}/generate-all-images",
            json={"provider": "openai", "only_missing": True, "include_poster": True},
        )
        assert gen_resp.status_code == 200
        state_after = _wait_assets_done(client, video_id)
        completed_imgs = [a for a in state_after["assets"] if a["asset_type"] == "image" and a["status"] == "completed"]
        assert len(completed_imgs) >= 2
