from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.routers.studio import _apply_no_product_shot_guard, _extract_prompt_doc_bytes_text
from app.services.audio_engine import (
    _generate_mock_voice_mp3,
    align_source_audio_to_duration,
)
from app.services.pack_parser import is_placeholder_text, parse_structured_production_pack
from app.services.video_processor import (
    build_timestamped_contact_sheet,
    is_ffmpeg_available,
    merge_shot_and_uniform_timestamps,
)
from app.services.video_stitcher import (
    extract_last_frame_jpeg,
    image_to_motion_clip,
    parse_planned_shot_duration_sec,
)


def test_structured_7shot_pack_parser_exact_count_and_anti_leak() -> None:
    sample_pack = """二、新版统一产品、人物、场景与风格设定
【风格】9:16满屏竖构图，写实奇幻高端家具广告。
【产品】原始沙发照片为造型唯一依据，焦糖橙色双人沙发，靠背横向波浪褶纹。
【人物】同一位虚构成年女性，穿黑色丝质连衣裙和黑鞋。

【文件 2：分镜内容】
【镜头01｜皮料展示与抛出｜保留约2.5秒】
关键帧图片提示词：私人客机敞开侧舱门内，女士双手托着黑色浅托盘与三块橙色薄皮料。没有成品沙发。
图生视频提示词：女士把托盘向左侧门外推出并松手。

【镜头02｜火山口正上方下落｜保留约1.5秒】
关键帧图片提示词：高空俯看火山口，黑色托盘连同橙色薄皮料处于中央正上方，画面没有沙发。
图生视频提示词：托盘向火山口中央坠落消失。

【镜头03｜烟雾反应｜保留约1秒】
关键帧图片提示词：俯视火山构图，中央烟雾盖住托盘消失位置，画面没有可见皮料、沙发或其他固体。
图生视频提示词：烟雾内部亮起橙金闪光并向上鼓起。

【镜头04｜完整同款沙发弹射亮相｜保留约2秒】
需要参考：原始沙发照片。
关键帧图片提示词：火山口上方，一张完整正常尺寸焦糖橙双人沙发从烟云中露出。
图生视频提示词：完整沙发被喷发向上推出。

【镜头05｜接近镜头形成遮挡｜保留约1秒】
需要参考：原始产品照片。
关键帧图片提示词：同款完整焦糖橙沙发处于空中较近位置。
图生视频提示词：沙发迅速掠近镜头形成橙色遮挡。

【镜头06｜客机会客区落稳｜保留约2秒】
需要参考：同款产品、人物参考。
关键帧图片提示词：豪华客机会客区，正常尺寸同款焦糖橙双人沙发即将落地，女士站在右侧。
图生视频提示词：沙发落地稳定，女士惊喜微笑。

【镜头07｜女士坐下开心笑｜保留约5秒】
需要参考：镜头06末帧、沙发原图。
关键帧图片提示词：女士站在同款焦糖橙沙发前准备坐下。
图生视频提示词：女士自然坐下开心地笑，完整展示产品。

四、共用排除要求
不要鸡肉、不要菱格靠背、不要人物换脸、不生成水印。
"""
    parsed = parse_structured_production_pack(sample_pack, product_name="焦糖橙沙发")
    assert parsed is not None
    assert parsed["shot_count"] == 7
    assert len(parsed["storyboard"]) == 7
    assert len(parsed["kling_prompts"]) == 7
    assert len(parsed["chatgpt_images_prompts"]) == 8  # poster + 7 shots
    # Shots 1-3 have no finished sofa -> keep_scene; Shots 4-7 -> insert_product
    assert [s.replication_action for s in parsed["storyboard"]] == [
        "keep_scene",
        "keep_scene",
        "keep_scene",
        "insert_product",
        "insert_product",
        "insert_product",
        "insert_product",
    ]
    # Shot 3 ("其他固体") must NOT falsely trigger has_person=True
    assert parsed["storyboard"][2].has_person is False
    assert parsed["storyboard"][0].has_person is True
    assert parsed["storyboard"][6].has_person is True
    # Zero placeholder strings anywhere
    for img_p in parsed["chatgpt_images_prompts"]:
        assert not is_placeholder_text(img_p.prompt_en)
        assert len(img_p.prompt_en) > 60


def test_parse_planned_shot_duration_sec_handles_universal_formats() -> None:
    assert parse_planned_shot_duration_sec("约3秒") == 3.0
    assert parse_planned_shot_duration_sec("成片约2秒") == 2.0
    assert parse_planned_shot_duration_sec("00:00-00:03") == 3.0
    assert parse_planned_shot_duration_sec("1.5-3秒") == 1.5
    assert parse_planned_shot_duration_sec("6-7.5s") == 1.5
    assert parse_planned_shot_duration_sec("约2-3秒") == 2.5


def test_extract_last_frame_jpeg_from_real_clip() -> None:
    if not is_ffmpeg_available():
        return
    clip = image_to_motion_clip(_make_sample_jpeg((190, 90, 30)), duration_sec=2.0)
    last_jpg = extract_last_frame_jpeg(clip)
    assert len(last_jpg) > 1000
    with Image.open(io.BytesIO(last_jpg)) as im:
        assert im.format == "JPEG"
        assert im.width >= 600


def test_align_source_audio_to_duration_stretches_cleanly() -> None:
    if not is_ffmpeg_available():
        return
    src_mp3 = _generate_mock_voice_mp3(3.0)
    aligned = align_source_audio_to_duration(src_mp3, 4.5)
    assert len(aligned) > 1000


def _make_sample_docx(text: str) -> bytes:
    buf = io.BytesIO()
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", xml.encode("utf-8"))
    return buf.getvalue()


def test_prompt_doc_extraction_and_no_product_anti_leak_guard() -> None:
    txt_out = _extract_prompt_doc_bytes_text("pack.txt", "镜头1：画面内没有成品沙发".encode("utf-8"))
    assert "画面内没有成品沙发" in txt_out

    docx_bytes = _make_sample_docx("皮料投入火山｜可灵制作包")
    docx_out = _extract_prompt_doc_bytes_text("pack.docx", docx_bytes)
    assert "皮料投入火山" in docx_out

    storyboard = [
        {"shot_no": 1, "adapted_visual_for_product": "展示橙色皮料，画面内没有成品沙发", "replication_action": "insert_product"},
        {"shot_no": 2, "adapted_visual_for_product": "完整正常尺寸焦糖橙双人沙发弹射上升", "replication_action": "insert_product"},
    ]
    image_prompts = [
        {"scene_title": "封面"},
        {"scene_title": "镜头1", "prompt_cn": "女士端着皮料托盘，画面内没有成品沙发"},
        {"scene_title": "镜头2", "prompt_cn": "上传沙发照片作为产品参考，完整焦糖橙沙发"},
    ]
    _apply_no_product_shot_guard(storyboard, image_prompts)
    assert storyboard[0]["replication_action"] == "keep_scene"
    assert storyboard[1]["replication_action"] == "insert_product"


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

        # 1.5 Step 2A: Review-only endpoint accepts .docx production pack file directly
        review_resp = client.post(
            f"/api/studio/videos/{video_id}/review-prompt",
            files=[
                (
                    "prompt_file",
                    (
                        "kling_pack.docx",
                        _make_sample_docx("二、新版统一设定：焦糖橙沙发；镜头1：展示皮料，画面内没有成品沙发"),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
            ],
        )
        assert review_resp.status_code == 200, review_resp.text
        rev_body = review_resp.json()
        assert rev_body["ok"] is True
        assert len(rev_body["review"]["suggestions"]) >= 1
        assert len(rev_body["review"]["editing_guidelines"]["generation_order"]) >= 1
        assert len(rev_body["review"]["editing_guidelines"]["final_qa_checklist"]) >= 1

        # 2. Step 2B: Apply confirmed suggestions -> returns 4-part split package
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
        assert plan["editing_guidelines"] is not None
        assert len(plan["editing_guidelines"]["generation_order"]) >= 1
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

        # 4. Also verify 2-file direct creative creation (/api/scans/from-prompts)
        two_file_resp = client.post(
            "/api/scans/from-prompts",
            data={"product_name_override": "焦糖橙真皮沙发"},
            files=[
                ("files", ("sofa.jpg", _make_sample_jpeg((210, 110, 30)), "image/jpeg")),
                (
                    "requirements_file",
                    (
                        "video_requirements.txt",
                        "9:16 竖屏写实高端家居广告，画面自然流畅，不死板照搬原片。".encode("utf-8"),
                        "text/plain",
                    ),
                ),
                (
                    "storyboard_file",
                    (
                        "storyboard.docx",
                        _make_sample_docx("镜头1（约3秒）：展示皮料；镜头2（约3秒）：成品沙发自然呈现"),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
            ],
        )
        assert two_file_resp.status_code == 200, two_file_resp.text
        assert two_file_resp.json()["session_id"]
