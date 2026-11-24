from __future__ import annotations

import json
from typing import Any

from ..schemas import ProductDNA


def build_product_dna_prompt(
    extracted_text: str,
    user_instruction: str,
    product_name_override: str = "",
    search_strategy: str = "cross_category",
) -> str:
    override_hint = (
        f"用户指定产品名称：{product_name_override}（请优先采用该名称）"
        if product_name_override.strip()
        else "请从产品资料中提炼一个简短精准的中文产品名称（4~16字，适合作为历史记录分类名）"
    )
    if search_strategy == "same_category":
        query_rules = """【搜索词生成策略：同品类 C 端高热模式】
请为每个平台生成 3 个该品类在海外社媒（C端消费者视角）最火的英文短词（2~3词），严禁枯燥的 B2B 采购/批发词（如 wholesale / supplier / fixture / retrofit）。"""
    elif search_strategy == "hybrid":
        query_rules = """【搜索词生成策略：跨品类创意模板 + 同品类混合模式】
每个平台生成 3 个英文短词：
- 第 1、2 个词：跨品类爆款创意广告/AI视觉模板词（严禁带原产品品类词，例如 `ai product commercial`, `cgi product ad`, `fooh cgi advertising`, `3d product animation`, `creative commercial video`, `product popping out`）；
- 第 3 个词：C 端泛品类高热视觉词（严禁 B2B 批发词）。"""
    else:
        query_rules = """【搜索词生成策略：纯跨品类爆款创意模板模式（产品完全解耦）】
用户明确要求：**绝不照着上传的产品素材去搜同品类产品视频！** 系统将使用独立于上传产品的全网跨品类爆款视觉模板库（FOOH 户外巨物 CGI、3D 悬浮/画册弹出、AI 超现实商业大片、无缝创意转场、微缩世界、极简高级商业摄影）去抓取三平台爆款，然后在拆解阶段把原片里的主角物品替换为用户的产品。
因此：
1. 你在本步骤的核心职责是**精准提炼产品外观、材质与卖点**（供后续替换分镜与 AI 提示词使用），以及**准确列出 `category_leak_keywords`**（该产品自身所属品类的中英文关键词，例如 LED 灯填 `["led", "light", "lighting", "lamp", "strip", "fixture", "灯", "灯具", "照明"]`），以便系统在搜索和初筛中彻底屏蔽同品类视频！
2. `search_queries` 字段严禁出现任何与该产品品类相关的词，仅填写全网通用的跨品类爆款创意广告词（系统后续也会通过代码级白名单模板库进行二次强校验与替换）。"""

    return f"""你是顶级海外社媒（TikTok / Instagram Reels / YouTube Shorts）爆款创意总监与 AI 商业广告专家。
请结合用户上传的产品图片/视频关键帧与下方文字资料，提炼结构化的《产品基因卡（Product DNA）》，并制定高播放、高点赞的搜索词策略。

{override_hint}

用户附加雷达指令：
{user_instruction or "寻找高播放、高点赞、视觉创意强、只需将原视频核心物品替换成我方产品就能复刻出爆款的短视频模板"}

产品文字与文档资料：
{extracted_text or "（无纯文本，请重点依据随附图片/视频关键帧识别产品外观、品类与卖点）"}

{query_rules}

请严格输出纯 JSON（不要输出任何额外说明或 markdown 标记），字段必须完全符合以下格式：
{{
  "product_name": "简短精准的产品名称",
  "category": "细分类目",
  "physical_form": "详细描述产品外观、尺寸、颜色、材质、视觉特征（如发光、金属质感、线条感、便携等）",
  "core_selling_points": ["卖点1", "卖点2", "卖点3", "卖点4"],
  "target_audience": "目标受众画像",
  "usage_scenarios": ["核心使用场景1", "核心使用场景2", "核心使用场景3"],
  "replaceable_visual_slots": [
    "跨品类可替换的爆款视觉槽位（例如：画册/杂志弹出3D悬浮展示、户外/室内巨物FOOH创意CGI、极简美学商业大片、微缩场景产品亮相）"
  ],
  "avoid_patterns": [
    "必须剔除的视频形态（纯人脸口播脱口秀、街头采访、纯新闻八卦、游戏录屏、完全没有物品主角位的视频）"
  ],
  "category_leak_keywords": [
    "该产品自身所属品类的 6~12 个中英文关键词（用于跨品类模式下自动屏蔽同品类搜索和同品类视频，严禁填 commercial/creative/ad 等通用词）"
  ],
  "search_queries": {{
    "tiktok": ["搜索词1", "搜索词2", "搜索词3"],
    "instagram": ["搜索词1", "搜索词2", "搜索词3"],
    "youtube": ["搜索词1", "搜索词2", "搜索词3"]
  }}
}}"""


def build_preliminary_screening_prompt(
    product_dna: ProductDNA,
    user_instruction: str,
    candidates: list[dict[str, Any]],
    search_strategy: str = "cross_category",
) -> str:
    dna_json = json.dumps(product_dna.model_dump(), ensure_ascii=False, indent=2)
    candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)
    if search_strategy == "same_category":
        strategy_rules = """【当前模式：同品类高热模式】
请重点筛选与目标产品同品类、画面展示清晰、可直接参考复刻的高热产品短视频。"""
    elif search_strategy == "hybrid":
        strategy_rules = """【当前模式：跨品类创意模板 + 同品类混合模式】
- 无论原视频展示的是什么品类物品（香水、球鞋、家具、耳机、咖啡杯或同品类产品），只要画面创意强、有清晰可替换的主角物品槽位，都给高分；
- 请如实标注 `is_same_category`（原视频核心主角物品是否与目标产品属于同一品类）。"""
    else:
        strategy_rules = f"""【当前模式：严格跨品类爆款视觉模板模式 — 最高优先级铁律！】
用户的核心诉求是：**不要给我找【{product_dna.product_name} / {product_dna.category}】的同品类视频！我要的是三个平台上其他品类的高赞爆款创意视频（例如香水巨物 FOOH CGI、翻开画册沙发 3D 悬浮弹出、运动鞋脑洞无缝转场、小人国微缩施工建造手表/咖啡杯、包包/耳机 AI 超现实商业大片），只要原视频画面元素足够爆款、且里面有一个核心物品槽位，后续就可以把里面的物品替换成用户的产品！**

【严格防偏向规则】：
1. **跨品类高创意 = 90~98 分**：绝对不要因为原片物品（如香水、球鞋、家具、饮料、汽车、手表、护肤品、数码）与目标产品形态不同就扣分！只要原片有炸裂的视觉创意和独立物品主角位，就给 `preliminary_score` 88~98、`visual_creativity_score` 88~98、`is_same_category: false`！
2. **严禁偏向同品类**：如果原视频展示的核心主角物品本身就属于目标产品的同一品类（即【{product_dna.product_name} / {product_dna.category}】），**必须**将 `is_same_category` 标为 `true`（且不要因为“品类一样好替换”就给虚高分）！
3. **精准判定 `is_same_category`**：仅根据视频实际展示的**核心主角物品（`original_featured_item`）**来判断！切勿因为一条香水/球鞋广告的标题里出现 “studio lighting / cinematic light”（摄影打光术语）就误判成灯具同品类！
4. **淘汰无主角位视频**：纯人脸口播、街访、纯剧情段子、新闻八卦、游戏录屏、纯风景无物品主角位 -> `preliminary_score` 0~45，`is_replaceable: false`。"""

    return f"""你是顶级短视频创意总监，负责评估三平台高热视频的**「爆款画面创意价值」**与**「跨品类物品可替换性」**。

{strategy_rules}

目标产品信息（仅用于判断 `is_same_category` 与后续替换参考，切勿用其限制创意品类）：
{dna_json}

用户附加指令：
{user_instruction or "无"}

评分标准（0~100分）：
- **visual_creativity_score（画面创意爆款分）**：评估视频本身的视觉冲击力与创意稀缺度（FOOH 户外巨物 CGI / 3D 悬浮画册弹出 / AI 超现实大片 / 脑洞无缝转场 / 微缩世界定格动画 / 电影级商业摄影给 85~98 分；普通平铺直叙实拍给 50~70 分；无视觉创意给 0~45 分）。
- **preliminary_score（可替换模板分）**：评估该视频是否存在清晰可替换的“主角物品槽位”，把原片主角物品替换成目标产品后能否复刻其爆款视觉结构。

候选视频列表（随附的封面图按 has_cover=true 的顺序一一对应）：
{candidates_json}

请严格输出纯 JSON，不要附加任何解释：
{{
  "results": [
    {{
      "candidate_id": "原样返回候选视频的 candidate_id",
      "preliminary_score": 92,
      "visual_creativity_score": 94,
      "is_same_category": false,
      "original_featured_item": "原视频核心展示物品（例如：巨型香水瓶、悬浮沙发、运动鞋、无线耳机；若无实物写'无明确实物'）",
      "reason": "一句话说明原视频的爆款视觉创意元素是什么、如何把原物品替换成目标产品",
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
6. **智能区分「AI 一键生成」与「手机实拍」分镜**（极其重要！）：
   - 在 `storyboard` 的每个镜头里必须标明 `production_mode`：
     - `"ai"`：适合用 AI 图生图 + 图生视频一键直出（如 FOOH 户外巨物、3D 悬浮、微缩世界、特效转场、高质感空镜海报）；
     - `"real_shoot"`：建议用户直接拿手机 10 秒实拍更真实、转化更高（如真实手持展示、通电亮灯测试、真实安装对比、细节手感特写）；
   - 并给出接地气的大白话 `real_shoot_guide`（机位放哪、怎么拿产品、光线与道具、拍几秒）和 `spoken_line`（该镜头对应的简短口播/字幕句）。

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
      "audio_sfx": "人声/音效/BGM变化",
      "production_mode": "ai",
      "real_shoot_guide": "手机竖屏 2x 焦段对准桌面中央产品，从距产品 40cm 匀速前推至 15cm，拍 3 秒即可",
      "spoken_line": "别划走，这个细节你一定没见过！"
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
