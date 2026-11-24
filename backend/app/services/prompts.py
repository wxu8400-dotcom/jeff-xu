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
    director_memory_block: str = "",
) -> str:
    dna_json = json.dumps(product_dna.model_dump(), ensure_ascii=False, indent=2)
    meta_json = json.dumps(video_meta, ensure_ascii=False, indent=2)
    memory_section = f"\n\n{director_memory_block}\n" if director_memory_block.strip() else ""
    mode_note = (
        "你正在直接观看该视频从 0.1 秒第一帧到结尾的全部高清画面帧/视频流，请务必从第 1 张图（0.1 秒开场第一帧）开始逐帧看清，绝不漏掉开场环境与人物位置！"
        if analysis_mode == "native_video"
        else "当前无法拉取原视频流，已降级为封面图+元数据推演模式，请忠实依据封面构图与标题还原原片画面。"
    )
    return f"""你是顶级视觉还原专家与 AI 视频提示词工程师（精通 **可灵 Kling** 与 **GPT Image / Seedream**）。
{mode_note}{memory_section}

【最高铁律：第一步只做 100% 忠实的「原视频画面与提示词还原」，绝不擅自改写剧本！】
用户的核心工作流是：**你先把原视频从头到尾的真实画面还原成精准的「原视频提示词」展示给用户 → 然后等用户说出他想替换的人物/场景/物品 → 用户没提到的地方全部保持原视频不变！**
因此在本步骤中，你必须严格遵守：
1. **死盯第 1 帧（0.1 秒开场）到最后一帧的真实画面**：
   - 仔细看清开场第一帧：人物是谁、**坐在哪里还是站在哪里**（例如坐在飞机客舱里、坐在车里、站在街上）、窗外或背景是什么、手里拿着什么物品、做了什么动作（如往窗外/火山口扔下某物）、随后发生了什么爆炸/弹出/转场变化、最后落在什么地方！
   - **严禁凭空脑补原视频没有的东西**（看不清的细节如实按视觉外观描述，绝不胡编“炸鸡”等无关物品）！
2. **输出整段连贯的《原视频完整还原提示词》（不要写“分镜1、分镜2”字样！）**：
   - `director_plan.original_video_prompt_cn`：用一段自然连贯、画面感极强、可直接用于生成同款视频的完整中文提示词，从开场第一秒顺畅描述到最后一秒（写清环境、光影、人物外貌穿搭与坐姿/站位、机位视角、手中物品、动作过程与结局画面，**此时不要把用户的商品塞进去，保持 100% 原视频原貌！**）；
   - `director_plan.original_video_prompt_en`：与上面完全对应的照片级写实英文完整提示词（包含 `photorealistic live-action cinema footage, natural skin texture`）；
   - `director_plan.current_master_prompt_cn`：初始值与 `original_video_prompt_cn` 完全一致；
   - `director_plan.current_master_prompt_en`：初始值与 `original_video_prompt_en` 完全一致；
   - `director_plan.has_user_customized`：固定填 `false`。
3. **底层静默执行段落拆分（仅供后续点击生成按钮时机器自动调用，不在主界面打扰用户）**：
   - 在 `storyboard`（2~4 个自然连续片段）、`chatgpt_images_prompts`（索引 0 为主海报，索引 1..N 一一对应各段首帧）、`kling_prompts`（一一对应各段 5s 动作）中，同样保持忠实于原片构图与动作顺序。

用户已上传待替换的目标商品信息（仅供你在 `replaceability` 字段做简要评估参考，**切勿混入 `original_video_prompt_cn/en` 中**！）：
{dna_json}

用户附加备注：
{user_instruction or "无"}

原视频基础信息：
{meta_json}

请严格输出纯 JSON（不含 markdown 代码块标记以外的文字），字段结构必须与下方完全一致：
{{
  "is_ai_generated": true,
  "ai_confidence": 90,
  "ai_detection_reason": "具体判断依据",
  "director_plan": {{
    "original_plot_summary": "一句话概括原视频完整画面内容",
    "original_video_prompt_cn": "100% 忠实还原原视频从 0.0 秒第一帧到结尾的完整连贯中文视频提示词（不写分镜编号，不塞用户商品，完整写清第一帧人物所在位置如坐在飞机客舱内、服饰、动作、机位、抛投物与后续画面变化）",
    "original_video_prompt_en": "100% faithful continuous English prompt describing the exact original video from 0.0s opening frame to ending frame, photorealistic live-action style",
    "current_master_prompt_cn": "与 original_video_prompt_cn 完全相同",
    "current_master_prompt_en": "与 original_video_prompt_en 完全相同",
    "has_user_customized": false,
    "keyframe_previews": [],
    "ai_character_profile_cn": "原片人物特征简述（若无人写'无人物'）",
    "ai_character_profile_en": "Photorealistic real human description matching the scene (empty if no person)",
    "product_placement_plan": "等待用户输入修改意见后按需精准替换",
    "open_questions_for_user": [],
    "revision_status": "draft",
    "revision_history": []
  }},
  "replaceability": {{
    "score": 90,
    "original_featured_item": "原视频中的核心物品",
    "replacement_strategy": "保持原视频全部构图与情节框架不变，按用户指令将原片物品替换为目标商品",
    "replacement_difficulty": "低",
    "recommended_workflow": "确认提示词后一键生成"
  }},
  "structure": {{
    "hook_3s": "开场前3秒真实画面钩子",
    "pacing_curve": "全片画面推进节奏",
    "conversion_cta": "结尾视觉落点",
    "viral_reasons": ["爆款原因1", "爆款原因2"]
  }},
  "storyboard": [
    {{
      "shot_no": 1,
      "time_range": "00:00-00:04",
      "shot_size": "中近景",
      "camera_movement": "原片真实运镜",
      "original_visual": "原视频该时间段真实画面（如：人物坐在飞机舷窗旁...）",
      "adapted_visual_for_product": "初始与 original_visual 保持一致，待用户提出修改意见后再做精准局部替换",
      "audio_sfx": "原片音效/环境音",
      "production_mode": "ai",
      "real_shoot_guide": "实拍参考说明",
      "spoken_line": "",
      "replication_action": "keep_scene",
      "director_advice": "",
      "has_person": true
    }}
  ],
  "shooting_requirements": {{
    "lighting": "原片光线质感",
    "camera_setup": "原片机位视角",
    "props_and_scene": "原片场景与道具",
    "editing_rhythm": "原片剪辑与转场",
    "bgm_style": "原片配乐与音效风格"
  }},
  "copywriting": {{
    "original_transcript": "原视频语音/字幕（若无语音写'纯画面+音效无口播'）",
    "chinese_translation": "中文翻译",
    "adapted_script_cn": "适配目标商品的简短中文口播脚本",
    "adapted_script_en": "Short English script adapted for the product",
    "caption_and_hashtags": "推荐发布标题与标签"
  }},
  "chatgpt_images_prompts": [
    {{
      "scene_title": "主视觉封面图",
      "usage_note": "自动融合上传的商品图",
      "aspect_ratio": "9:16",
      "prompt_en": "Keep the exact product from the uploaded reference image...",
      "prompt_cn": "保持上传商品图外观一致..."
    }},
    {{
      "scene_title": "画面段落 1 首帧图",
      "usage_note": "对应开场第一帧画面",
      "aspect_ratio": "9:16",
      "prompt_en": "Photorealistic vertical 9:16 opening frame...",
      "prompt_cn": "写实竖屏 9:16 开场首帧画面..."
    }}
  ],
  "kling_prompts": [
    {{
      "shot_no": 1,
      "scene_title": "画面段落 1 动态视频",
      "mode": "图生视频 (I2V)",
      "recommended_params": "时长: 5s | 画质: 高品质",
      "prompt_cn": "完整中文动作与运镜提示词",
      "prompt_en": "Complete English motion & camera prompt for Kling AI",
      "negative_prompt": "变形, 模糊, 卡通, 动漫, 穿模, 多余手指, 闪烁, 水印, 杂乱文字"
    }}
  ]
}}"""


def build_director_revision_prompt(
    *,
    product_dna: ProductDNA,
    current_analysis: dict[str, Any],
    user_feedback: str,
    revision_history: list[dict[str, Any]],
    director_memory_block: str = "",
) -> str:
    dna_json = json.dumps(product_dna.model_dump(), ensure_ascii=False, indent=2)
    curr_json = json.dumps(current_analysis, ensure_ascii=False, indent=2)
    hist_json = json.dumps(revision_history[-8:], ensure_ascii=False, indent=2)
    memory_section = f"\n\n{director_memory_block}\n" if director_memory_block.strip() else ""

    return f"""你是用户的专属**视频提示词精准改写助手**。
系统已经把原爆款视频还原成了 `director_plan.original_video_prompt_cn`（以及上一轮改写后的 `director_plan.current_master_prompt_cn`）。现在用户给出了他的修改意见，请你**严格在上一版提示词的基础上做「手术刀式局部替换」**！{memory_section}

【绝对不可违背的 5 条铁律】
1. **没提的地方 100% 原封不动！（最高优先级！）**
   - 保持原视频完整的画面框架、人物坐姿/站位、镜头顺序、机位视角与动作逻辑不变，**只替换用户明确提到的元素**！
   - 反面教材警告：如果原片第一帧人物是“坐在飞机客舱里”，用户说“把飞机换成豪华私人飞机、人物换成欧美漂亮贵妇、往火山口扔缩小版沙发……”，那么第一帧**必须依然是这位欧美漂亮贵妇坐在豪华私人飞机客舱里**，绝对不准擅自把她改到地面或火山边站着！
   - 如果这是用户的第 2 轮、第 3 轮修改，必须在上一轮 `current_master_prompt_cn` 已改好的基础上继续微调用户新指出的点，不要把上一轮改好的内容丢掉！
2. **绝不跟用户啰嗦“第几个分镜”！**
   - `director_plan.current_master_prompt_cn` 和 `director_plan.current_master_prompt_en` 必须写成**一整段自然连贯、画面细节饱满的完整视频提示词**（按画面发生先后一气呵成，**严禁在里面写“分镜1 / 分镜2 / 第一镜”等拆分标题**）！
   - `director_reply` 只用 1~2 句干净利落的话回复用户（例如：“已按你的意见将飞机替换为带茶几的豪华私人飞机客舱客厅、人物替换为欧美漂亮贵妇，并将抛下与弹回的物品替换为你上传的【{product_dna.product_name}】，未提及的画面细节全部保持原视频不变。请查看上方新提示词，还有想调的可继续告诉我，满意点「确认没问题，开始生成」即可！”）——**严禁在 `director_reply` 里提“分镜1、分镜2、第几镜”**！
   - 将 `director_plan.has_user_customized` 设为 `true`，且保留原有的 `original_video_prompt_cn`、`original_video_prompt_en` 和 `keyframe_previews` 不变！
3. **精准融入用户上传的商品特征**：
   - 凡是出现用户商品的地方，具体写出【{product_dna.product_name}】（外观特征：{product_dna.physical_form}），严禁写 `[你的产品]` 等占位符；
   - 如果用户指定某处是“缩小版/迷你版商品”，英文提示词写明 `a miniature palm-sized version of the exact product from the uploaded reference image ({product_dna.product_name}, {product_dna.physical_form})`；正常尺寸写明 `Keep the exact full-size product from the uploaded reference image ({product_dna.product_name}, {product_dna.physical_form}, 100% unchanged)`。
4. **静默同步底层执行数组（供用户点确认后一键生图/生可灵视频自动读取）**：
   - 将改写后的连贯提示词同步拆分更新到底层 JSON 的 `storyboard`、`chatgpt_images_prompts`（索引 0 为海报，索引 1..N 对应 `storyboard` 1..N；有用户商品出现的段落标 `replication_action: "insert_product"` 并在 `prompt_en` 开头带 `Keep the exact product from the uploaded reference image...`，没有商品出现的纯环境/铺垫段标 `replication_action: "keep_scene"`；有人物的段标 `has_person: true` 并在 `director_plan.ai_character_profile_cn/en` 及各段 `prompt_en` 中锁定同一套写实真人外貌与穿搭！）和 `kling_prompts`！
5. **自动沉淀长期记忆（`learned_memories`）**：
   - 从用户本次意见中提炼 0~2 条可复用的创作偏好规则（`character` / `scene_style` / `product_replacement` / `pacing_framing` / `taboo`）。

用户上传的目标商品基因卡：
{dna_json}

历次修改对话记录：
{hist_json}

当前完整数据 JSON（含原视频基准提示词与上一轮提示词）：
{curr_json}

用户的最新修改意见（只改这里提到的内容，没提的一字不改！）：
{user_feedback}

请严格输出纯 JSON（不要附加任何说明文字），结构如下：
{{
  "director_reply": "简洁自然的确认回复（严禁提'分镜几'）",
  "changed_shots": [1],
  "learned_memories": [
    {{
      "category": "product_replacement",
      "product_scope": "global",
      "rule_summary": "一句可复用的创作偏好规则",
      "example_snippet": "本次创意简述"
    }}
  ],
  "analysis": {{
    "...完整更新后的 VideoDeepAnalysis 对象（含更新后的 director_plan.current_master_prompt_cn/en 且 has_user_customized=true，以及静默同步好的 storyboard / chatgpt_images_prompts / kling_prompts）..."
  }}
}}"""
