from __future__ import annotations

import asyncio
import io
import time

from PIL import Image

from app.database import get_session_factory
from app.models import GeneratedAsset, ScanSession, VideoRecord
from app.routers.studio import _prepare_shot_image_inputs, _save_asset_media


def _make_sample_jpg(color: tuple[int, int, int] = (230, 240, 250)) -> bytes:
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
    raise AssertionError("Scan did not complete in time")


def test_director_co_creation_revise_and_lock_lifecycle(make_client):
    with make_client(password="", mock_mode=True) as client:
        resp = client.post(
            "/api/scans",
            data={
                "product_name_override": "磁吸桌面氛围灯",
                "product_text": "极简设计、USB-C充电、三档调光，适合书桌卧室使用。",
                "platforms": '["tiktok"]',
                "target_count": "1",
                "min_views": "10000",
                "min_likes": "500",
                "date_range_days": "30",
            },
            files=[("files", ("lamp.jpg", _make_sample_jpg(), "image/jpeg"))],
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        detail = _wait_scan_done(client, session_id)
        assert detail["status"] == "completed"
        assert len(detail["videos"]) >= 1

        video = detail["videos"][0]
        video_id = video["id"]
        analysis = video["analysis_json"]
        plan = analysis["director_plan"]
        assert plan["revision_status"] == "draft"
        assert plan["original_plot_summary"]
        assert plan["ai_character_profile_cn"]
        assert plan["ai_character_profile_en"]
        assert any(s.get("replication_action") == "keep_scene" for s in analysis["storyboard"])
        assert any(s.get("has_person") for s in analysis["storyboard"])

        # Round 1: User gives director feedback to tweak character & product placement
        rev_resp = client.post(
            f"/api/studio/videos/{video_id}/revise-plan",
            json={"feedback": "把AI人物换成年轻女性，第2镜再自然引出产品"},
        )
        assert rev_resp.status_code == 200
        rev_data = rev_resp.json()
        assert rev_data["ok"] is True
        assert rev_data["director_reply"]
        updated_plan = rev_data["analysis_json"]["director_plan"]
        assert updated_plan["revision_status"] == "draft"
        assert len(updated_plan["revision_history"]) == 2
        assert updated_plan["revision_history"][0]["role"] == "user"
        assert "年轻女性" in updated_plan["revision_history"][0]["message"]
        assert updated_plan["revision_history"][1]["role"] == "director"

        # Verify persisted in scan detail reload
        reloaded = client.get(f"/api/scans/{session_id}").json()
        reloaded_video = next(v for v in reloaded["videos"] if v["id"] == video_id)
        assert len(reloaded_video["analysis_json"]["director_plan"]["revision_history"]) == 2

        # Lock the finalized storyboard plan
        lock_resp = client.post(
            f"/api/studio/videos/{video_id}/lock-plan",
            json={"locked": True},
        )
        assert lock_resp.status_code == 200
        assert lock_resp.json()["revision_status"] == "locked"

        # Unlock back to draft
        unlock_resp = client.post(
            f"/api/studio/videos/{video_id}/lock-plan",
            json={"locked": False},
        )
        assert unlock_resp.status_code == 200
        assert unlock_resp.json()["revision_status"] == "draft"


def test_smart_reference_passing_respects_keep_scene_and_character_consistency(make_client):
    with make_client(password="", mock_mode=True) as client:
        resp = client.post(
            "/api/scans",
            data={
                "product_name_override": "便携香薰机",
                "product_text": "极简磨砂质感，静音出雾。",
                "platforms": '["tiktok"]',
                "target_count": "1",
                "min_views": "10000",
                "min_likes": "500",
                "date_range_days": "30",
            },
            files=[("files", ("diffuser.jpg", _make_sample_jpg((100, 120, 140)), "image/jpeg"))],
        )
        assert resp.status_code == 200
        detail = _wait_scan_done(client, resp.json()["session_id"])
        video_id = detail["videos"][0]["id"]

        factory = get_session_factory()
        db = factory()
        try:
            video = db.get(VideoRecord, video_id)
            session = db.get(ScanSession, video.session_id)
            assert video is not None and session is not None

            # Force deterministic shot flags for testing
            analysis = dict(video.analysis_json or {})
            analysis["director_plan"] = {
                **(analysis.get("director_plan") or {}),
                "ai_character_profile_en": "A cheerful 26-year-old East Asian woman with shoulder-length black hair wearing a beige knit sweater",
            }
            analysis["storyboard"] = [
                {
                    "shot_no": 1,
                    "time_range": "0-3s",
                    "shot_size": "中景",
                    "camera_movement": "固定",
                    "original_visual": "人物走进客厅",
                    "adapted_visual_for_product": "新AI人物走进客厅，先铺垫情绪，暂不出现产品",
                    "replication_action": "keep_scene",
                    "has_person": True,
                },
                {
                    "shot_no": 2,
                    "time_range": "3-7s",
                    "shot_size": "特写",
                    "camera_movement": "慢推",
                    "original_visual": "拿起桌面物品",
                    "adapted_visual_for_product": "同一AI人物拿起便携香薰机",
                    "replication_action": "insert_product",
                    "has_person": True,
                },
            ]
            video.analysis_json = analysis
            db.commit()

            product_bytes = _make_sample_jpg((255, 0, 0))
            product_refs = [(product_bytes, "image/jpeg")]

            # 1) Shot 1 (keep_scene + has_person): NO product ref attached, AI character profile injected!
            p1, refs1 = asyncio.run(
                _prepare_shot_image_inputs(
                    video=video,
                    session=session,
                    db=db,
                    slot_index=1,
                    shot_no=1,
                    prompt="A cozy modern living room opening scene",
                    product_refs=product_refs,
                    use_character_ref=True,
                )
            )
            assert len(refs1) == 0
            assert "26-year-old East Asian woman" in p1

            # Persist a completed generated image for Shot 1 (acts as character anchor)
            char_bytes = _make_sample_jpg((0, 200, 100))
            shot1_asset = GeneratedAsset(
                video_id=video.id,
                session_id=session.id,
                asset_type="image",
                slot_index=1,
                shot_no=1,
                scene_title="分镜 1 首帧图",
                provider="mock",
                model_name="mock-img",
                status="completed",
                mime_type="image/jpeg",
            )
            db.add(shot1_asset)
            db.commit()
            db.refresh(shot1_asset)
            _save_asset_media(shot1_asset, char_bytes)
            db.commit()

            # 2) Shot 2 (insert_product + has_person + use_character_ref=True):
            # MUST attach BOTH product ref AND Shot 1 character ref!
            p2, refs2 = asyncio.run(
                _prepare_shot_image_inputs(
                    video=video,
                    session=session,
                    db=db,
                    slot_index=2,
                    shot_no=2,
                    prompt="Holding the diffuser on the wooden desk",
                    product_refs=product_refs,
                    use_character_ref=True,
                )
            )
            assert len(refs2) == 2
            assert refs2[0][0] == product_bytes
            assert refs2[1][0] == char_bytes
            assert "CRITICAL CHARACTER CONSISTENCY" in p2

            # 3) Shot 2 with use_character_ref=False: ONLY product ref attached
            p2_nochar, refs2_nochar = asyncio.run(
                _prepare_shot_image_inputs(
                    video=video,
                    session=session,
                    db=db,
                    slot_index=2,
                    shot_no=2,
                    prompt="Holding the diffuser on the wooden desk",
                    product_refs=product_refs,
                    use_character_ref=False,
                )
            )
            assert len(refs2_nochar) == 1
            assert refs2_nochar[0][0] == product_bytes
            assert "CRITICAL CHARACTER CONSISTENCY" not in p2_nochar

            # 4) Poster (slot 0): always attaches product ref
            _, refs0 = asyncio.run(
                _prepare_shot_image_inputs(
                    video=video,
                    session=session,
                    db=db,
                    slot_index=0,
                    shot_no=None,
                    prompt="Hero commercial poster",
                    product_refs=product_refs,
                    use_character_ref=True,
                )
            )
            assert len(refs0) == 1
            assert refs0[0][0] == product_bytes
        finally:
            db.close()


def test_gemini_recommended_model_parsing_and_302_safety_net(monkeypatch):
    from app.config import Settings
    from app.services.ai_client import TokenUsage, UnifiedAIClient

    err_msg = (
        "404 NOT_FOUND. {'error': {'code': 404, 'message': "
        "'This model models/gemini-2.5-flash is no longer available to new users. "
        "Please update your code to use models/gemini-3.8-flash for the latest features.'}}"
    )
    assert UnifiedAIClient._parse_recommended_model_from_error(err_msg) == "gemini-3.8-flash"

    # Verify fallback to 302.ai OpenAI-compatible relay when all Gemini models fail
    cfg = Settings(
        GEMINI_API_KEY="dummy-gemini",
        OPENAI_IMAGE_API_KEY="sk-302-relay",
        OPENAI_IMAGE_BASE_URL="https://api.302.ai/v1",
        ENABLE_MOCK_MODE=False,
    )
    ai = UnifiedAIClient(cfg)

    class _FailingModels:
        def generate_content(self, **kwargs):
            raise RuntimeError("404 NOT_FOUND: model not found")

        def list(self):
            return []

    class _FakeClient:
        models = _FailingModels()

    monkeypatch.setattr(ai, "_build_gemini_client", lambda **kwargs: _FakeClient())
    UnifiedAIClient._discovered_gemini_models = []
    UnifiedAIClient._dead_gemini_models = set()

    called_relay = {}

    async def _fake_openai_fallback(**kwargs):
        called_relay.update(kwargs)
        return '{"ok": true}', TokenUsage(10, 5)

    monkeypatch.setattr(ai, "_call_openai_compatible", _fake_openai_fallback)

    text, usage = asyncio.run(
        ai._call_gemini(
            prompt="hello",
            tier="fast",
            images=[],
            video_bytes=None,
            video_mime="video/mp4",
        )
    )
    assert text == '{"ok": true}'
    assert usage.input_tokens == 10
    assert called_relay["api_key_override"] == "sk-302-relay"
    assert called_relay["base_url_override"] == "https://api.302.ai/v1"
    UnifiedAIClient._dead_gemini_models = set()


def test_openai_compatible_302_fallback_recovers_from_500(monkeypatch):
    import types as pytypes
    from app.config import Settings
    from app.services.ai_client import UnifiedAIClient

    cfg = Settings(
        OPENAI_IMAGE_API_KEY="sk-302-relay",
        OPENAI_IMAGE_BASE_URL="https://api.302.ai/v1",
        ENABLE_MOCK_MODE=False,
    )
    ai = UnifiedAIClient(cfg)

    tried_models: list[str] = []

    class _FakeCompletions:
        async def create(self, **kwargs):
            m = kwargs["model"]
            tried_models.append(m)
            if m == "gpt-4.1":
                raise RuntimeError("Error code: 500")
            msg = pytypes.SimpleNamespace(content='{"status": "recovered"}')
            choice = pytypes.SimpleNamespace(message=msg)
            usage = pytypes.SimpleNamespace(prompt_tokens=120, completion_tokens=40)
            return pytypes.SimpleNamespace(choices=[choice], usage=usage)

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = pytypes.SimpleNamespace(completions=_FakeCompletions())

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsyncOpenAI)

    text, usage = asyncio.run(
        ai._call_openai_compatible(
            prompt="deep analysis",
            tier="deep",
            images=[],
            video_bytes=None,
            api_key_override="sk-302-relay",
            base_url_override="https://api.302.ai/v1",
        )
    )
    assert text == '{"status": "recovered"}'
    assert usage.input_tokens == 120
    assert tried_models == ["gpt-4.1", "gemini-2.5-pro"]


def test_director_long_term_memory_auto_extraction_reinforcement_and_crud(make_client):
    from app.services.director_memory import load_director_memory_block

    with make_client(password="", mock_mode=True) as client:
        # 1. Start a direct-URL analysis for cc 沙发
        resp = client.post(
            "/api/scans/analyze-urls",
            data={
                "product_name_override": "cc 沙发",
                "product_text": "焦糖色奢华真皮双人沙发",
                "urls": "https://www.tiktok.com/@brand/video/7412345678901234567",
            },
        )
        assert resp.status_code == 200
        detail = _wait_scan_done(client, resp.json()["session_id"])
        video_id = detail["videos"][0]["id"]

        # 2. First director revision automatically distills & persists long-term memory
        rev1 = client.post(
            f"/api/studio/videos/{video_id}/revise-plan",
            json={
                "feedback": "把飞机变成豪华私人飞机，欧美漂亮贵妇扔缩小版沙发，弹出正常尺寸沙发落入机舱客厅"
            },
        )
        assert rev1.status_code == 200
        rev1_data = rev1.json()
        assert len(rev1_data["learned_memories"]) == 1
        mem_id = rev1_data["learned_memories"][0]["id"]
        assert rev1_data["learned_memories"][0]["confidence_hits"] == 1

        # 3. Repeating a similar creative preference reinforces confidence_hits (no duplicate spam!)
        rev2 = client.post(
            f"/api/studio/videos/{video_id}/revise-plan",
            json={
                "feedback": "把飞机变成豪华私人飞机，欧美漂亮贵妇扔缩小版沙发，弹出正常尺寸沙发落入机舱客厅"
            },
        )
        assert rev2.status_code == 200
        assert rev2.json()["learned_memories"][0]["id"] == mem_id
        assert rev2.json()["learned_memories"][0]["confidence_hits"] == 2

        # 4. Verify memory block is automatically formatted for future videos
        factory = get_session_factory()
        db = factory()
        try:
            block = load_director_memory_block(db, product_name="cc 沙发", category="家具")
            assert "私人飞机" in block
            assert "已强化 2 次" in block
        finally:
            db.close()

        # 5. Verify manual create / toggle / delete memory APIs
        created = client.post(
            "/api/studio/memories",
            json={
                "category": "pacing_framing",
                "product_scope": "global",
                "rule_summary": "未提及的画面框架和镜头绝不擅自改动",
            },
        )
        assert created.status_code == 200
        custom_id = created.json()["id"]

        listed = client.get("/api/studio/memories").json()
        assert len(listed) == 2

        paused = client.patch(f"/api/studio/memories/{custom_id}", json={"is_active": False})
        assert paused.status_code == 200
        assert paused.json()["is_active"] is False

        deleted = client.delete(f"/api/studio/memories/{custom_id}")
        assert deleted.status_code == 200
        assert len(client.get("/api/studio/memories").json()) == 1


def test_first_frame_inclusive_timestamps_and_unified_prompt_workflow(make_client):
    from app.schemas import ProductDNA
    from app.services.prompts import build_director_revision_prompt
    from app.services.video_processor import _compute_inclusive_timestamps

    # 0. Revision prompt MUST strip large base64 keyframe_previews so LLM never overflows/fails
    fake_base64 = "data:image/jpeg;base64," + ("A" * 50_000)
    rev_prompt = build_director_revision_prompt(
        product_dna=ProductDNA(product_name="cc 沙发"),
        current_analysis={
            "director_plan": {
                "original_video_prompt_cn": "直升机内白裙女性扔生鸡肉进火山口，最后炸鸡弹出",
                "keyframe_previews": [fake_base64, fake_base64],
            }
        },
        user_feedback="把直升机改为豪华客机，扔缩小版沙发",
        revision_history=[],
    )
    assert "data:image/jpeg;base64," not in rev_prompt
    assert len(rev_prompt) < 10_000

    # 1. Opening frame (~0.15s) MUST always be Frame 0 so airplane/opening shots are never skipped
    ts_12s = _compute_inclusive_timestamps(12.0, 6)
    assert ts_12s[0] == 0.15
    assert ts_12s[-1] >= 11.5
    assert len(ts_12s) == 6

    with make_client(password="", mock_mode=True) as client:
        resp = client.post(
            "/api/scans/analyze-urls",
            data={
                "product_name_override": "cc 沙发",
                "product_text": "焦糖色真皮双人沙发",
                "urls": "https://www.tiktok.com/t/ZPNBMH3e7/",
            },
        )
        assert resp.status_code == 200
        detail = _wait_scan_done(client, resp.json()["session_id"])
        video = detail["videos"][0]
        video_id = video["id"]
        plan = video["analysis_json"]["director_plan"]

        # 2. Initial parse outputs pure original prompt with has_user_customized == False
        assert plan["has_user_customized"] is False
        assert plan["original_video_prompt_cn"]
        assert plan["current_master_prompt_cn"] == plan["original_video_prompt_cn"]
        orig_prompt = plan["original_video_prompt_cn"]

        # 3. Multi-turn revision updates current_master_prompt_cn while keeping original_video_prompt_cn intact
        r1 = client.post(
            f"/api/studio/videos/{video_id}/revise-plan",
            json={"feedback": "把飞机换成豪华私人飞机，人物换成欧美漂亮贵妇"},
        )
        assert r1.status_code == 200
        p1 = r1.json()["analysis_json"]["director_plan"]
        assert p1["has_user_customized"] is True
        assert p1["original_video_prompt_cn"] == orig_prompt
        assert "豪华私人飞机" in p1["current_master_prompt_cn"]

        r2 = client.post(
            f"/api/studio/videos/{video_id}/revise-plan",
            json={"feedback": "再在客舱沙发前面加一张奢华大理石茶几"},
        )
        assert r2.status_code == 200
        p2 = r2.json()["analysis_json"]["director_plan"]
        assert "豪华私人飞机" in p2["current_master_prompt_cn"]
        assert "大理石茶几" in p2["current_master_prompt_cn"]

        # 4. Confirm/lock with optional manual text tweak
        lock = client.post(
            f"/api/studio/videos/{video_id}/lock-plan",
            json={"locked": True, "master_prompt_cn": p2["current_master_prompt_cn"] + "（终版定稿）"},
        )
        assert lock.status_code == 200
        assert lock.json()["revision_status"] == "locked"
        assert lock.json()["analysis_json"]["director_plan"]["current_master_prompt_cn"].endswith("（终版定稿）")


def test_multi_angle_product_photos_and_per_image_chinese_refinement(make_client):
    with make_client(password="", mock_mode=True) as client:
        # Upload 4 multi-angle product photos alongside a direct video link
        resp = client.post(
            "/api/scans/analyze-urls",
            data={
                "product_name_override": "cc 沙发",
                "product_text": "焦糖橙色奢华真皮双人沙发，多角度实拍",
                "urls": "https://www.tiktok.com/t/ZPNBMH3e7/",
            },
            files=[
                ("files", ("front.jpg", _make_sample_jpg((210, 120, 40)), "image/jpeg")),
                ("files", ("side.jpg", _make_sample_jpg((200, 115, 35)), "image/jpeg")),
                ("files", ("back.jpg", _make_sample_jpg((190, 110, 30)), "image/jpeg")),
                ("files", ("detail.jpg", _make_sample_jpg((220, 130, 45)), "image/jpeg")),
            ],
        )
        assert resp.status_code == 200
        detail = _wait_scan_done(client, resp.json()["session_id"])
        video_id = detail["videos"][0]["id"]

        # Studio state exposes all 4 multi-angle product previews
        state = client.get(f"/api/studio/videos/{video_id}/assets").json()
        assert state["has_product_reference"] is True
        assert len(state["product_reference_previews"]) == 4

        # Revise prompt returns dedicated negative_constraints
        rev = client.post(
            f"/api/studio/videos/{video_id}/revise-plan",
            json={"feedback": "把直升机改为豪华客机，人物换成欧美贵妇，扔缩小版沙发弹出正常尺寸沙发"},
        )
        assert rev.status_code == 200
        assert rev.json()["analysis_json"]["director_plan"]["negative_constraints"]

        # Per-image Chinese refinement endpoint re-generates that specific image with the fix
        refined = client.post(
            f"/api/studio/videos/{video_id}/refine-image",
            json={
                "slot_index": 1,
                "shot_no": 1,
                "scene_title": "画面 1",
                "base_prompt": "Woman seated inside private jet cabin holding miniature sofa",
                "feedback": "人物换更年轻的28岁欧美金发美女，机舱光线调亮一点",
                "provider": "openai",
                "aspect_ratio": "9:16",
            },
        )
        assert refined.status_code == 200
        asset = refined.json()
        assert asset["status"] == "completed"
        assert asset["slot_index"] == 1
        assert "28岁欧美金发美女" in asset["prompt_used"]





