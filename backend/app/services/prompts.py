from __future__ import annotations

import json
from typing import Any

from ..schemas import ProductDNA


def build_product_dna_prompt(
    extracted_text: str,
    user_instruction: str,
    product_name_override: str = "",
) -> str:
    override_hint = (
        f"用户指定产品名称：{product_name_override}（请优先采用该名称）"
        if product_name_override.strip()
        else "请从产品资料中提炼一个简短精准的中文产品名称（4~16字，适合作为历史记录分类名）"
    )
    return f"""你是顶级跨境电商短视频爆款策略专家。请结合用户上传的产品图片/视频关键帧与下方文字资料，提炼结构化的《产品基因卡（Product DNA）》，用于后续在 TikTok、Instagram Reels、YouTube Shorts 上精准搜索“高播放、高点赞且物品可替换为该产品”的爆款短视频。

{override_hint}

用户附加雷达指令：
{user_instruction or "无额外指令，请寻找最容易爆单、视觉冲击力强、方便替换成我方产品的短视频模板"}

产品文字与文档资料：
{extracted_text or "（无纯文本，请重点依据随附图片/视频关键帧识别产品外观、品类与卖点）"}

请严格输出纯 JSON（不要输出任何额外说明或 markdown 标记），字段必须完全符合以下格式：
{{
  "product_name": "简短精准的产品名称",
  "category": "细分类目",
  "physical_form": "详细描述产品外观、尺寸、颜色、材质、手持/桌面/穿戴等视觉形态特征",
  "core_selling_points": ["卖点1", "卖点2", "卖点3", "卖点4"],
  "target_audience": "目标受众画像",
  "usage_scenarios": ["核心使用场景1", "核心使用场景2", "核心使用场景3"],
  "replaceable_visual_slots": [
    "适合替换的爆款视频展示槽位（例如：桌面开箱特写、手持痛点对比、前后效果实测、创意微缩/AI视觉变装）"
  ],
  "avoid_patterns": [
    "必须剔除的视频形态（例如：纯人脸口播无实物、大型家具汽车、强名人IP剧情）"
  ],
  "search_queries": {{
    "tiktok": ["3个在TikTok最容易搜出高播高赞实物展示爆款的英文/目标市场搜索词"],
    "instagram": ["3个在Instagram Reels最容易搜出高赞好物/创意视觉视频的关键词"],
    "youtube": ["3个在YouTube Shorts最容易搜出高播放实物测评/创意展示的搜索词"]
  }}
}}"""


def build_preliminary_screening_prompt(
    product_dna: ProductDNA,
    user_instruction: str,
    candidates: list[dict[str, Any]],
) -> str:
    dna_json = json.dumps(product_dna.model_dump(), ensure_ascii=False, indent=2)
    candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)
    return f"""你是短视频选品与“产品可替换性”严苛审核官。你的任务是在极低成本下，仅根据候选视频的标题、文案摘要、时长以及对应顺序的封面图，判断这些高热视频中的核心物品是否能**自然、高还原度地替换成用户的目标产品**。

目标产品基因卡：
{dna_json}

用户附加指令：
{user_instruction or "无"}

评分标准（0~100分，严格打分，宁缺毋滥）：
- 85~100分（极佳）：画面以具体实物展示/痛点对比/开箱/使用演示/创意视觉为核心，物品体积与使用动作与目标产品高度匹配，替换为目标产品后完全不违和且极易爆量。
- 65~84分（可用）：有一定物品展示位，稍作场景或道具调整即可通过实拍或 AI（ChatGPT Images + 可灵 Kling）替换成目标产品。
- 0~64分（淘汰）：纯口播无道具、纯新闻/八卦/街访、强依赖特定名人/固定IP剧情、或物品形态差距极大（如把大汽车替换成小口红），一律判为不可替换（<65分）。

候选视频列表（随附的封面图按 has_cover=true 的顺序一一对应）：
{candidates_json}

请严格输出纯 JSON，不要附加任何解释：
{{
  "results": [
    {{
      "candidate_id": "原样返回候选视频的 candidate_id",
      "preliminary_score": 88,
      "original_featured_item": "原视频核心展示物品（若无实物写'无明确实物'）",
      "reason": "一句话说明为什么可替换或为什么淘汰",
      "is_replaceable": true
    }}
  ]
}}"""


def build_deep_analysis_prompt(
    product_dna: ProductDNA,
    user_instruction: str,
    video_meta: dict[str, Any],
    analysis_mode: str,
) -> str:
    dna_json = json.dumps(product_dna.model_dump(), ensure_ascii=False, indent=2)
    meta_json = json.dumps(video_meta, ensure_ascii=False, indent=2)
    mode_note = (
        "你正在直接观看该视频的完整画面与音频流，请精确捕捉每一个转场、运镜、景别、光影细节与原声台词。"
        if analysis_mode == "native_video"
        else "当前无法拉取原视频流，已降级为封面图+元数据深度推演模式，请结合封面构图与标题文案给出高度可落地的复刻分镜与提示词。"
    )
    return f"""你是顶级短视频编导、商业摄影指导兼 AI 视频生成提示词专家（精通 **可灵 Kling** 视频生成与 **ChatGPT Images** 产品融合出图）。
{mode_note}

请针对随附的爆款短视频，结合用户上传的目标产品基因卡，完成深度拆解并产出可直接落地复刻、直接复制使用的提示词。

目标产品基因卡（必须将原视频核心物品彻底替换为该产品）：
{dna_json}

用户附加指令：
{user_instruction or "无"}

爆款视频基础信息：
{meta_json}

【强制质量规范】
1. **禁止占位符**：所有分镜、改写文案、ChatGPT Images 提示词、可灵 Kling 提示词中，必须具体写出该产品的真实外观、材质、颜色与卖点，严禁出现 `[你的产品]`、`[产品名]` 等敷衍占位符！
2. **AI 制作判定**：客观判断原视频是否为 AI 制作（`is_ai_generated`），给出置信度与判断依据；无论原视频是 AI 制作还是实拍，都必须完整输出 `chatgpt_images_prompts` 和 `kling_prompts`。
3. **ChatGPT Images 提示词规范**（至少输出 4 条：第 1 条为“爆款主视觉/封面海报”，第 2~4+ 条对应关键分镜的首帧参考图）：
   - 专门面向 ChatGPT Images 图生图/融合场景设计；
   - `prompt_en` 必须是一段可直接复制的详尽英文自然语言指令，开头明确声明：Keep the exact product from the uploaded reference image (preserving its shape, material, color, texture, and logo 100% unchanged), 然后详述构图、手部/桌面交互、镜头焦段、真实商业摄影光影、背景氛围与画幅比例；
   - 同时给出准确的 `prompt_cn`。
4. **可灵 Kling 提示词规范**（与核心分镜一一对应，3~6 条）：
   - 面向可灵 Kling 图生视频 (I2V) / 首尾帧工作流；
   - `prompt_cn` 与 `prompt_en` 遵循可灵高出片公式：**主体与产品细节 + 流畅真实的物理动作/光影动态 + 明确运镜指令（如缓慢推进/环绕/俯拍拉远） + 氛围与电影级质感**；避免让视频模型生成文字；
   - 给出具体的 `recommended_params`（时长 5s/10s、画质模式、运镜建议、创意相关性）与防变形 `negative_prompt`。

请严格输出纯 JSON（不含 markdown 代码块标记以外的文字），字段结构必须与下方完全一致：
{{
  "is_ai_generated": false,
  "ai_confidence": 85,
  "ai_detection_reason": "具体判断依据",
  "replaceability": {{
    "score": 90,
    "original_featured_item": "原视频核心展示物品",
    "replacement_strategy": "具体可落地的替换方案：如何把原物品换成目标产品，保留原片哪些爆款视觉钩子",
    "replacement_difficulty": "低",
    "recommended_workflow": "实拍复刻 + AI复刻双方案皆可"
  }},
  "structure": {{
    "hook_3s": "黄金3秒画面+听觉钩子拆解",
    "pacing_curve": "全片时间轴节奏与情绪推进曲线",
    "conversion_cta": "结尾转化引导与下单刺激点",
    "viral_reasons": ["爆款原因1", "爆款原因2", "爆款原因3"]
  }},
  "storyboard": [
    {{
      "shot_no": 1,
      "time_range": "00:00-00:03",
      "shot_size": "特写",
      "camera_movement": "快速推镜",
      "original_visual": "原视频该镜头画面内容",
      "adapted_visual_for_product": "替换为目标产品后的精准分镜画面",
      "audio_sfx": "人声/音效/BGM变化"
    }}
  ],
  "shooting_requirements": {{
    "lighting": "灯光与布光方案",
    "camera_setup": "机位、角度、焦段与手机/相机拍摄参数",
    "props_and_scene": "场景与道具清单",
    "editing_rhythm": "剪辑节奏、转场、花字与调色风格",
    "bgm_style": "BGM情绪、BPM与卡点建议"
  }},
  "copywriting": {{
    "original_transcript": "原视频语音转录与字幕文案",
    "chinese_translation": "原视频文案准确中文翻译",
    "adapted_script_cn": "结合目标产品核心卖点改写的直接可用中文口播/字幕脚本",
    "adapted_script_en": "结合目标产品核心卖点改写的适合TikTok/INS/YT出海投放的英文口播/字幕脚本",
    "caption_and_hashtags": "可直接发布的标题文案 + 8~10个高流量精准标签"
  }},
  "chatgpt_images_prompts": [
    {{
      "scene_title": "爆款主视觉海报（封面图）",
      "usage_note": "在 ChatGPT 中上传你的产品实拍图，然后直接复制下方提示词发送",
      "aspect_ratio": "9:16",
      "prompt_en": "Keep the exact product from the uploaded reference image...",
      "prompt_cn": "严格保持上传参考图中产品的外观、材质、颜色与细节完全一致..."
    }}
  ],
  "kling_prompts": [
    {{
      "shot_no": 1,
      "scene_title": "分镜1：黄金3秒亮相",
      "mode": "图生视频 (I2V) — 上传上方分镜1首帧图后粘贴下方提示词",
      "recommended_params": "时长: 5s | 画质: 高品质 | 运镜: 缓慢推进 | 创意相关性: 0.5",
      "prompt_cn": "可直接复制到可灵中文版的完整提示词",
      "prompt_en": "Direct copy-paste English prompt for Kling AI",
      "negative_prompt": "变形, 模糊, 产品Logo扭曲, 穿模, 多余手指, 闪烁, 画面撕裂, 水印, 杂乱文字"
    }}
  ]
}}"""
