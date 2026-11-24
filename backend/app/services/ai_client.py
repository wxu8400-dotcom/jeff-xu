from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from ..config import Settings, get_settings
from ..schemas import (
    ChatGPTImagePrompt,
    CopywritingAnalysis,
    KlingVideoPrompt,
    PreliminaryScreeningBatch,
    PreliminaryScreeningItem,
    ProductDNA,
    ReplaceabilityAnalysis,
    SearchQueries,
    ShootingRequirements,
    StoryboardShot,
    VideoDeepAnalysis,
    VideoStructureAnalysis,
)
from .video_processor import extract_keyframes_from_bytes

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: "TokenUsage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


def estimate_cost_cny(
    input_tokens: int,
    output_tokens: int,
    model_name: str = "gemini-2.5-flash",
) -> float:
    """Rough cost estimation in CNY (1 USD ≈ 7.25 CNY)."""
    lower = model_name.lower()
    if "lite" in lower or "mini" in lower:
        in_usd_per_m, out_usd_per_m = 0.10, 0.40
    elif "flash" in lower:
        in_usd_per_m, out_usd_per_m = 0.30, 2.50
    else:
        in_usd_per_m, out_usd_per_m = 2.50, 10.00
    usd = (input_tokens / 1_000_000) * in_usd_per_m + (
        output_tokens / 1_000_000
    ) * out_usd_per_m
    return round(usd * 7.25, 4)


def extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"无法从模型返回中解析合法 JSON：{raw_text[:240]}")


class UnifiedAIClient:
    """Supports Gemini native video/image (official or custom relay URL),
    OpenAI-compatible fallback, and deterministic Mock mode for testing."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def is_configured(self) -> bool:
        if self.settings.enable_mock_mode:
            return True
        if self.settings.ai_provider == "gemini":
            return bool(self.settings.gemini_api_key.strip())
        return bool(self.settings.openai_api_key.strip())

    def _build_gemini_client(self):
        from google import genai
        from google.genai import types

        http_options = None
        if self.settings.gemini_base_url.strip():
            http_options = types.HttpOptions(
                base_url=self.settings.gemini_base_url.strip().rstrip("/")
            )
        return genai.Client(
            api_key=self.settings.gemini_api_key.strip(),
            http_options=http_options,
        )

    async def generate_structured(
        self,
        *,
        prompt: str,
        schema_cls: type[T],
        tier: str = "fast",
        images: list[tuple[bytes, str]] | None = None,
        video_bytes: bytes | None = None,
        video_mime: str = "video/mp4",
        mock_context: dict[str, Any] | None = None,
    ) -> tuple[T, TokenUsage]:
        if self.settings.enable_mock_mode:
            return self._mock_response(schema_cls, mock_context or {})

        if not self.is_configured():
            raise RuntimeError(
                "尚未配置 AI API Key（请配置 GEMINI_API_KEY 或切换 OPENAI_API_KEY）"
            )

        last_err: Exception | None = None
        for attempt in range(2):
            try:
                if self.settings.ai_provider == "gemini":
                    raw_text, usage = await self._call_gemini(
                        prompt=prompt,
                        tier=tier,
                        images=images or [],
                        video_bytes=video_bytes,
                        video_mime=video_mime,
                    )
                else:
                    raw_text, usage = await self._call_openai_compatible(
                        prompt=prompt,
                        tier=tier,
                        images=images or [],
                        video_bytes=video_bytes,
                    )
                data = extract_json_object(raw_text)
                return schema_cls.model_validate(data), usage
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "AI structured call attempt %d failed (%s): %s",
                    attempt + 1,
                    schema_cls.__name__,
                    exc,
                )
                if attempt == 0:
                    prompt = (
                        prompt
                        + "\n\n【格式纠错提示】上次返回 JSON 解析失败，请务必只输出严格合法的纯 JSON 对象，不要包含注释或多余文字。"
                    )
                    await asyncio.sleep(1.0)
        assert last_err is not None
        raise last_err

    async def _call_gemini(
        self,
        *,
        prompt: str,
        tier: str,
        images: list[tuple[bytes, str]],
        video_bytes: bytes | None,
        video_mime: str,
    ) -> tuple[str, TokenUsage]:
        from google.genai import types

        model_name = (
            self.settings.gemini_fast_model
            if tier == "fast"
            else self.settings.gemini_deep_model
        )
        client = self._build_gemini_client()

        parts: list[Any] = [types.Part.from_text(text=prompt)]
        for img_bytes, mime in images:
            parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))

        if video_bytes:
            # Compressed 360p/1fps video is typically 1~3MB; inline Part.from_bytes works
            # reliably across both Google official API and Alipay/WeChat relay gateways.
            if len(video_bytes) <= 18 * 1024 * 1024:
                parts.append(
                    types.Part.from_bytes(data=video_bytes, mime_type=video_mime)
                )
            else:
                frames = extract_keyframes_from_bytes(video_bytes, max_frames=8)
                for frame_bytes in frames:
                    parts.append(
                        types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg")
                    )

        config = types.GenerateContentConfig(
            temperature=0.35 if tier == "fast" else 0.5,
            response_mime_type="application/json",
        )

        def _sync_call(target_model: str):
            return client.models.generate_content(
                model=target_model,
                contents=parts,
                config=config,
            )

        fallback_chain = (
            [model_name, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash"]
            if tier == "fast"
            else [model_name, "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview", "gemini-2.5-flash"]
        )
        seen_models: list[str] = []
        for m in fallback_chain:
            if m and m not in seen_models:
                seen_models.append(m)

        resp = None
        last_err: Exception | None = None
        for idx, candidate_model in enumerate(seen_models):
            for retry in range(2):
                try:
                    resp = await asyncio.to_thread(_sync_call, candidate_model)
                    break
                except Exception as exc:
                    err_str = str(exc).upper()
                    is_404 = "404" in err_str or "NOT_FOUND" in err_str
                    is_transient = (
                        "503" in err_str
                        or "UNAVAILABLE" in err_str
                        or "429" in err_str
                        or "RESOURCE_EXHAUSTED" in err_str
                        or "OVERLOADED" in err_str
                    )
                    last_err = exc
                    if is_404:
                        logger.warning(
                            "Gemini model %s unavailable (404), trying next fallback...",
                            candidate_model,
                        )
                        break
                    if is_transient:
                        if retry == 0:
                            logger.warning(
                                "Gemini model %s returned transient 503/429, retrying in 3s...",
                                candidate_model,
                            )
                            await asyncio.sleep(3.0)
                            continue
                        if idx < len(seen_models) - 1:
                            logger.warning(
                                "Gemini model %s still busy (503/429), switching to next fallback model...",
                                candidate_model,
                            )
                            break
                    raise
            if resp is not None:
                break
        if resp is None:
            assert last_err is not None
            raise last_err
        text = resp.text or ""
        usage_meta = getattr(resp, "usage_metadata", None)
        usage = TokenUsage(
            input_tokens=int(getattr(usage_meta, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage_meta, "candidates_token_count", 0) or 0),
        )
        return text, usage

    async def _call_openai_compatible(
        self,
        *,
        prompt: str,
        tier: str,
        images: list[tuple[bytes, str]],
        video_bytes: bytes | None,
    ) -> tuple[str, TokenUsage]:
        from openai import AsyncOpenAI

        model_name = (
            self.settings.openai_fast_model
            if tier == "fast"
            else self.settings.openai_deep_model
        )
        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key.strip(),
            base_url=self.settings.openai_base_url.strip(),
        )

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        all_images = list(images)
        if video_bytes:
            frames = extract_keyframes_from_bytes(video_bytes, max_frames=6)
            all_images.extend([(f, "image/jpeg") for f in frames])

        for img_bytes, mime in all_images:
            b64 = base64.b64encode(img_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "low"},
                }
            )

        resp = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": content}],
            temperature=0.35 if tier == "fast" else 0.5,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        usage_obj = resp.usage
        usage = TokenUsage(
            input_tokens=int(getattr(usage_obj, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage_obj, "completion_tokens", 0) or 0),
        )
        return text, usage

    def _mock_response(
        self, schema_cls: type[T], ctx: dict[str, Any]
    ) -> tuple[T, TokenUsage]:
        if schema_cls is ProductDNA:
            raw_name = (ctx.get("product_name_override") or "").strip()
            raw_text = (ctx.get("extracted_text") or "").strip()
            if not raw_name:
                if "风扇" in raw_text:
                    raw_name = "迷你高速手持冰敷风扇"
                elif "精华" in raw_text or "护肤" in raw_text:
                    raw_name = "玻色因修护抗老精华"
                elif "杯" in raw_text:
                    raw_name = "磁吸便携保温咖啡杯"
                else:
                    raw_name = "便携智能好物产品"
            dna = ProductDNA(
                product_name=raw_name,
                category="跨境热门消费好物",
                physical_form=f"精致便携单手可握外观，磨砂高级质感，细节辨识度高（{raw_name}）",
                core_selling_points=[
                    "3秒直观见效，画面对比冲击力强",
                    "高颜值便携设计，适配桌面与户外多场景",
                    "高频日常痛点解决，天然适合短视频种草转化",
                ],
                target_audience="18-38岁注重生活品质与颜值效率的欧美/东南亚年轻消费者",
                usage_scenarios=["通勤户外随身使用", "书桌/办公桌精致搭配", "居家开箱实测对比"],
                replaceable_visual_slots=[
                    "手持产品近景特写展示",
                    "桌面美学开箱与前后对比",
                    "AI创意微缩/悬浮产品大片",
                ],
                avoid_patterns=["纯人脸口播无实物道具", "大型汽车家具改装", "强明星IP剧情"],
                category_leak_keywords=[raw_name] if raw_name else [],
                search_queries=SearchQueries(
                    tiktok=["fooh cgi", "3d product animation", "ai commercial ad"],
                    instagram=["fooh", "3dproductanimation", "creativecommercial"],
                    youtube=["fooh cgi commercial", "3d product animation commercial", "ai commercial video shorts"],
                ),
            )
            return dna, TokenUsage(input_tokens=620, output_tokens=310)  # type: ignore[return-value]

        if schema_cls is PreliminaryScreeningBatch:
            candidates: list[dict[str, Any]] = ctx.get("candidates", [])
            items: list[PreliminaryScreeningItem] = []
            for cand in candidates:
                title_lower = (cand.get("title", "") + " " + cand.get("caption", "")).lower()
                if any(bad in title_lower for bad in ["street interview", "podcast", "drama", "prank", "口播", "街访"]):
                    score = 32
                    creativity = 25
                    item_name = "无明确实物（纯人物对话）"
                    reason = "纯人物对话/街访类内容，无清晰产品展示槽位，直接淘汰"
                    ok = False
                elif any(good in title_lower for good in ["ai", "cgi", "3d", "fooh", "unboxing", "aesthetic", "gadget", "review"]):
                    score = 92
                    creativity = 94
                    item_name = "跨品类爆款创意展示单品"
                    reason = "强视觉创意模板且主体产品镜头占比高，极易替换为目标产品复刻爆款元素"
                    ok = True
                else:
                    score = 78
                    creativity = 76
                    item_name = "日常跨品类实物道具"
                    reason = "具备清晰展示与对比镜头，可替换性良好"
                    ok = True
                items.append(
                    PreliminaryScreeningItem(
                        candidate_id=str(cand["candidate_id"]),
                        preliminary_score=score,
                        visual_creativity_score=creativity,
                        is_same_category=False,
                        original_featured_item=item_name,
                        reason=reason,
                        is_replaceable=ok,
                    )
                )
            return PreliminaryScreeningBatch(results=items), TokenUsage(
                input_tokens=1150, output_tokens=420
            )  # type: ignore[return-value]

        if schema_cls is VideoDeepAnalysis:
            dna: ProductDNA = ctx["product_dna"]
            video_meta: dict[str, Any] = ctx.get("video_meta", {})
            title_lower = str(video_meta.get("title", "")).lower()
            is_ai = any(k in title_lower for k in ["ai", "cgi", "3d", "kling", "sora"])
            pname = dna.product_name
            pform = dna.physical_form or pname

            analysis = VideoDeepAnalysis(
                is_ai_generated=is_ai,
                ai_confidence=91 if is_ai else 84,
                ai_detection_reason=(
                    "画面存在超现实流体光影与悬浮运镜，符合 AI 视频生成特征，非常适合直接用可灵 Kling 复刻"
                    if is_ai
                    else "自然手持微抖与真实环境光反射明显，判断为实拍爆款；同时已为你附带实拍与 AI 双套复刻提示词"
                ),
                replaceability=ReplaceabilityAnalysis(
                    score=93 if is_ai else 88,
                    original_featured_item=str(video_meta.get("original_featured_item") or "手持热门爆款单品"),
                    replacement_strategy=(
                        f"原视频核心逻辑是“前3秒极致视觉特写 + 中段痛点场景实测 + 结尾情绪价值收尾”。"
                        f"只需将原片中的主体完全替换为【{pname}】（{pform}），保留其快节奏推拉运镜与光影反差，"
                        f"既可直接按分镜实拍，也可用下方 ChatGPT Images 融合你的产品图生成首帧，再用可灵 Kling 生成无缝动态视频。"
                    ),
                    replacement_difficulty="低",
                    recommended_workflow=(
                        "推荐优先用 ChatGPT Images + 可灵 Kling 1:1 AI 复刻"
                        if is_ai
                        else "实拍 1 小时可出片，亦可用 ChatGPT Images + 可灵 Kling 低成本 AI 复刻"
                    ),
                ),
                structure=VideoStructureAnalysis(
                    hook_3s=f"0-3秒直接微距特写切入痛点，用强烈对比画面瞬间锁住注意力，立刻引出【{pname}】登场。",
                    pacing_curve="0-3s 强视觉钩子 -> 3-10s 核心卖点直观演示 -> 10-18s 真实场景对比反差 -> 18-24s 情绪收尾与下单引导",
                    conversion_cta="画面角落出现简洁行动提示，口播强调“用过就回不去”，引导点击主页链接/评论区关键词。",
                    viral_reasons=[
                        "前 1.5 秒无废话直给视觉冲击，完播率极高",
                        "产品展示槽位极其聚焦，观众一眼看懂核心功能",
                        "配乐卡点明快，天然激发点赞收藏与转发欲望",
                    ],
                ),
                storyboard=[
                    StoryboardShot(
                        shot_no=1,
                        time_range="00:00-00:03",
                        shot_size="极端特写",
                        camera_movement="快速前推并轻微上仰",
                        original_visual="原单品在强光下破雾而出，伴随清脆开启音效",
                        adapted_visual_for_product=f"【{pname}】置于冷暖撞色光影台面中央，镜头快速推进聚焦其磨砂机身质感与核心功能细节，瞬间吸睛",
                        audio_sfx="清脆“咔哒”启动声 + 低频重音卡点",
                    ),
                    StoryboardShot(
                        shot_no=2,
                        time_range="00:03-00:10",
                        shot_size="近景手持",
                        camera_movement="平稳跟随横移",
                        original_visual="单手握持演示核心功能，画面干净无杂物",
                        adapted_visual_for_product=f"一只干净自然的手稳稳握持【{pname}】在日常高频场景中启动演示，直观呈现「{dna.core_selling_points[0] if dna.core_selling_points else '核心卖点'}」",
                        audio_sfx="节奏感轻快英文/电子鼓点 BGM 切入",
                    ),
                    StoryboardShot(
                        shot_no=3,
                        time_range="00:10-00:18",
                        shot_size="中景分屏/对比",
                        camera_movement="固定机位微推",
                        original_visual="使用前烦躁痛点 vs 使用后轻松愉悦的强反差",
                        adapted_visual_for_product=f"对比展示没有【{pname}】时的困扰，切到使用【{pname}】后的清爽高效状态，突出便携与高颜值属性",
                        audio_sfx="转场“嗖”音效 + 人声高潮金句",
                    ),
                    StoryboardShot(
                        shot_no=4,
                        time_range="00:18-00:24",
                        shot_size="特写定格",
                        camera_movement="缓慢环绕 30 度",
                        original_visual="产品精致摆放，四周虚化光斑收尾",
                        adapted_visual_for_product=f"【{pname}】精致陈列在桌面美学场景中，柔光勾勒轮廓，背景呈现高级奶油虚化光斑，预留底部字幕与行动引导区",
                        audio_sfx="BGM 干净收尾 + 轻柔提示音",
                    ),
                ],
                shooting_requirements=ShootingRequirements(
                    lighting="主光采用 45° 柔光箱（5200K 自然白），侧后方加一盏冷蓝/暖金轮廓灯拉出产品边缘立体感。",
                    camera_setup="手机 4K 60fps 竖屏（9:16），特写使用 2x~3x 长焦镜头避免广角畸变，搭配小型桌面滑轨或稳定器。",
                    props_and_scene="极简浅灰/原木桌面背景，控制画面不超过 3 个颜色，保持产品为绝对视觉焦点。",
                    editing_rhythm="前 3 秒每 0.8~1.2 秒切一个景别，中段按鼓点精准剪辑，字幕使用高对比粗体居中偏下放置。",
                    bgm_style="轻快现代 Future Bass / Minimal Tech 鼓点（BPM 118-124），前 3 秒留音效空白后爆点进入。",
                ),
                copywriting=CopywritingAnalysis(
                    original_transcript="Wait until you see how effortlessly this solves my biggest daily annoyance...",
                    chinese_translation="等一下，你一定要看看这个小东西是怎么轻松解决我每天最大烦恼的……",
                    adapted_script_cn=f"别划走！每天最让人崩溃的小事，居然被这个【{pname}】3秒搞定了？颜值高到像桌面艺术品，关键是{dna.core_selling_points[0] if dna.core_selling_points else '体验直接拉满'}，出门随手揣包里毫无负担，用过一次真的回不去！",
                    adapted_script_en=f"Stop scrolling! I didn't think I needed this {pname} until it fixed my biggest daily annoyance in 3 seconds. Sleek, portable, and ridiculously satisfying to use—honestly my best find this month.",
                    caption_and_hashtags=f"这个【{pname}】真的相见恨晚🔥 #tiktokmademebuyit #amazonfinds #viralproducts #musthave #productreview #aestheticfinds #dailyessentials #giftideas",
                ),
                chatgpt_images_prompts=[
                    ChatGPTImagePrompt(
                        scene_title="爆款主视觉海报（9:16 封面图）",
                        usage_note="在 ChatGPT 中上传你的产品实拍图，然后直接复制下方英文提示词发送",
                        aspect_ratio="9:16",
                        prompt_en=(
                            f"Keep the exact product from the uploaded reference image ({pname}, preserving its exact shape, matte finish, color, proportions, and logo 100% unchanged). "
                            "Place it heroically at the center-lower third of a minimalist studio pedestal with subtle floating mist and dramatic rim lighting, warm sunlit highlights contrasting against a sleek dark slate background. "
                            "Shot on Hasselblad medium format camera, 85mm lens, shallow depth of field, ultra-crisp commercial advertising photography, clean negative space at the top third for bold poster headline typography, photorealistic, 8K, vertical 9:16."
                        ),
                        prompt_cn=(
                            f"严格保持上传参考图中【{pname}】的外观造型、材质纹理、颜色比例与Logo细节100%不变。将产品作为绝对主角摆放在极简高级摄影展台的中下方，周围点缀细腻薄雾与高级轮廓逆光，暖色高光与深灰质感背景形成强烈对比；哈苏中画幅85mm商业广告实拍质感，浅景深，顶部预留干净排版留白，竖屏9:16。"
                        ),
                    ),
                    ChatGPTImagePrompt(
                        scene_title="分镜1首帧参考图：黄金3秒微距亮相",
                        usage_note="在 ChatGPT 中上传产品图 + 复制下方提示词，生成的图片直接喂给可灵 Kling 图生视频",
                        aspect_ratio="9:16",
                        prompt_en=(
                            f"Keep the exact product from the uploaded reference image ({pname}, preserving every physical detail, texture, and branding accurately). "
                            "Close-up macro commercial shot on a sleek dark walnut desk, crisp morning sunlight beams cutting diagonally across the product surface highlighting its refined craftsmanship, soft bokeh background of a modern minimalist room. "
                            "Cinematic lighting, 50mm f/1.8 photography, ultra-realistic shadows and reflections, vertical 9:16, no text, no watermark."
                        ),
                        prompt_cn=(
                            f"严格还原上传参考图中的【{pname}】所有外观细节。微距商业特写，产品放置于深胡桃木极简桌面，清晨斜射光束打在机身表面凸显精致质感，背景为现代极简房间柔美虚化；50mm f/1.8 电影级光影与真实反射，无文字无水印，竖屏9:16。"
                        ),
                    ),
                    ChatGPTImagePrompt(
                        scene_title="分镜2首帧参考图：真实手持场景演示",
                        usage_note="在 ChatGPT 中上传产品图 + 复制下方提示词，用于生成第2镜首帧",
                        aspect_ratio="9:16",
                        prompt_en=(
                            f"Keep the exact product from the uploaded reference image ({pname}) held naturally and realistically in a young person's clean, well-manicured hand at chest level, outdoors in soft golden hour sunlight with an urban cafe background softly blurred. "
                            "Authentic UGC viral TikTok aesthetic combined with crisp Sony FX3 color grading, realistic skin texture, natural finger grip fitting the true scale of the product, vertical 9:16, no text."
                        ),
                        prompt_cn=(
                            f"严格还原上传参考图中的【{pname}】真实比例与外观。一位年轻人干净自然的手掌在胸前高度稳稳握持产品，背景是日落暖光下虚化的户外咖啡馆街道；真实自然的手指握持与皮肤质感，兼具 TikTok 爆款真实感与 Sony FX3 高级色彩，无文字，竖屏9:16。"
                        ),
                    ),
                    ChatGPTImagePrompt(
                        scene_title="分镜4首帧参考图：高级桌面美学收尾",
                        usage_note="在 ChatGPT 中上传产品图 + 复制下方提示词，用于生成结尾定格首帧",
                        aspect_ratio="9:16",
                        prompt_en=(
                            f"Keep the exact product from the uploaded reference image ({pname}, 100% faithful appearance) styled gracefully on an aesthetic minimalist desk alongside a ceramic coffee cup and soft linen notebook. "
                            "Warm cozy afternoon window light casting gentle shadows, dreamy creamy bokeh, luxury lifestyle editorial photography, clean composition, vertical 9:16, no text or logos added."
                        ),
                        prompt_cn=(
                            f"严格还原上传参考图中的【{pname}】全部细节。产品优雅陈列在极简美学书桌上，旁边搭配陶瓷咖啡杯与亚麻笔记本，午后窗边暖光投下柔和光影，奶油般柔和虚化，高级生活方式杂志质感，无文字，竖屏9:16。"
                        ),
                    ),
                ],
                kling_prompts=[
                    KlingVideoPrompt(
                        shot_no=1,
                        scene_title="分镜1：黄金3秒微距推镜亮相",
                        mode="图生视频 (I2V) — 上传「分镜1首帧参考图」",
                        recommended_params="时长: 5s | 画质: 高品质 | 运镜: 缓慢推进 (Zoom In) | 创意相关性: 0.45",
                        prompt_cn=f"画面中的【{pname}】保持外观与结构完全稳定不变形，镜头从近景平滑而富有节奏地向前推进至特写，清晨斜射阳光在机身磨砂表面缓缓流转产生细腻高光，空气中浮现极微小的金色光尘，商业广告电影级质感，动作丝滑自然。",
                        prompt_en=f"The {pname} remains completely solid and undistorted while the camera smoothly pushes forward into a crisp macro close-up. Morning sunbeams gently glide across the matte surface creating subtle specular highlights, faint golden dust motes drifting softly in the air, high-end commercial cinema look, ultra-smooth motion.",
                        negative_prompt="变形, 模糊, 产品Logo扭曲, 闪烁, 画面撕裂, 融化, 杂乱文字, 水印",
                    ),
                    KlingVideoPrompt(
                        shot_no=2,
                        scene_title="分镜2：自然手持展示与轻微转动",
                        mode="图生视频 (I2V) — 上传「分镜2首帧参考图」",
                        recommended_params="时长: 5s | 画质: 高品质 | 运镜: 跟随微移 | 创意相关性: 0.4",
                        prompt_cn=f"手掌自然稳健地微微转动手中的【{pname}】展示正面与侧面精致细节，大拇指轻触功能按键，背景户外咖啡馆柔和光斑轻轻晃动，日落暖光在产品边缘自然反射，真实物理手部动作，4K高清实拍质感。",
                        prompt_en=f"The hand naturally and gently rotates the {pname} to showcase its front and side details, thumb lightly pressing the control button. Soft warm golden-hour bokeh gently sways in the outdoor cafe background, realistic physical hand motion and natural light reflections, authentic 4K footage look.",
                        negative_prompt="多余手指, 手指畸变, 穿模, 产品变形, 模糊, 抖动过度, 水印, 文字",
                    ),
                    KlingVideoPrompt(
                        shot_no=3,
                        scene_title="分镜4：高级环绕定格收尾",
                        mode="图生视频 (I2V) — 上传「分镜4首帧参考图」",
                        recommended_params="时长: 5s | 画质: 高品质 | 运镜: 向右平滑环绕 (Orbit Right) | 创意相关性: 0.5",
                        prompt_cn=f"镜头围绕桌面上的【{pname}】优雅缓慢地向右弧形环绕约30度，午后窗边暖光随视角变化在机身与旁边陶瓷杯上轻轻流淌，桌面静物保持绝对稳固，浅景深层次分明，高级生活方式广告结尾氛围。",
                        prompt_en=f"The camera performs a slow, graceful 30-degree arc orbit to the right around the {pname} on the minimalist desk. Warm afternoon window light subtly shifts across the product surface and nearby ceramic cup while all objects stay perfectly grounded, creamy shallow depth of field, luxury commercial ending.",
                        negative_prompt="物体漂移, 变形, 闪烁, 穿模, 模糊, 畸变, 水印, 乱码文字",
                    ),
                ],
            )
            return analysis, TokenUsage(input_tokens=11800, output_tokens=2100)  # type: ignore[return-value]

        raise ValueError(f"Unsupported mock schema: {schema_cls}")
