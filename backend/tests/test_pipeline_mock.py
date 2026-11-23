from __future__ import annotations

import time


def _wait_session_done(client, session_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/api/scans/{session_id}").json()
        if detail["status"] in ("completed", "failed"):
            return detail
        time.sleep(0.1)
    raise AssertionError("Scan did not complete in time")


def test_four_stage_funnel_end_to_end_in_mock_mode(make_client):
    client = make_client(password="", mock_mode=True)

    resp = client.post(
        "/api/scans",
        data={
            "product_text": "迷你高速手持冰敷风扇，磨砂白，3秒降温",
            "product_name_override": "迷你冰敷风扇",
            "user_instruction": "找欧美高播高赞可替换爆款",
            "platforms": '["tiktok","instagram","youtube"]',
            "min_views": "100000",
            "min_likes": "5000",
            "date_range_days": "30",
            "target_count": "5",
            "auto_relax": "false",
        },
    )
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    detail = _wait_session_done(client, session_id)
    assert detail["status"] == "completed"
    assert "迷你冰敷风扇" in detail["history_title"]

    # Verify 4-stage funnel numbers:
    # Mock has 6 total videos:
    # - 1 IG video has only 1,200 views -> filtered in Stage 2 (leaving 5)
    # - 1 TikTok video is NYC Street Interview -> eliminated in Stage 3 (< 65 score, leaving 4)
    stats = detail["funnel_stats"]
    assert stats["collected"] == 6
    assert stats["after_hard_filter"] == 5
    assert stats["after_screening"] == 4
    assert stats["analyzed"] == 4
    assert stats["input_tokens"] > 0
    assert stats["output_tokens"] > 0

    videos = detail["videos"]
    assert len(videos) == 4
    video_ids = {v["platform_video_id"] for v in videos}
    # Street interview and low-view video MUST NOT be included
    assert "7410001003" not in video_ids
    assert "C9xLowView02" not in video_ids

    # Verify rich structured outputs for every collected video
    for v in videos:
        assert v["video_url"].startswith("https://")
        assert v["replaceability_score"] >= 65
        a = v["analysis_json"]
        assert a["structure"]["hook_3s"]
        assert len(a["storyboard"]) >= 3
        assert a["shooting_requirements"]["lighting"]
        assert a["copywriting"]["adapted_script_cn"]
        assert a["copywriting"]["adapted_script_en"]
        assert len(a["chatgpt_images_prompts"]) >= 3
        assert len(a["kling_prompts"]) >= 3
        for p in a["chatgpt_images_prompts"]:
            assert "迷你冰敷风扇" in p["prompt_en"] or "迷你冰敷风扇" in p["prompt_cn"]
        for kp in a["kling_prompts"]:
            assert kp["prompt_cn"] and kp["prompt_en"] and kp["negative_prompt"]
