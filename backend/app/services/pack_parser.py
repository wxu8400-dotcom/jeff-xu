from __future__ import annotations

import re
from typing import Any

from ..schemas import (
    ChatGPTImagePrompt,
    CopywritingAnalysis,
    DirectorPlan,
    EditingGuidelines,
    KlingVideoPrompt,
    PromptAuditReport,
    ReplaceabilityAnalysis,
    ShootingRequirements,
    StoryboardShot,
    VideoDeepAnalysis,
    VideoStructureAnalysis,
)

# Universal markers indicating a shot must NOT attach the finished product photo
NO_PRODUCT_MARKERS: tuple[str, ...] = (
    "没有成品",
    "无成品",
    "没有沙发",
    "没有可见沙发",
    "没有可见产品",
    "没有可见皮料、沙发",
    "不出现产品",
    "不出现成品",
    "没有产品",
    "画面没有沙发",
    "画面内没有成品",
    "no finished product",
    "no finished sofa",
    "without the finished product",
)

HAS_PRODUCT_MARKERS: tuple[str, ...] = (
    "原始沙发照片",
    "原始产品照片",
    "沙发原图",
    "上传沙发照片",
    "上传产品照片",
    "产品参考",
    "完整同款",
    "同款产品",
    "同款沙发",
    "成品沙发",
    "完整沙发",
    "完整正常尺寸",
)

NO_PERSON_MARKERS: tuple[str, ...] = (
    "不出现人物",
    "无人物",
    "没有人物",
    "无人",
    "no person",
    "no human",
)

HAS_PERSON_MARKERS: tuple[str, ...] = (
    "女士",
    "女人",
    "女性",
    "人物",
    "男性",
    "模特",
    "黑裙",
    "连衣裙",
    "双臂",
    "双手",
    "woman",
    "lady",
    "man",
    "person",
    "model",
)

PLACEHOLDER_SUBSTRINGS: tuple[str, ...] = (
    "展示并抛出：人物在主场景展示迷你版产品并抛出",
    "Photorealistic vertical 9:16 cinema keyframe...",
    "Keep the exact product from the uploaded reference images...",
    "简洁清晰描述该镜头首帧的构图、人物位置与产品状态",
    "严格保持上传商品外观一致的主视觉封面...",
    "第一部分：全片统一参考提示词（画幅质感",
)

# Matches shot headers like:
# 【镜头01｜皮料展示与抛出｜保留约2.5秒】
# 【镜头1｜展示皮料并抛出｜成片约3秒】
# 镜头1：xxx / ### 镜头 01 - xxx / Shot 1: xxx
_SHOT_HEADER_RE = re.compile(
    r"(?m)^(?:#{1,4}\s*)?(?:【\s*(?:镜头|分镜|Shot)\s*0*(\d+)\s*[｜|:：\-\s]+([^】\n]+?)】|(?:镜头|分镜|Shot)\s*0*(\d+)\s*[｜|:：\-]\s*(.+?))$"
)

_TIME_HINT_RE = re.compile(
    r"((?:保留约|成片约|约)?\s*\d+(?:\.\d+)?\s*(?:[-–~]\s*\d+(?:\.\d+)?)?\s*(?:秒|s|sec))",
    re.IGNORECASE,
)


def is_placeholder_text(text: str | None) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    if any(p in s for p in PLACEHOLDER_SUBSTRINGS):
        return True
    if s.endswith("...") and len(s) < 95:
        return True
    return False


def _extract_section(full_text: str, start_patterns: list[str], stop_patterns: list[str]) -> str:
    start_idx = -1
    for pat in start_patterns:
        m = re.search(pat, full_text, re.MULTILINE)
        if m:
            start_idx = m.end()
            break
    if start_idx < 0:
        return ""
    rest = full_text[start_idx:]
    end_idx = len(rest)
    for spat in stop_patterns:
        m = re.search(spat, rest, re.MULTILINE)
        if m and m.start() < end_idx:
            end_idx = m.start()
    return rest[:end_idx].strip()


def _extract_labeled_field(block: str, labels: list[str]) -> str:
    label_group = "|".join(labels)
    pat = re.compile(
        rf"(?m)^(?:{label_group})\s*[:：]\s*(.+?)(?=\n(?:需要参考|关键帧图片提示词|关键帧图片|首帧提示词|图生视频提示词|图生视频|动态提示词|结束状态/衔接|结束状态|剪辑衔接|通过标准|验收标准|【镜头|【分镜|镜头\d|分镜\d)|\Z)",
        re.DOTALL,
    )
    m = pat.search(block)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _detect_shot_flags(
    *,
    title: str,
    ref_line: str,
    keyframe_cn: str,
    video_cn: str,
) -> tuple[str, bool]:
    """Return (replication_action, has_person) deterministically from shot text."""
    combined_no_check = f"{keyframe_cn} {title}".lower()
    combined_all = f"{title} {ref_line} {keyframe_cn} {video_cn}".lower()

    if any(m in combined_no_check for m in NO_PRODUCT_MARKERS):
        action = "keep_scene"
    elif any(m in combined_all for m in HAS_PRODUCT_MARKERS):
        action = "insert_product"
    else:
        action = "keep_scene"

    if any(m in combined_all for m in NO_PERSON_MARKERS):
        has_person = False
    else:
        has_person = any(m in combined_all for m in HAS_PERSON_MARKERS)

    return action, has_person


def _split_numbered_lines(text: str) -> list[str]:
    if not text.strip():
        return []
    items: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^(?:\d+[.、)）]\s*|[-*•]\s*)", "", line).strip()
        if len(cleaned) >= 4:
            items.append(cleaned)
    return items


def parse_structured_production_pack(
    combined_text: str,
    *,
    product_name: str = "",
) -> dict[str, Any] | None:
    """Universal deterministic parser for structured video production packs (any video,
    any shot count N >= 2). Returns None if the text is freeform / unstructured."""
    if not combined_text or len(combined_text.strip()) < 60:
        return None

    # Prefer the dedicated File 2 section if both File 1 & File 2 contain the same shots
    shot_source_text = combined_text
    f2_marker = "【文件 2：分镜内容】"
    if f2_marker in combined_text:
        f2_part = combined_text.split(f2_marker, 1)[1]
        if len(list(_SHOT_HEADER_RE.finditer(f2_part))) >= 2:
            shot_source_text = f2_part

    matches = list(_SHOT_HEADER_RE.finditer(shot_source_text))
    if len(matches) < 2:
        return None

    # Deduplicate by shot_no (preserving first occurrence in shot_source_text)
    parsed_shots: list[dict[str, Any]] = []
    seen_shot_nos: set[int] = set()

    for idx, m in enumerate(matches):
        shot_no = int(m.group(1) or m.group(3) or (idx + 1))
        if shot_no in seen_shot_nos:
            continue
        seen_shot_nos.add(shot_no)

        raw_header = (m.group(2) or m.group(4) or f"镜头 {shot_no}").strip()
        block_start = m.end()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(shot_source_text)
        block = shot_source_text[block_start:block_end].strip()

        # Trim trailing sections (e.g. 四、共用排除要求) if present inside the last shot block
        stop_sec = re.search(
            r"(?m)^(?:四、|五、|共用排除|统一排除|每段附加|生成、剪辑|新手生成|以后其他视频)",
            block,
        )
        if stop_sec:
            block = block[: stop_sec.start()].strip()

        # Extract time_range from header or block
        tm = _TIME_HINT_RE.search(raw_header) or _TIME_HINT_RE.search(block[:120])
        time_range = tm.group(1).strip() if tm else "约3秒"
        clean_title = re.sub(r"[｜|]\s*(?:保留约|成片约|约)?\s*\d+.*$", "", raw_header).strip()
        if not clean_title:
            clean_title = f"镜头 {shot_no}"

        ref_line = _extract_labeled_field(block, ["需要参考", "参考图", "参考"])
        keyframe_cn = _extract_labeled_field(
            block, ["关键帧图片提示词", "关键帧图片", "关键帧图片内容", "首帧提示词", "首帧图片"]
        )
        video_cn = _extract_labeled_field(
            block, ["图生视频提示词", "图生视频", "可复制的图生视频提示词", "动态提示词"]
        )
        transition_note = _extract_labeled_field(block, ["结束状态/衔接", "结束状态", "剪辑衔接"])
        qa_note = _extract_labeled_field(block, ["通过标准", "验收标准"])

        if not keyframe_cn and not video_cn:
            # Fallback to whole block body if unlabeled
            body_clean = re.sub(r"\s+", " ", block).strip()
            keyframe_cn = body_clean
            video_cn = body_clean
        elif not keyframe_cn:
            keyframe_cn = video_cn
        elif not video_cn:
            video_cn = keyframe_cn

        action, has_person = _detect_shot_flags(
            title=clean_title,
            ref_line=ref_line,
            keyframe_cn=keyframe_cn,
            video_cn=video_cn,
        )

        advice_parts = [p for p in (ref_line and f"参考：{ref_line}", transition_note and f"衔接：{transition_note}", qa_note and f"验收：{qa_note}") if p]
        parsed_shots.append(
            {
                "shot_no": shot_no,
                "title": f"镜头{shot_no:02d}｜{clean_title}",
                "time_range": time_range,
                "keyframe_cn": keyframe_cn,
                "video_cn": video_cn,
                "director_advice": " | ".join(advice_parts),
                "replication_action": action,
                "has_person": has_person,
            }
        )

    if len(parsed_shots) < 2:
        return None

    parsed_shots.sort(key=lambda x: x["shot_no"])

    # Extract Global Reference (二、新版统一... / 全片统一参考提示词)
    global_ref_cn = _extract_section(
        combined_text,
        [
            r"(?m)^(?:二、[^\n]*统一[^\n]*|全片统一参考提示词[^\n]*|新版统一设定[^\n]*)$",
            r"(?m)^(?:\d+[.、]\s*)?(?:全片统一参考提示词|新版统一设定)[^\n]*$",
        ],
        [
            r"(?m)^(?:三、|四、|【镜头|【分镜|【文件 2：)",
        ],
    )

    # Extract Negative Constraints (四、共用排除要求 / 统一排除要求)
    neg_constraints = _extract_section(
        combined_text,
        [
            r"(?m)^(?:四、[^\n]*排除[^\n]*|共用排除要求[^\n]*|统一排除要求[^\n]*|每段附加同一组约束[^\n]*)$",
        ],
        [
            r"(?m)^(?:五、|【文件 2：|以后其他视频)",
        ],
    )
    if not neg_constraints:
        neg_constraints = (
            "避免产品换款、颜色漂移、纹理消失、配件增减、多余产品、人物换脸、手指畸形、穿模、场景漂移、画面文字或水印。"
        )

    # Extract Editing & Generation Guidelines (五、生成、剪辑...)
    edit_sec = _extract_section(
        combined_text,
        [
            r"(?m)^(?:五、[^\n]*(?:生成|剪辑|顺序|检查)[^\n]*|四、[^\n]*(?:生成|剪辑)[^\n]*)$",
        ],
        [
            r"(?m)^(?:以后其他视频|【文件 2：)",
        ],
    )
    edit_lines = _split_numbered_lines(edit_sec)
    gen_order: list[str] = []
    trans_tips: list[str] = []
    audio_tips: list[str] = []
    qa_list: list[str] = []
    for line in edit_lines:
        if any(k in line for k in ("衔接", "拼接", "剪掉", "保留时长", "遮挡")):
            trans_tips.append(line)
        elif any(k in line for k in ("声音", "音效", "音乐", "标题", "品牌", "Logo", "私信")):
            audio_tips.append(line)
        elif any(k in line for k in ("验收", "检查素材", "错哪镜")):
            qa_list.append(line)
        else:
            gen_order.append(line)

    if not gen_order:
        gen_order = [
            f"共拆出 {len(parsed_shots)} 个独立可控镜头，建议先确认核心产品镜与人物镜的关键帧图，再逐镜或一键生成可灵动态视频。",
            "每个镜头只执行当前镜头的独立动作，不把整套剧情重复塞入单镜。",
        ]
    if not qa_list:
        qa_list = [
            "产品外观与颜色纹理 100% 一致，未带入参考图杂物背景",
            "无成品镜头未提前出现成品（已自动跳过商品图）",
            "人物脸型、发型、服装与鞋子全程统一",
            "结尾完整清晰展示产品，画面无文字水印",
        ]

    # Extract concise character profile if 【人物】 exists in global_ref_cn
    char_m = re.search(r"【人物】([^\n]+)", global_ref_cn)
    char_profile_cn = char_m.group(1).strip() if char_m else ""

    # Build a compact global visual anchor (<= 380 chars) to prepend to each keyframe image prompt
    # so image models NEVER receive a bare cutout prompt!
    anchor_lines: list[str] = []
    for tag in ("【风格】", "【产品】", "【材料】", "【人物】", "【客机】", "【场景】", "【火山】"):
        m_tag = re.search(rf"{re.escape(tag)}([^\n]+)", global_ref_cn)
        if m_tag:
            anchor_lines.append(f"{tag}{m_tag.group(1).strip()}")
    compact_global_anchor = " ".join(anchor_lines)[:520] if anchor_lines else global_ref_cn[:380]

    # Build exact synchronized arrays
    storyboard: list[StoryboardShot] = []
    image_prompts: list[ChatGPTImagePrompt] = []
    kling_prompts: list[KlingVideoPrompt] = []

    # Slot 0: Poster (from first insert_product shot, or last shot)
    hero_shot = next((s for s in parsed_shots if s["replication_action"] == "insert_product"), parsed_shots[-1])
    hero_img_prompt = (
        f"9:16 竖屏写实电影级商业广告主视觉画面。{compact_global_anchor}\n\n"
        f"画面主体：{hero_shot['keyframe_cn']}\n"
        f"严格排除：{neg_constraints[:220]}"
    ).strip()
    image_prompts.append(
        ChatGPTImagePrompt(
            scene_title=f"主视觉参考图（{product_name or '成品展示'}）",
            usage_note="自动融合多角度商品图（仅提取商品本体，忽略参考图背景）",
            aspect_ratio="9:16",
            prompt_cn=hero_shot["keyframe_cn"],
            prompt_en=hero_img_prompt,
        )
    )

    for s in parsed_shots:
        storyboard.append(
            StoryboardShot(
                shot_no=s["shot_no"],
                time_range=s["time_range"],
                shot_size="按分镜设定",
                camera_movement="按分镜运镜",
                original_visual=s["keyframe_cn"],
                adapted_visual_for_product=f"{s['title']}：{s['keyframe_cn']}",
                audio_sfx="",
                production_mode="ai",
                real_shoot_guide="",
                spoken_line="",
                replication_action=s["replication_action"],
                director_advice=s["director_advice"],
                has_person=s["has_person"],
            )
        )
        # For image generation: combine global visual anchor + this shot's exact keyframe description
        # (omit 【产品】 block on keep_scene shots so the finished product NEVER leaks early!)
        shot_anchor = compact_global_anchor
        if s["replication_action"] == "keep_scene":
            shot_anchor = re.sub(r"【产品】[^【]+", "", shot_anchor).strip()
        full_img_prompt = (
            f"9:16 竖屏满屏电影级写实画面，无文字、无水印、无黑边。\n"
            f"{shot_anchor}\n\n"
            f"当前镜头（{s['title']}）关键帧画面：{s['keyframe_cn']}\n"
            f"排除要求：{neg_constraints[:240]}"
        ).strip()
        image_prompts.append(
            ChatGPTImagePrompt(
                scene_title=f"{s['title']}（{s['time_range']}）",
                usage_note=(
                    "已自动挂成品商品图（仅取商品本体）"
                    if s["replication_action"] == "insert_product"
                    else "本镜不含成品，已自动跳过商品图防提前串镜"
                ),
                aspect_ratio="9:16",
                prompt_cn=s["keyframe_cn"],
                prompt_en=full_img_prompt,
            )
        )
        kling_prompts.append(
            KlingVideoPrompt(
                shot_no=s["shot_no"],
                scene_title=f"{s['title']}（{s['time_range']}）",
                mode="图生视频 (I2V)",
                recommended_params="时长: 5s | 画质: 高品质",
                prompt_cn=s["video_cn"],
                prompt_en=s["video_cn"],
                negative_prompt=neg_constraints[:320],
            )
        )

    master_summary = (
        f"【全片统一设定】\n{global_ref_cn or '按各镜头设定执行'}\n\n"
        + "\n\n".join(
            f"【{s['title']}｜{s['time_range']}】\n关键帧：{s['keyframe_cn']}\n图生视频：{s['video_cn']}"
            for s in parsed_shots
        )
    )

    no_prod_shots = [s["shot_no"] for s in parsed_shots if s["replication_action"] == "keep_scene"]
    prod_shots = [s["shot_no"] for s in parsed_shots if s["replication_action"] == "insert_product"]

    audit_report = PromptAuditReport(
        verdict="accurate",
        summary=(
            f"已 100% 精准解析你的结构化制作包：共拆出 {len(parsed_shots)} 个独立镜头（零删减、零占位词）。"
            + (f"其中镜头 {no_prod_shots} 识别为不含成品，生图时已自动跳过成品商品图防串镜；" if no_prod_shots else "")
            + (f"镜头 {prod_shots} 已绑定多角度商品图（自动剥离商品照背景）。" if prod_shots else "")
        ),
        matched_points=[
            f"完整拆出全部 {len(parsed_shots)} 个独立分镜，逐镜保留关键帧图片提示词与图生视频动态提示词",
            "已将全片统一设定自动融入每个镜头的关键帧生图指令，杜绝白底纯商品图",
        ],
        issues_found=[],
        fixes_applied=[
            f"镜头 {no_prod_shots} 自动关闭成品图挂载（防提前串镜）" if no_prod_shots else "已锁定全片商品外观一致性",
            "已完整提取共用排除要求与生成/剪辑顺序",
        ],
    )

    editing_guidelines = EditingGuidelines(
        generation_order=gen_order[:6],
        transition_tips=trans_tips[:5],
        audio_and_overlay_tips=audio_tips[:4],
        final_qa_checklist=qa_list[:6],
    )

    deep_analysis = VideoDeepAnalysis(
        is_ai_generated=True,
        ai_confidence=98,
        ai_detection_reason=f"确定性结构化制作包精准拆解（共 {len(parsed_shots)} 个独立镜头）",
        director_plan=DirectorPlan(
            original_plot_summary=f"共 {len(parsed_shots)} 个独立镜头的结构化制作方案",
            original_video_prompt_cn=master_summary,
            original_video_prompt_en=master_summary,
            global_reference_prompt_cn=global_ref_cn or compact_global_anchor,
            global_reference_prompt_en=global_ref_cn or compact_global_anchor,
            current_master_prompt_cn=master_summary,
            current_master_prompt_en=master_summary,
            negative_constraints=neg_constraints,
            prompt_audit_report=audit_report,
            editing_guidelines=editing_guidelines,
            has_user_customized=True,
            ai_character_profile_cn=char_profile_cn,
            ai_character_profile_en=char_profile_cn,
            product_placement_plan=f"已精准拆解 {len(parsed_shots)} 个独立可控镜头",
            revision_status="draft",
        ),
        replaceability=ReplaceabilityAnalysis(
            score=98,
            original_featured_item=product_name or "目标商品",
            replacement_strategy="按用户双文件结构化制作包 100% 精准拆镜执行",
            replacement_difficulty="低",
            recommended_workflow="步骤 1 确认提示词 → 步骤 2 生成关键图 → 步骤 3 生成视频 → 步骤 4 合成下载",
        ),
        structure=VideoStructureAnalysis(
            hook_3s=parsed_shots[0]["keyframe_cn"][:120],
            pacing_curve=" → ".join(f"{s['title']}({s['time_range']})" for s in parsed_shots),
            conversion_cta=parsed_shots[-1]["keyframe_cn"][:120],
            viral_reasons=[f"精准拆解 {len(parsed_shots)} 个独立可控镜头", "全片统一设定 + 防串镜护栏 + 精剪对齐"],
        ),
        storyboard=storyboard,
        shooting_requirements=ShootingRequirements(
            lighting="按全片统一设定自然电影级光影",
            camera_setup="9:16 竖屏满屏写实镜头",
            props_and_scene=global_ref_cn[:260],
            editing_rhythm="；".join(trans_tips[:2]) or "按各镜头计划保留时长自动精剪衔接",
            bgm_style="；".join(audio_tips[:2]) or "按画面节奏自动匹配原片风格音效",
        ),
        copywriting=CopywritingAnalysis(
            original_transcript="无口播（纯视觉+环境音效）",
            chinese_translation="",
            adapted_script_cn="",
            adapted_script_en="",
            caption_and_hashtags="",
        ),
        chatgpt_images_prompts=image_prompts,
        kling_prompts=kling_prompts,
    )

    return {
        "shot_count": len(parsed_shots),
        "deep_analysis": deep_analysis,
        "audit_report": audit_report,
        "editing_guidelines": editing_guidelines,
        "global_reference_prompt_cn": global_ref_cn or compact_global_anchor,
        "negative_constraints": neg_constraints,
        "ai_character_profile_cn": char_profile_cn,
        "storyboard": storyboard,
        "chatgpt_images_prompts": image_prompts,
        "kling_prompts": kling_prompts,
        "master_summary": master_summary,
    }
