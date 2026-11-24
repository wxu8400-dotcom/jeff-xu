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
1. **逐帧盯紧第 1 帧（0.1 秒开场）到最后 1 帧（结尾）的每一个动作与过渡，严禁跳步省略！**：
   - 仔细看清开场第一帧：人物是谁、**坐在哪里还是站在哪里**（例如坐在开着舱门的直升机里、坐在车里、站在街上）、窗外或背景是什么、手里拿着什么物品、做了什么动作（如往窗外/火山口倾倒或扔下某物）；
   - **严禁省略中间的关键过渡画面！** 如果原视频有“物品往下掉 → 触发喷发/爆炸 → 变身后的物品（如炸鸡）从火山口向上喷射飞向空中并飞回机舱 → 落入机舱/人物开心享用”的完整过程，**每一个起承转合和飞行/变化过渡都必须原原本本写出来**，绝对不能从“火山冒烟”直接跳到“最后在机舱吃炸鸡”！
   - **严禁凭空脑补原视频没有的东西**，也严禁漏掉任何 1 秒的视觉爆点过渡！
2. **输出电影级、可直接丢进可灵/即梦/Sora 1:1 复刻的《原视频完整还原提示词》（必须写足 700~1200 字，严禁三句话敷衍！）**：
   - `director_plan.original_video_prompt_cn` 必须按以下清晰排版结构完整输出（可直接复制，不要写“分镜1/2”这种说教，而是按真实时间轴分段写透）：
     - **【画面质感与风格】**：9:16 竖屏、真实手机/电影广角摄影质感、近距离拍摄、轻微自然手持晃动/运镜风格、光线方向与真实皮肤纹理；
     - **【统一人物与核心环境】**：精确写出原片人物的肤色、年龄感、发型发色、五官表情、服装领口/细节/配饰，以及核心环境内部材质（如直升机灰色菱形绗缝软包内壁、深灰座椅、金属地板、敞开侧舱门、窗外黄绿色山地与云层）；
     - **【按时间轴完整画面与动作流程】**：按视频实际秒数（如 `【0–2秒】`、`【2–6秒】`、`【6–8秒】`、`【8–10秒】`），每一段写足 3~5 句高密度视觉细节（机位视角、主体位置、前景/背景层次、双手抓取与抛投动作、远小近大透视变化、熔岩喷发瞬间、物体从火山口向上飞射扑向镜头形成前景遮挡转场、回到机舱后的最终落点与人物表情动作！）；
     - **【摄影、光影与声音】**：光线冷暖对比、运镜跟随、环境音效依次变化（旋翼/环境声、坠落风声、喷发轰鸣、落地/咬合声），画面不生成文字/水印；
     - **【统一排除要求】**：避免人物换脸、发型服装改变、多余手指、物体变形/融化/悬停/瞬移、穿模、画面文字水印；
   - `director_plan.original_video_prompt_en`：与上面中文版同样丰富的电影级英文完整提示词；
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
    # Build a clean, compact context WITHOUT any base64 keyframe_previews!
    curr_plan = dict(current_analysis.get("director_plan") or {})
    orig_cn = str(
        curr_plan.get("original_video_prompt_cn")
        or curr_plan.get("original_plot_summary")
        or ""
    )
    prev_cn = str(curr_plan.get("current_master_prompt_cn") or orig_cn)
    prev_char_cn = str(curr_plan.get("ai_character_profile_cn") or "")
    prev_char_en = str(curr_plan.get("ai_character_profile_en") or "")

    compact_ctx = {
        "original_video_prompt_cn": orig_cn,
        "previous_master_prompt_cn": prev_cn,
        "previous_ai_character_cn": prev_char_cn,
        "previous_ai_character_en": prev_char_en,
        "storyboard_count": max(2, len(current_analysis.get("storyboard") or [])),
    }
    dna_json = json.dumps(
        {
            "product_name": product_dna.product_name,
            "category": product_dna.category,
            "physical_form": product_dna.physical_form,
            "core_selling_points": product_dna.core_selling_points[:3],
        },
        ensure_ascii=False,
        indent=2,
    )
    ctx_json = json.dumps(compact_ctx, ensure_ascii=False, indent=2)
    hist_json = json.dumps(revision_history[-6:], ensure_ascii=False, indent=2)
    memory_section = f"\n\n{director_memory_block}\n" if director_memory_block.strip() else ""

    return f"""你是用户的专属**视频提示词精准改写助手**。
用户刚刚提交了他的最新修改内容（用户可能是直接把原视频提示词复制下来做了局部增删改写，也可能是写了一段修改要求）。请你**100% 严格落实用户的最新修改内容**，生成干净完整的确认版中英文提示词，并静默同步底层的生图与可灵视频指令！{memory_section}

【绝对不可违背的 5 条铁律】
1. **100% 忠实落实用户提交的每一个细节，未提改动处严格保留原视频框架，并输出 800~1400 字电影级可直接复刻的完整总提示词！**
   - 如果用户已经把原视频提示词复制下来做了局部替换与增补（例如把直升机改成豪华宽体私人客机、把人物改成穿黑色连衣裙的苗条欧美贵妇、把生鸡肉改成双手托着迷你版上传沙发、火山喷发弹射出正常尺寸沙发飞回豪华客机会客区落地，贵妇走过去坐下开怀大笑），你必须**一字不漏地完整采纳用户的全部改动与新增情节**，自动修正错别字（如“猫着烟火”→“冒着烟火”），绝不偷懒缩写成三两句话！
   - **同时你已经看到了随附的用户商品实拍图**：请在【产品一致性】中精确描写商品图的真实细节（颜色、款式比例、扶手/轮廓造型、表面纹理材质、附带配件如抱枕数量与花纹），并明确声明**只参考商品本体，不带入原商品照里的展厅、窗帘、树枝或杂物背景**！
2. **输出可直接复制到可灵 / 或直接在工坊一键生成的专业排版总提示词（严禁写“分镜1/2/3”说教，按以下专业结构排版！）**：
   - `current_master_prompt_cn`（必须写足 **800~1400 字**！）严格包含以下模块：
     - 开头总述（如“制作一条 15 秒、9:16 竖屏的超现实高端产品广告，真实电影摄影质感……”）
     - **【产品一致性】**（精确锁死上传商品的外观、比例、材质、纹理与配件；若有迷你版→正常尺寸变化，明确写清两者是完全同一款产品只有整体尺寸变化，且不带入参考图背景杂物）
     - **【人物与场景】**（全片统一人物的气质、年龄、发型、服装穿搭 + 豪华场景内饰材质、色彩、光影、敞开舱门与外部环境）
     - **【时间轴完整动作与运镜脚本】**（按自然时间段如 `【0–3秒：...】`、`【3–6秒：...】`、`【6–9秒：...】`、`【9–12秒：...】`、`【12–15秒：...】`，每段写足 3~5 句电影级物理与视觉细节：机位角度、主体动作、远小近大透视、火光烟雾遮挡完成尺寸变化、前景遮挡自然转场、落地重量感与接触阴影、人物坐下时坐垫的轻微自然压缩与表情反应！）
     - **【摄影与声音】**（冷暖光影对比、运镜节奏、依次出现的环境声/风声/轰鸣/喷发冲击声/落地闷响/自然笑声，画面不生成文字或水印）
     - **【统一排除要求】**（避免商品变形、颜色改变、纹理消失、配件数量变化、多余手指、融化解体、背景杂物带入、文字水印）
   - `current_master_prompt_en`：与上面中文版完全对应的电影级英文完整总提示词！
   - `director_reply`：只用 1~2 句简洁自然的话确认已按用户要求重写完毕并锁死了商品图细节，**严禁在 `director_reply` 里提“分镜几”**！
3. **精准融入用户上传的商品特征**：
   - 凡出现用户商品处，写清【{product_dna.product_name}】（{product_dna.physical_form}），严禁占位符；
   - 迷你版英文写明 `a miniature palm-sized version of the exact product from the uploaded reference image ({product_dna.product_name}, {product_dna.physical_form})`；正常尺寸写明 `Keep the exact full-size product from the uploaded reference image ({product_dna.product_name}, {product_dna.physical_form}, 100% unchanged, ignoring any background clutter from the reference photo)`。
4. **静默同步底层执行数组（供用户点确认后一键生图/生可灵视频使用）**：
   - 将新版总提示词的各时间段同步写入 `storyboard`（3~5 段，每段 `shot_no` 为 1..N，标好 `has_person` 和 `replication_action`：含用户商品标 `"insert_product"`，纯火山/无商品环境段标 `"keep_scene"`）；
   - `chatgpt_images_prompts`：索引 0 为主视觉封面，索引 1..N 严格一一对应 `storyboard` 1..N，每条英文 `prompt_en` 都要保留对应的电影级细节与统一 `ai_character_profile_en`；
   - `kling_prompts`：严格一一对应 `storyboard` 1..N，每段 5 秒平滑衔接。
5. **自动沉淀 0~2 条长期记忆（`learned_memories`）**。

用户上传的目标商品：
{dna_json}

原视频与上一版提示词基准：
{ctx_json}

最近修改记录：
{hist_json}

用户本次提交的最新修改内容（最高优先级，必须 100% 完整落实！）：
{user_feedback}

请严格输出纯 JSON（不要附加任何多余文字），结构如下：
{{
  "director_reply": "1~2句简洁确认回复（严禁出现'分镜'二字）",
  "changed_shots": [1, 2, 3],
  "current_master_prompt_cn": "按用户最新意见重新编写并润色好的完整连贯中文视频提示词（800~1400字，含【产品一致性】【人物与场景】【时间轴完整动作与运镜脚本】【摄影与声音】）",
  "current_master_prompt_en": "Complete cohesive English photorealistic video prompt covering opening frame to ending frame",
  "negative_constraints": "独立的一段【统一排除要求（负向约束）】，例如：避免产品变形、颜色变化、扶手/轮廓/纹理消失、配件数量变化、多余手指、人物换脸、背景杂物带入、文字或水印",
  "ai_character_profile_cn": "全片统一的写实 AI 人物中文设定",
  "ai_character_profile_en": "Consistent photorealistic real human English character profile",
  "adapted_script_cn": "简短配套中文口播（若原片纯画面无口播可简短写一句高冲击文案）",
  "adapted_script_en": "Short matching English voiceover line",
  "learned_memories": [
    {{
      "category": "product_replacement",
      "product_scope": "global",
      "rule_summary": "一句可复用的创作偏好规则",
      "example_snippet": "本次创意简述"
    }}
  ],
  "storyboard": [
    {{
      "shot_no": 1,
      "time_range": "00:00-00:05",
      "shot_size": "中景",
      "camera_movement": "跟随微推",
      "original_visual": "对应原片画面",
      "adapted_visual_for_product": "按用户意见替换后的该段具体画面",
      "audio_sfx": "环境音与音效",
      "production_mode": "ai",
      "real_shoot_guide": "实拍参考",
      "spoken_line": "",
      "replication_action": "insert_product",
      "director_advice": "",
      "has_person": true
    }}
  ],
  "chatgpt_images_prompts": [
    {{
      "scene_title": "主视觉封面图",
      "usage_note": "自动融合上传的商品图",
      "aspect_ratio": "9:16",
      "prompt_en": "Keep the exact product from the uploaded reference image...",
      "prompt_cn": "保持上传商品图外观一致..."
    }},
    {{
      "scene_title": "画面 1 首帧图",
      "usage_note": "对应开场画面",
      "aspect_ratio": "9:16",
      "prompt_en": "Photorealistic vertical 9:16 frame...",
      "prompt_cn": "写实竖屏 9:16 画面..."
    }}
  ],
  "kling_prompts": [
    {{
      "shot_no": 1,
      "scene_title": "画面 1 动态视频",
      "mode": "图生视频 (I2V)",
      "recommended_params": "时长: 5s | 画质: 高品质",
      "prompt_cn": "完整中文动作与运镜提示词",
      "prompt_en": "Complete English motion & camera prompt for Kling AI",
      "negative_prompt": "变形, 模糊, 卡通, 动漫, 穿模, 多余手指, 闪烁, 水印, 杂乱文字"
    }}
  ]
}}"""


def build_image_refinement_prompt(
    *,
    product_name: str,
    product_form: str,
    base_prompt: str,
    user_feedback: str,
    character_profile_en: str = "",
) -> str:
    return f"""你是专业商业广告生图提示词精修师。
用户刚刚预览了 AI 生成的这张画面图，并对局部不满意，提出了具体的中文修正意见。
请你在**严格保留原画面主体构图、核心场景与上传商品外观 100% 一致**的前提下，只精准落实用户的修正意见（例如调整人物长相/年龄/发型/服装、调亮光线、放大商品、去掉杂物等），输出精修后的中英文生图提示词！

目标商品：{product_name}（{product_form}）
统一人物参考设定（若用户没要求改人物则保持，若用户要求改人物则按用户最新要求替换）：{character_profile_en or "无"}

原图生图提示词：
{base_prompt}

用户对这张图的中文修正意见（最高优先级，必须准确落实！）：
{user_feedback}

请严格输出纯 JSON：
{{
  "refined_prompt_en": "Complete, photorealistic vertical 9:16 English image generation prompt applying the user's exact visual fix while preserving the exact uploaded product (NO cartoon, NO anime, NO text, NO watermark)",
  "refined_prompt_cn": "精修后的中文画面提示词对照"
}}"""


def build_prompt_import_prompt(
    *,
    product_name: str,
    product_text: str,
    pasted_prompt_text: str,
    screenshot_count: int,
    product_photo_count: int,
) -> str:
    return f"""你是顶级 AI 视频制作执行导演（精通 **GPT Image / Seedream 多图融合生图** 与 **可灵 Kling I2V 图生视频**）。
用户已经在外部工具（如 Codex）完成了爆款视频拆解并定稿了完整提示词，现在把**提示词截图（共 {screenshot_count} 张，排在附带图片的最前面）**和/或**提示词文字**，以及**目标商品多角度实拍图（共 {product_photo_count} 张，排在后面）**一起上传给你，希望你**100% 忠实照着截图里的提示词内容**直接拆成可执行的生图指令与可灵视频指令，进入后续制作流程！

【最高铁律 — 100% 忠实还原用户提示词截图，绝不擅自删减或魔改剧情！】
1. **逐字看清每一张提示词截图**：
   - 将截图中的所有文字（包括总述、【产品一致性】、【人物与场景】、所有时间段如 `0–3秒` / `3–6秒` / `6–9秒` / `9–12秒` / `12–15秒` 或 `镜头一/二/三/四`、【摄影与声音】、【统一排除要求/负向约束】）**一字不漏地完整整理**到 `director_plan.current_master_prompt_cn`（以及 `original_video_prompt_cn`）中，并将排除约束单独放入 `director_plan.negative_constraints`！
2. **严格按截图里的每一段时间/镜头，一一对应生成可执行段落（`storyboard`、`chatgpt_images_prompts`、`kling_prompts`）**：
   - 如果截图里写了 5 个时间段（例如 `0–3秒`、`3–6秒`、`6–9秒`、`9–12秒`、`12–15秒`），`storyboard` 就必须严格输出 **5 个对应段落**（绝不能私自合并成 3 段丢掉“喷发弹射”或“飞回机舱”！）；如果截图写了 4 个镜头，就严格输出 4 个对应段落！
   - 仔细观察后面附带的用户商品实拍图，把商品的真实颜色、造型比例、材质纹理、抱枕/配件细节完整融入英文生图提示词；
   - **重要**：如果某一段是纯环境/纯火山过渡、截图明确没有出现商品，标 `replication_action: "keep_scene"`；凡是出现迷你版或正常尺寸商品的段落，标 `replication_action: "insert_product"`，并在 `chatgpt_images_prompts` 对应 `prompt_en` 中明确写明：
     - 迷你版：`a miniature palm-sized version of the exact product from the uploaded reference images ({product_name}, keeping its exact color, shape, material, and cushions, ignoring any background clutter from the product photos)`
     - 正常尺寸：`Keep the exact full-size product from the uploaded reference images ({product_name}, 100% faithful to its exact color, shape, texture, and accessories, ignoring any background clutter from the product photos)`
   - **人物统一**：从截图的【人物与场景】提取全片统一的人物外貌与穿搭写入 `director_plan.ai_character_profile_cn` / `ai_character_profile_en`，在每一个有人物出现的段落标 `has_person: true` 并在 `prompt_en` 中严格复用同一人物设定！
3. **`chatgpt_images_prompts` 索引严格对齐**：
   - 索引 0：主视觉海报（封面图）；
   - 索引 1..N：**严格一一对应 `storyboard` 第 1..N 段的首帧参考图**（写实电影摄影质感、9:16 竖屏、无文字无水印，100% 落实截图里该段的机位、景别、前景/背景、人物动作与商品状态！）。
4. **`kling_prompts` 严格对齐第 1..N 段**：
   - 逐段还原截图里的物理运动、抛投轨迹、远小近大透视、火山喷发、前景遮挡转场、落地阴影与人物坐下压缩/表情变化；
   - `negative_prompt` 直接带上截图里的全部排除要求！

用户填写的商品名称：{product_name or "请从提示词截图与商品图中自动识别"}
用户补充商品说明：{product_text or "无（请直接参考附带的提示词截图与商品实拍图）"}
用户直接粘贴的提示词文本（若有，与截图合并整理）：
{pasted_prompt_text or "（无纯文本，请完整识别上方附带的提示词截图）"}

请严格输出纯 JSON（不含 markdown 代码块以外的说明文字），结构与下方完全一致：
{{
  "is_ai_generated": true,
  "ai_confidence": 98,
  "ai_detection_reason": "用户导入的定稿提示词直出制作任务",
  "director_plan": {{
    "original_plot_summary": "一句话概括用户提示词的完整创意流程",
    "original_video_prompt_cn": "100% 忠实提取并整理自用户截图/文本的完整中文总提示词",
    "original_video_prompt_en": "Complete faithful English translation of the user's imported prompt",
    "current_master_prompt_cn": "与 original_video_prompt_cn 完全一致",
    "current_master_prompt_en": "与 original_video_prompt_en 完全一致",
    "negative_constraints": "从截图中完整提取的【统一排除要求】",
    "has_user_customized": true,
    "keyframe_previews": [],
    "ai_character_profile_cn": "从截图提取的全片统一写实人物中文设定",
    "ai_character_profile_en": "Consistent photorealistic real human English profile from screenshot",
    "product_placement_plan": "已严格按导入提示词的每一段时间轴完成生图与可灵视频指令拆解",
    "open_questions_for_user": [],
    "revision_status": "locked",
    "revision_history": []
  }},
  "replaceability": {{
    "score": 98,
    "original_featured_item": "{product_name or '目标商品'}",
    "replacement_strategy": "严格按用户上传的定稿提示词执行生图与可灵视频制作",
    "replacement_difficulty": "低",
    "recommended_workflow": "一键生图确认（支持单图中文修正）→ 可灵生成动态视频 → 合成 9:16 成片 MP4"
  }},
  "structure": {{
    "hook_3s": "开场前 3 秒画面钩子",
    "pacing_curve": "全片时间轴推进节奏",
    "conversion_cta": "结尾产品展示与情绪落点",
    "viral_reasons": ["反常识超现实视觉奇观", "完整保留用户定稿脚本细节"]
  }},
  "storyboard": [
    {{
      "shot_no": 1,
      "time_range": "00:00-00:03",
      "shot_size": "广角中近景",
      "camera_movement": "跟随运镜",
      "original_visual": "对应截图该时间段的完整中文画面描述",
      "adapted_visual_for_product": "对应截图该时间段的完整中文画面描述",
      "audio_sfx": "对应截图该段的声音/音效描述",
      "production_mode": "ai",
      "real_shoot_guide": "",
      "spoken_line": "",
      "replication_action": "insert_product",
      "director_advice": "",
      "has_person": true
    }}
  ],
  "shooting_requirements": {{
    "lighting": "从截图提取的光线要求",
    "camera_setup": "从截图提取的机位与摄影风格",
    "props_and_scene": "从截图提取的场景与道具设定",
    "editing_rhythm": "从截图提取的转场与节奏",
    "bgm_style": "从截图提取的声音与音效设计"
  }},
  "copywriting": {{
    "original_transcript": "无口播（纯视觉+环境音效）",
    "chinese_translation": "",
    "adapted_script_cn": "",
    "adapted_script_en": "",
    "caption_and_hashtags": ""
  }},
  "chatgpt_images_prompts": [
    {{
      "scene_title": "主视觉海报（封面图）",
      "usage_note": "自动融合上传的多角度商品图",
      "aspect_ratio": "9:16",
      "prompt_en": "Keep the exact product from the uploaded reference images...",
      "prompt_cn": "严格保持上传商品外观一致的主视觉封面..."
    }},
    {{
      "scene_title": "画面 1 首帧图（0-3秒）",
      "usage_note": "严格对应截图第一段首帧画面",
      "aspect_ratio": "9:16",
      "prompt_en": "Photorealistic vertical 9:16 cinema frame...",
      "prompt_cn": "对应截图第一段首帧中文画面..."
    }}
  ],
  "kling_prompts": [
    {{
      "shot_no": 1,
      "scene_title": "画面 1 动态视频（0-3秒）",
      "mode": "图生视频 (I2V)",
      "recommended_params": "时长: 5s | 画质: 高品质",
      "prompt_cn": "严格还原截图第一段全部动作与运镜的中文可灵提示词",
      "prompt_en": "Detailed English Kling I2V motion & camera prompt matching segment 1",
      "negative_prompt": "从截图提取的完整负向排除约束"
    }}
  ]
}}"""
