from __future__ import annotations

import json
from typing import Any

from ..models import ScanSession


def export_session_markdown(session: ScanSession) -> str:
    dna = session.product_dna or {}
    stats = session.funnel_stats or {}
    lines: list[str] = [
        f"# {session.history_title}",
        "",
        f"- **产品名称**：{session.product_name}",
        f"- **扫描模式**：{'三平台爆款雷达' if session.mode == 'radar' else '指定链接直拆'}",
        f"- **覆盖平台**：{', '.join(session.platforms or [])}",
        f"- **用户指令**：{session.user_instruction or '无'}",
        f"- **漏斗统计**：抓取 {stats.get('collected', 0)} 条 → 硬过滤 {stats.get('after_hard_filter', 0)} 条 → 初筛入选 {stats.get('after_screening', 0)} 条 → 最终收录 {len(session.videos)} 条",
        f"- **Token 消耗**：输入 {stats.get('input_tokens', 0):,} / 输出 {stats.get('output_tokens', 0):,}（预估 ¥{stats.get('estimated_cost_cny', 0):.4f}）",
        "",
        "## 一、产品基因卡（Product DNA）",
        f"- **品类**：{dna.get('category', '')}",
        f"- **外观形态**：{dna.get('physical_form', '')}",
        f"- **核心卖点**：{'; '.join(dna.get('core_selling_points', []))}",
        f"- **目标人群**：{dna.get('target_audience', '')}",
        f"- **适配替换槽位**：{'; '.join(dna.get('replaceable_visual_slots', []))}",
        "",
        "---",
        "",
        f"## 二、收录高可替换爆款视频（共 {len(session.videos)} 条）",
        "",
    ]

    for idx, v in enumerate(session.videos, start=1):
        a: dict[str, Any] = v.analysis_json or {}
        rep = a.get("replaceability", {})
        st = a.get("structure", {})
        shoot = a.get("shooting_requirements", {})
        copy = a.get("copywriting", {})

        lines.extend(
            [
                f"### {idx}. [{v.platform.upper()}] {v.title or v.platform_video_id}",
                f"- **原视频链接**：{v.video_url}",
                f"- **数据表现**：播放 `{v.views:,}` | 点赞 `{v.likes:,}` | 赞播比 `{v.engagement_rate:.2f}%`",
                f"- **视频类型**：{'AI 制作' if v.is_ai_generated else '实拍视频'}（置信度 {v.ai_confidence}%）— {a.get('ai_detection_reason', '')}",
                f"- **可替换性评分**：**{v.replaceability_score} / 100**（原核心物品：{v.original_featured_item}）",
                f"- **产品替换方案**：{rep.get('replacement_strategy', '')}",
                "",
                "#### 1) 视频结构拆解",
                f"- **黄金 3 秒钩子**：{st.get('hook_3s', '')}",
                f"- **节奏曲线**：{st.get('pacing_curve', '')}",
                f"- **结尾转化 CTA**：{st.get('conversion_cta', '')}",
                f"- **爆款原因**：{'；'.join(st.get('viral_reasons', []))}",
                "",
                "#### 2) 逐秒分镜表（已替换为你的产品）",
                "| 镜头 | 时间 | 景别 | 运镜 | 原片画面 | 替换为我方产品后的画面 | 音效/BGM |",
                "| :---: | :---: | :---: | :---: | :--- | :--- | :--- |",
            ]
        )

        for shot in a.get("storyboard", []):
            lines.append(
                f"| {shot.get('shot_no', '')} | {shot.get('time_range', '')} | {shot.get('shot_size', '')} | "
                f"{shot.get('camera_movement', '')} | {shot.get('original_visual', '')} | "
                f"{shot.get('adapted_visual_for_product', '')} | {shot.get('audio_sfx', '')} |"
            )

        lines.extend(
            [
                "",
                "#### 3) 拍摄与制作要求",
                f"- **布光**：{shoot.get('lighting', '')}",
                f"- **机位参数**：{shoot.get('camera_setup', '')}",
                f"- **道具与布景**：{shoot.get('props_and_scene', '')}",
                f"- **剪辑节奏**：{shoot.get('editing_rhythm', '')}",
                f"- **BGM 风格**：{shoot.get('bgm_style', '')}",
                "",
                "#### 4) 视频文案",
                f"- **原声/字幕**：{copy.get('original_transcript', '')}",
                f"- **中文翻译**：{copy.get('chinese_translation', '')}",
                f"- **改写中文可用文案**：\n\n> {copy.get('adapted_script_cn', '')}\n",
                f"- **改写英文出海文案**：\n\n> {copy.get('adapted_script_en', '')}\n",
                f"- **推荐标题与标签**：{copy.get('caption_and_hashtags', '')}",
                "",
                "#### 5) ChatGPT Images 提示词（海报 & 分镜首帧图）",
            ]
        )

        for p in a.get("chatgpt_images_prompts", []):
            lines.extend(
                [
                    f"**{p.get('scene_title', '')}**（比例 `{p.get('aspect_ratio', '9:16')}`）",
                    f"使用说明：{p.get('usage_note', '')}",
                    "```text",
                    p.get("prompt_en", ""),
                    "```",
                    f"中文对照：{p.get('prompt_cn', '')}",
                    "",
                ]
            )

        lines.append("#### 6) 可灵 Kling 视频生成提示词")
        for kp in a.get("kling_prompts", []):
            lines.extend(
                [
                    f"**分镜 {kp.get('shot_no', '')} — {kp.get('scene_title', '')}**",
                    f"- 模式：{kp.get('mode', '')}",
                    f"- 推荐参数：`{kp.get('recommended_params', '')}`",
                    "- 中文提示词（直接复制）：",
                    "```text",
                    kp.get("prompt_cn", ""),
                    "```",
                    "- 英文提示词（可灵国际版）：",
                    "```text",
                    kp.get("prompt_en", ""),
                    "```",
                    f"- 负向提示词：`{kp.get('negative_prompt', '')}`",
                    "",
                ]
            )
        lines.append("---\n")

    return "\n".join(lines)


def export_session_json(session: ScanSession) -> str:
    payload = {
        "id": session.id,
        "history_title": session.history_title,
        "product_name": session.product_name,
        "mode": session.mode,
        "status": session.status,
        "user_instruction": session.user_instruction,
        "platforms": session.platforms,
        "filter_config": session.filter_config,
        "product_dna": session.product_dna,
        "funnel_stats": session.funnel_stats,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "videos": [
            {
                "id": v.id,
                "platform": v.platform,
                "platform_video_id": v.platform_video_id,
                "video_url": v.video_url,
                "cover_url": v.cover_url,
                "author_name": v.author_name,
                "title": v.title,
                "duration_sec": v.duration_sec,
                "views": v.views,
                "likes": v.likes,
                "engagement_rate": v.engagement_rate,
                "is_ai_generated": v.is_ai_generated,
                "ai_confidence": v.ai_confidence,
                "replaceability_score": v.replaceability_score,
                "original_featured_item": v.original_featured_item,
                "analysis_mode": v.analysis_mode,
                "analysis": v.analysis_json,
                "token_usage": v.token_usage,
            }
            for v in session.videos
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
