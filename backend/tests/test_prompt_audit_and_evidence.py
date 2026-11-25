from __future__ import annotations

import io
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.services.video_processor import (
    build_timestamped_contact_sheet,
    merge_shot_and_uniform_timestamps,
)


def _make_sample_jpeg(color: tuple[int, int, int] = (200, 120, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (240, 360), color=color).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def test_merge_shot_and_uniform_timestamps_keeps_opening_and_cuts() -> None:
    ts = merge_shot_and_uniform_timestamps(
        duration=10.0,
        scene_cuts=[2.0, 6.0, 8.0],
        max_frames=12,
    )
    assert ts[0] == 0.15
    assert ts[-1] >= 9.5
    assert len(ts) <= 12
    # Each scene cut (+0.12s settled) should be represented closely
    assert any(abs(t - 2.12) <= 0.25 for t in ts)
    assert any(abs(t - 6.12) <= 0.25 for t in ts)
    assert any(abs(t - 8.12) <= 0.25 for t in ts)


def test_build_timestamped_contact_sheet_renders_valid_jpeg() -> None:
    frames = [
        (0.15, _make_sample_jpeg((180, 50, 50))),
        (2.12, _make_sample_jpeg((50, 180, 50))),
        (6.12, _make_sample_jpeg((50, 50, 180))),
        (9.60, _make_sample_jpeg((200, 200, 50))),
    ]
    sheet = build_timestamped_contact_sheet(frames, cols=2)
    assert sheet is not None and len(sheet) > 1000
    with Image.open(io.BytesIO(sheet)) as im:
        assert im.format == "JPEG"
        assert im.width > 400
        assert im.height > 600


def test_audit_revise_endpoint_with_screenshots_and_3part_output(make_client) -> None:
    with make_client(password="", mock_mode=True) as client:
        # 1. Run a direct-URL scan first so we have a video record
        resp = client.post(
            "/api/scans/analyze-urls",
            data={
                "product_name_override": "焦糖橙真皮沙发",
                "urls": "https://www.tiktok.com/@demo/video/7690224248564108558",
            },
            files=[("files", ("sofa.jpg", _make_sample_jpeg((210, 110, 30)), "image/jpeg"))],
        )
        assert resp.status_code == 200, resp.text
        session_id = resp.json()["session_id"]

        video_id = None
        for _ in range(40):
            detail = client.get(f"/api/scans/{session_id}").json()
            if detail["status"] == "completed" and detail["videos"]:
                video_id = detail["videos"][0]["id"]
                break
            time.sleep(0.15)
        assert video_id is not None

        # 2. Submit reference prompt text + prompt screenshot + modification notes to /audit-revise
        audit_resp = client.post(
            f"/api/studio/videos/{video_id}/audit-revise",
            data={
                "reference_prompt_text": "全片统一参考：9:16 竖屏写实广告...\n镜头1：展示并抛出...",
                "modification_notes": "把主角物品换成我上传的焦糖橙沙发，补全喷发飞向镜头遮挡转场",
            },
            files=[
                (
                    "prompt_images",
                    ("codex_shot_1.jpg", _make_sample_jpeg((30, 30, 40)), "image/jpeg"),
                ),
            ],
        )
        assert audit_resp.status_code == 200, audit_resp.text
        body = audit_resp.json()
        assert body["ok"] is True
        assert body["prompt_audit_report"] is not None
        assert body["prompt_audit_report"]["verdict"] in ("accurate", "minor_gaps", "major_mismatch")

        plan = body["analysis_json"]["director_plan"]
        assert plan["has_user_customized"] is True
        assert plan["global_reference_prompt_cn"]
        assert plan["negative_constraints"]
        assert plan["prompt_audit_report"]["summary"]
        assert len(body["analysis_json"]["storyboard"]) >= 1
        assert len(body["analysis_json"]["kling_prompts"]) >= 1

        # 3. Lock plan with edited global_reference_prompt_cn & negative_constraints
        lock_resp = client.post(
            f"/api/studio/videos/{video_id}/lock-plan",
            json={
                "locked": True,
                "global_reference_prompt_cn": "已手动确认的全片统一参考提示词",
                "negative_constraints": "避免换款、避免穿模、无水印",
            },
        )
        assert lock_resp.status_code == 200, lock_resp.text
        locked_plan = lock_resp.json()["analysis_json"]["director_plan"]
        assert locked_plan["revision_status"] == "locked"
        assert locked_plan["global_reference_prompt_cn"] == "已手动确认的全片统一参考提示词"
        assert locked_plan["negative_constraints"] == "避免换款、避免穿模、无水印"
