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
    return f"""你是顶级海外社媒（TikTok / Instagram Reels / YouTube Shorts）爆款创意总监与 AI 商业广告专家。
请结合用户上传的产品图片/视频关键帧与下方文字资料，提炼结构化的《产品基因卡（Product DNA）》，并制定**高播放、高点赞、可跨品类替换产品**的爆款搜索词策略。

{override_hint}

用户附加雷达指令：
{user_instruction or "寻找高播放、高点赞、视觉创意强、只需将原视频核心物品替换成我方产品就能复刻出爆款的短视频模板"}

产品文字与文档资料：
{extracted_text or "（无纯文本，请重点依据随附图片/视频关键帧识别产品外观、品类与卖点）"}

【核心搜索词生成铁律 — 极其重要！】
我们**不是**在找枯燥的 B2B 工厂安装视频，而是要找**“爆款视觉创意模板”**——只要原视频里有一个清晰的物品主角位（例如：画册翻开产品 3D 悬浮弹出、FOOH 户外巨物 CGI 广告、AI 创意变装、极简美学开箱、前后改造视觉冲击、光影氛围展示等），即使原视频卖的是家具/台灯/音箱/香水/潮玩，我们也能把里面的物品替换成用户的产品变成爆款！

因此，为每个平台生成的 3 个英文搜索词 **必须严格采用「双轨策略」**：
- **第 1 个词（跨品类 AI / CGI 创意广告爆款词）**：结合产品物理特征（如长条/发光/空间/便携/材质），生成海外社媒极高播放量的创意广告模板词（例如：`ai product commercial`, `cgi product ad`, `3d product animation`, `fooh cgi advertising`, `creative product video`, `surreal product commercial`）。
- **第 2 个词（跨品类视觉美学/空间改造爆款词）**：找跨品类同调性高赞视觉模板（例如针对灯具/家居用 `minimalist room transformation`, `aesthetic lighting glow up`, `creative furniture ad`；针对小家电/日用用 `aesthetic product showcase`, `satisfying unboxing`, `viral design gadget`）。
- **第 3 个词（C端泛品类高热词）**：用海外普通消费者爱看的短词（2~3个单词为佳），**严禁生成枯燥的 B2B 采购/工程长尾词**（严禁出现 `wholesale`, `supplier`, `vapor tight`, `batten`, `retrofit`, `commercial electrician` 等几乎零播放的词汇！）。

请严格输出纯 JSON（不要输出任何额外说明或 markdown 标记），字段必须完全符合以下格式：
{{
  "product_name": "简短精准的产品名称",
  "category": "细分类目",
  "physical_form": "详细描述产品外观、尺寸、颜色、材质、视觉特征（如发光、金属质感、线条感、便携等）",
  "core_selling_points": ["卖点1", "卖点2", "卖点3", "卖点4"],
  "target_audience": "目标受众画像",
  "usage_scenarios": ["核心使用场景1", "核心使用场景2", "核心使用场景3"],
  "replaceable_visual_slots": [
    "跨品类可替换的爆款视觉槽位（例如：画册/杂志弹出3D悬浮展示、户外/室内巨物FOOH创意CGI、暗到亮空间氛围改造、极简桌面/墙面产品特写大片）"
  ],
  "avoid_patterns": [
    "必须剔除的视频形态（仅排除：纯人脸口播脱口秀、街头采访、纯新闻八卦、游戏录屏、完全没有物品主角位的视频）"
  ],
  "search_queries": {{
    "tiktok": ["跨品类AI/CGI创意词", "跨品类视觉美学/改造词", "C端泛品类高热短词"],
    "instagram": ["跨品类AI/CGI创意词", "跨品类视觉美学/创意广告词", "C端泛品类高热短词"],
    "youtube": ["跨品类AI/CGI创意词", "跨品类创意产品展示词", "C端泛品类高热短词"]
  }}
}}"""


def build_preliminary_screening_prompt(
    product_dna: ProductDNA,
    user_instruction: str,
    candidates: list[dict[str, Any]],
) -> str:
    dna_json = json.dumps(product_dna.model_dump(), ensure_ascii=False, indent=2)
    candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)
    return f"""你是顶级短视频创意总监，负责评估高热视频的**「跨品类产品可替换性」**。

【极其重要的核心原则：鼓励跨品类借壳复刻！】
我们的目的**不是**只找同品类视频！
举例说明：如果用户卖的是“LED 线性灯”，而候选视频是一条“翻开极简画册，一把家具长凳从书页里 3D 悬浮弹出来”的爆款视频，或者一条“街头巨物 CGI 香水广告”、或者一条“极简氛围台灯开箱/空间前后改造”——这些视频的核心本质都是**【强视觉钩子 + 独立物品主角槽位】**，只需把原视频里的家具/香水/台灯替换为用户的 LED 线性灯（用实拍或 ChatGPT Images + 可灵 Kling AI 复刻），就能做出同款爆款！这类跨品类爆款视频应该给 **80~98 高分**！

目标产品基因卡：
{dna_json}

用户附加指令：
{user_instruction or "无"}

评分标准（0~100分）：
- **85~100分（极佳爆款模板）**：AI/CGI创意产品广告、3D悬浮/画册弹出/微缩/FOOH巨物广告、极简美学产品特写、强视觉反差前后改造、高质感开箱或光影展示——**不论原视频展示的是什么品类物品**，只要把主角物品换成目标产品就能成立且很吸睛！
- **65~84分（良好可替换）**：视频中存在明确的实物展示、空间场景演示、创意转场或产品对比，稍作构图或场景微调即可替换为目标产品。
- **0~59分（直接淘汰）**：纯人脸口播/播客、街头采访、纯搞笑段子/情侣剧情、纯唱歌跳舞、新闻资讯、游戏录屏、完全找不到“物品展示主角位”的视频。

候选视频列表（随附的封面图按 has_cover=true 的顺序一一对应）：
{candidates_json}

请严格输出纯 JSON，不要附加任何解释：
{{
  "results": [
    {{
      "candidate_id": "原样返回候选视频的 candidate_id",
      "preliminary_score": 88,
      "original_featured_item": "原视频核心展示物品或创意载体（若无实物写'无明确实物'）",
      "reason": "一句话说明原视频的视觉创意是什么、为什么适合（或不适合）替换成目标产品",
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
    return f"""你是顶级短视频编导、商业广告创意总监兼 AI 视频提示词专家（精通 **可灵 Kling** 视频生成与 **ChatGPT Images** 产品融合出图）。
{mode_note}

请针对随附的高热爆款短视频（注意：它可能是同品类视频，也可能是**跨品类创意视觉模板**），彻底拆解它的爆款结构与镜头语言，并将原视频的核心主角物品**创造性地、无缝替换为用户的目标产品**，产出可直接复制落地的拆解报告与 AI 提示词。

目标产品基因卡（必须将原视频核心物品彻底替换为该产品）：
{dna_json}

用户附加指令：
{user_instruction or "无"}

爆款视频基础信息：
{meta_json}

【强制质量规范】
1. **禁止占位符**：所有分镜、改写文案、ChatGPT Images 提示词、可灵 Kling 提示词中，必须具体写出目标产品的真实外观、材质、颜色、功能特征与卖点，严禁出现 `[你的产品]`、`[产品名]` 等敷衍占位符！
2. **跨品类巧妙融合**：如果原视频是跨品类创意模板（例如家具画册悬浮、CGI 巨物、空间美学展示等），请在 `replacement_strategy` 与 `storyboard` 中详细设计如何保留原视频最抓眼球的视觉魔法/构图节奏，同时把目标产品的独特优势（例如灯具的发光氛围、数码的精致质感等）自然融合进去！
3. **AI 制作判定**：客观判断原视频是否为 AI / CGI 制作（`is_ai_generated`），给出置信度与判断依据；无论原视频是 AI 制作还是实拍，都必须完整输出 `chatgpt_images_prompts` 和 `kling_prompts`。
4. **ChatGPT Images 提示词规范**（至少输出 4 条：第 1 条为“爆款主视觉/封面海报”，第 2~4+ 条对应关键分镜的首帧参考图）：
   - 专门面向 ChatGPT Images 图生图/融合场景设计；
   - `prompt_en` 必须是一段可直接复制的详尽英文自然语言指令，开头明确声明：Keep the exact product from the uploaded reference image (preserving its shape, material, color, texture, and logo 100% unchanged), 然后详述构图、光影融合、真实商业摄影质感、背景元素与画幅比例；
   - 同时给出准确的 `prompt_cn`。
5. **可灵 Kling 提示词规范**（与核心分镜一一对应，3~6 条）：
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
    "replacement_strategy": "具体可落地的替换方案：如何保留原片爆款视觉结构，把原物品无缝换成目标产品",
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
