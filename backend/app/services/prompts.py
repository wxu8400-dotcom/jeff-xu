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
        query_rules = """【搜索词生成策略：同品类 C 端高热模式（仅真人实拍 / 写实 AI 真人）】
请为每个平台生成 3 个该品类在海外社媒（C端消费者视角）最火的英文短词（2~3词），必须指向真人实拍或照片级写实 AI 真人短视频；严禁生成动漫/卡通/动画/定格动画相关词，也严禁枯燥的 B2B 采购/批发词（如 wholesale / supplier / fixture / retrofit）。"""
    elif search_strategy == "hybrid":
        query_rules = """【搜索词生成策略：跨品类创意模板 + 同品类混合模式（仅真人实拍 / 写实 AI 真人）】
每个平台生成 3 个英文短词（严禁任何动漫/卡通/animation/stop motion 词）：
- 第 1、2 个词：跨品类真人实景或写实 AI 真人爆款创意广告词（严禁带原产品品类词，例如 `realistic ai commercial`, `viral commercial transition`, `fooh cgi street`, `luxury lifestyle commercial`）；
- 第 3 个词：C 端泛品类真人实拍高热视觉词（严禁 B2B 批发词）。"""
    else:
        query_rules = """【搜索词生成策略：纯跨品类爆款创意模板模式（产品完全解耦，仅真人/写实 AI 真人）】
用户明确要求：**绝不照着上传的产品素材去搜同品类产品视频，也绝不要动漫/卡通/定格动画！** 系统将使用独立于上传产品的全网跨品类真人实拍与写实 AI 真人爆款视觉模板库去抓取三平台爆款，然后在拆解阶段把原片里的主角物品替换为用户的产品。
因此：
1. 你在本步骤的核心职责是**精准提炼产品外观、材质与卖点**（供后续替换分镜与 AI 提示词使用），以及**准确列出 `category_leak_keywords`**（该产品自身所属品类的中英文关键词，例如 LED 灯填 `["led", "light", "lighting", "lamp", "strip", "fixture", "灯", "灯具", "照明"]`），以便系统在搜索和初筛中彻底屏蔽同品类视频！
2. `search_queries` 字段严禁出现任何与该产品品类或动漫/卡通相关的词，仅填写全网通用的真人/写实 AI 跨品类爆款创意广告词（系统后续也会通过代码级白名单模板库进行二次强校验与替换）。"""

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

【画风最高铁律 — 一票否决动漫/卡通/定格动画！（看封面图和标题严格把关！）】
用户明确要求：**只搜索和收录「真人实拍」或「照片级写实 AI 真人」短视频，绝不要任何动漫、卡通或定格动画！**
- **一票否决（必须标 `is_cartoon_or_animation: true`, `is_replaceable: false`, `preliminary_score: 0~20`）**：
  1. 任何 2D 动漫、日漫/国漫、二次元、手绘/插画风动画（如 Animated by Hand、绘本风）；
  2. 任何 3D 卡通人偶、皮克斯/迪士尼风格、塑料玩偶/公仔角色、黏土/泥塑定格动画（如 Wallace & Gromit、木偶、乐高、游戏建模风）；
  3. 任何卡通化/非照片级写实画风——即使播放量几百万、大牌广告，也必须直接淘汰！
- **优先高分收录（`is_cartoon_or_animation: false`, `has_realistic_human: true`）**：
  - 真实人类出镜的实拍商业广告/生活种草/创意转场/剧情反转短片；
  - 或具有真实皮肤纹理、真实相机光影的**照片级写实 AI 真人**短片（如 Kling/Sora/Veo 写实真人商业广告、街头实景 FOOH 真人反应大片）。

{strategy_rules}

目标产品信息（仅用于判断 `is_same_category` 与后续替换参考，切勿用其限制创意品类）：
{dna_json}

用户附加指令：
{user_instruction or "无"}

评分标准（0~100分）：
- **visual_creativity_score（画面创意爆款分）**：在满足「真人实拍 / 照片级写实 AI 真人」的前提下，评估视频的视觉冲击力与创意稀缺度（真人实景脑洞转场 / 街头真人 FOOH 巨物 CGI / 写实 AI 真人商业大片 / 电影级真人生活方式广告给 85~98 分；普通平铺直叙实拍给 55~72 分；动漫卡通或无创意给 0~25 分）。
- **preliminary_score（可替换模板分）**：评估该真人/写实 AI 真人视频是否存在清晰可替换的“主角物品槽位”，把原片主角物品替换成目标产品后能否 1:1 复刻其情节与爆款视觉结构。

候选视频列表（随附的封面图按 has_cover=true 的顺序一一对应，请务必仔细肉眼查看封面画风！）：
{candidates_json}

请严格输出纯 JSON，不要附加任何解释：
{{
  "results": [
    {{
      "candidate_id": "原样返回候选视频的 candidate_id",
      "preliminary_score": 92,
      "visual_creativity_score": 94,
      "is_same_category": false,
      "is_cartoon_or_animation": false,
      "has_realistic_human": true,
      "original_featured_item": "原视频核心展示物品（例如：巨型香水瓶、真皮手袋、咖啡杯、无线耳机；若无实物写'无明确实物'）",
      "reason": "一句话说明原视频的真人/写实AI画风与爆款视觉创意元素，以及如何替换为目标产品",
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
    return f"""你是顶级短视频编导、爆款 1:1 复刻导演兼 AI 视频提示词专家（精通 **可灵 Kling** 视频生成与 **GPT Image / Seedream** 产品融合出图）。
{mode_note}

【核心铁律：1:1 忠实复刻原爆款的情节、分镜与场景，绝不凭空编一个不一样的新视频！】
用户的明确要求：
1. **严格保留原视频的情节、分镜顺序、场景构图、镜头运动与转场节奏**——不能把原片魔改成一个完全不同的故事或无关场景！
2. **人物脱敏换角（全片统一写实 AI 真人）**：如果原视频里出现人物（模特/路人/主播/手部主角），**绝不能照搬原片真人的脸**，也**绝不能做成动漫/卡通/3D玩偶画风**；必须保留这个人物在原片里的**相同情节动作与站位**，并将其替换为一个**全新的、100% 照片级写实真人质感的原创 AI 人物形象**（在 `director_plan.ai_character_profile_cn` 与 `ai_character_profile_en` 中明确写清年龄、性别、真实肤质长相气质、发型、服装穿搭，并在每一个有人物出现的分镜提示词中 100% 复用这个完全一致的写实 AI 真人设定，英文提示词必须包含 `photorealistic real human, natural skin texture, live-action cinema photography, NOT cartoon, NOT anime, NOT 3D doll`！若原片全程无人，则这两个字段写“无人物（纯静物/场景）”）。
3. **像专业导演一样给用户「替换与改写意见」**：
   - 先用 `director_plan.original_plot_summary` 客观还原原爆款视频到底讲了什么情节、每一镜发生什么；
   - 在 `director_plan.product_placement_plan` 里清楚建议：用户的目标产品应该**安排在第几镜出场最自然**、哪些镜头**1:1 原样保留原片场景和情节（`replication_action: "keep_scene"`）**、哪些镜头把原物品**直接替换为目标产品（`replication_action: "insert_product"`）**、哪些镜头因产品属性差异**建议适度微调改写场景（`replication_action: "rewrite_scene"`）**；
   - 在 `director_plan.open_questions_for_user` 提出 2~3 个具体、简洁的导演确认问题，方便用户在正式花钱生图/生视频前先和你对话修改定稿！

目标产品基因卡：
{dna_json}

用户附加指令：
{user_instruction or "无"}

爆款视频基础信息：
{meta_json}

【强制质量规范】
1. **禁止占位符**：所有出现目标产品的分镜、改写文案、生图提示词、可灵提示词中，必须具体写出目标产品的真实外观、材质、颜色、功能特征与卖点，严禁出现 `[你的产品]`、`[产品名]` 等占位符！
2. **不强行塞入产品**：如果原片第 1 镜是人物/氛围铺垫戏（还没到产品出场），则第 1 镜 `replication_action` 标为 `"keep_scene"`，不要硬把用户的产品塞进不该出现的镜头，保持原片的情节反转与悬念！
3. **AI 制作判定**：客观判断原视频是否为 AI / CGI 制作（`is_ai_generated`），给出置信度与判断依据；无论原视频是 AI 还是实拍，都必须完整输出 `chatgpt_images_prompts` 和 `kling_prompts`。
4. **生图提示词规范（`chatgpt_images_prompts` 必须与分镜一一对齐！）**：
   - 第 1 条（索引 0）：爆款主视觉封面海报；
   - 第 2 ~ N+1 条（索引 1..N）：**严格与 `storyboard` 分镜 1..N 一一对应**（不能漏镜、不能跳镜！）；
   - 若该镜包含目标产品（`insert_product` / `rewrite_scene` 或封面海报）：`prompt_en` 开头必须明确声明 `Keep the exact product from the uploaded reference image (preserving its shape, material, color, texture, and logo 100% unchanged),`；
   - 若该镜包含人物（`has_person: true`）：`prompt_en` 必须完整包含 `director_plan.ai_character_profile_en` 中的统一原创 AI 人物外貌与穿搭，确保全片人物不换脸、不撞脸原片真人！
5. **可灵 Kling 提示词规范（与 `storyboard` 分镜 1..N 一一对应）**：
   - 面向可灵 Kling 图生视频 (I2V)，严格复刻原片该镜头的真实物理动作、人物动作、特效与运镜，避免让视频模型生成文字；
   - 给出具体的 `recommended_params` 与防变形 `negative_prompt`。
6. **智能区分「AI 一键生成」与「手机实拍」分镜**：
   - 每个分镜标明 `production_mode`（`"ai"` 或 `"real_shoot"`）、大白话 `real_shoot_guide`、`spoken_line`，以及 `replication_action`、`director_advice`、`has_person`。

请严格输出纯 JSON（不含 markdown 代码块标记以外的文字），字段结构必须与下方完全一致：
{{
  "is_ai_generated": false,
  "ai_confidence": 85,
  "ai_detection_reason": "具体判断依据",
  "director_plan": {{
    "original_plot_summary": "1:1 客观还原原爆款视频的完整情节、场景与反转节奏",
    "ai_character_profile_cn": "全片统一的原创替换 AI 人物形象设定（如：26岁时尚女设计师，微卷深棕色齐肩发，身穿米白色极简西装外套；若原片无人物写'无人物（纯静物/场景）'）",
    "ai_character_profile_en": "A stylish 26-year-old original female designer with shoulder-length dark brown wavy hair wearing a minimalist cream blazer (empty string if no person in video)",
    "product_placement_plan": "导演替换建议：说明目标产品安排在第几镜出场、哪些镜头 1:1 原样保留、哪些场景建议适度改写及原因",
    "open_questions_for_user": [
      "当前为你设计的原创 AI 人物形象是否满意，还是想换成其他年龄/风格/穿搭？",
      "目标产品安排在第 X 镜出场并保留原片前段悬念，你是否同意或想提前出场？"
    ],
    "revision_status": "draft",
    "revision_history": []
  }},
  "replaceability": {{
    "score": 90,
    "original_featured_item": "原视频核心展示物品",
    "replacement_strategy": "具体可落地的 1:1 替换方案：保留原片情节与场景构图，替换原物品与原人物",
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
      "original_visual": "原视频该镜头完整画面、场景、人物动作与物品内容",
      "adapted_visual_for_product": "1:1 沿用原片场景与情节，替换新 AI 人物/目标产品后的精准分镜画面",
      "audio_sfx": "人声/音效/BGM变化",
      "production_mode": "ai",
      "real_shoot_guide": "手机竖屏 2x 焦段对准桌面中央产品，从距产品 40cm 匀速前推至 15cm，拍 3 秒即可",
      "spoken_line": "别划走，这个细节你一定没见过！",
      "replication_action": "keep_scene",
      "director_advice": "本镜 1:1 保留原片开场悬念场景与动作，仅将原片真人替换为统一的原创 AI 人物，暂不提前暴露产品",
      "has_person": true
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
      "usage_note": "在工坊一键生成，自动融合你的产品参考图",
      "aspect_ratio": "9:16",
      "prompt_en": "Keep the exact product from the uploaded reference image...",
      "prompt_cn": "严格保持上传参考图中产品的外观、材质、颜色与细节完全一致..."
    }}
  ],
  "kling_prompts": [
    {{
      "shot_no": 1,
      "scene_title": "分镜1：黄金3秒亮相",
      "mode": "图生视频 (I2V) — 使用分镜1首帧图",
      "recommended_params": "时长: 5s | 画质: 高品质 | 运镜: 缓慢推进 | 创意相关性: 0.5",
      "prompt_cn": "可直接用于可灵的完整中文动作与运镜提示词",
      "prompt_en": "Direct English motion & camera prompt for Kling AI",
      "negative_prompt": "变形, 模糊, 产品Logo扭曲, 穿模, 多余手指, 闪烁, 画面撕裂, 水印, 杂乱文字"
    }}
  ]
}}"""


def build_director_revision_prompt(
    *,
    product_dna: ProductDNA,
    current_analysis: dict[str, Any],
    user_feedback: str,
    revision_history: list[dict[str, Any]],
) -> str:
    dna_json = json.dumps(product_dna.model_dump(), ensure_ascii=False, indent=2)
    curr_json = json.dumps(current_analysis, ensure_ascii=False, indent=2)
    hist_json = json.dumps(revision_history[-8:], ensure_ascii=False, indent=2)

    return f"""你是用户的专属**爆款短视频 1:1 复刻导演**。用户正在和你共创、打磨这条爆款视频的复刻分镜方案（还没开始花钱生图/生视频）。
请严格遵照用户的最新修改意见，对当前的 `analysis` 方案做精准修改，并**同步更新所有相关字段**，确保下一步点击生图和生视频时 100% 按照用户定稿执行！

【修改铁律】
1. **严格保留 1:1 原片情节与未被用户要求改动的分镜**：用户没要求改的场景、镜头、节奏不要乱动！
2. **全链路同步更新**：
   - 如果用户修改了**人物形象**（如年龄/性别/国籍/穿搭）→ 必须同时更新 `director_plan.ai_character_profile_cn`、`director_plan.ai_character_profile_en`，以及**所有 `has_person: true` 分镜的 `adapted_visual_for_product`、`chatgpt_images_prompts`、`kling_prompts`**！
   - 如果用户调整了**产品出场分镜**（如“产品提前到第2镜出场”或“第1镜不要出现产品”）→ 必须同步更新对应分镜的 `replication_action`（`"keep_scene"` / `"insert_product"` / `"rewrite_scene"`）、`director_advice`、`adapted_visual_for_product`、`chatgpt_images_prompts`（含产品镜保留 `Keep the exact product from the uploaded reference image...`，不含产品镜移除产品描述！）和 `kling_prompts`！
   - 如果用户改了**剧情/场景/口播文案** → 同步更新 `storyboard`、`copywriting`（中英文脚本）、`chatgpt_images_prompts`、`kling_prompts`！
3. **`chatgpt_images_prompts` 索引对齐**：索引 0 为主视觉海报，索引 1..N 严格一一对应 `storyboard` 的分镜 1..N！
4. **`kling_prompts` 对齐**：与 `storyboard` 分镜 1..N 严格一一对应！
5. 用自然、专业的导演口吻在 `director_reply` 里简洁回复用户：说明你改了哪几个分镜、怎么落实了他的想法，并询问是否还有需要微调的地方或可以直接锁定定稿。

目标产品基因卡：
{dna_json}

之前的导演共创对话记录：
{hist_json}

当前完整分镜方案 JSON：
{curr_json}

用户的最新修改意见（最高优先级，必须逐条落实）：
{user_feedback}

请严格输出纯 JSON（不要附加任何 markdown 以外的说明文字），结构如下：
{{
  "director_reply": "给用户的导演回复（简洁清楚说明改了哪些镜头、人物或产品植入位置）",
  "changed_shots": [1, 2],
  "analysis": {{
    "...完整的更新后 VideoDeepAnalysis 对象，保留全部原有字段结构..."
  }}
}}"""
