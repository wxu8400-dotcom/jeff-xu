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
    DirectorPlan,
    DirectorRevisionResponse,
    KlingVideoPrompt,
    LearnedMemoryItem,
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

    _discovered_gemini_models: list[str] | None = None
    _dead_gemini_models: set[str] = set()

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @classmethod
    def _parse_recommended_model_from_error(cls, err_msg: str) -> str | None:
        m = re.search(
            r"use\s+models/([a-zA-Z0-9._-]+)",
            err_msg or "",
            flags=re.IGNORECASE,
        )
        return m.group(1) if m else None

    @classmethod
    def _discover_gemini_flash_models_sync(cls, client: Any) -> list[str]:
        if cls._discovered_gemini_models is not None:
            return list(cls._discovered_gemini_models)
        found: list[str] = []
        try:
            for model in client.models.list():
                name = str(getattr(model, "name", "") or "")
                if name.startswith("models/"):
                    name = name[len("models/") :]
                lower = name.lower()
                if not lower.startswith("gemini-") or "flash" not in lower:
                    continue
                if any(
                    bad in lower
                    for bad in (
                        "image",
                        "tts",
                        "audio",
                        "live",
                        "embed",
                        "robotics",
                        "computer",
                        "exp-image",
                    )
                ):
                    continue
                actions = [
                    str(a).lower()
                    for a in (getattr(model, "supported_actions", None) or [])
                ]
                if actions and not any("generatecontent" in a for a in actions):
                    continue
                found.append(name)
        except Exception as exc:
            logger.warning("Gemini models.list() discovery failed: %s", exc)
            return []

        def _sort_key(model_id: str) -> tuple[float, int, str]:
            ver_m = re.search(r"gemini-(\d+(?:\.\d+)?)", model_id.lower())
            ver = float(ver_m.group(1)) if ver_m else 0.0
            is_stable = 0 if ("preview" in model_id or "exp" in model_id) else 1
            return (ver, is_stable, model_id)

        found.sort(key=_sort_key, reverse=True)
        cls._discovered_gemini_models = found
        logger.info("Discovered live Gemini flash models: %s", found)
        return list(found)

    def is_configured(self) -> bool:
        if self.settings.enable_mock_mode:
            return True
        if self.settings.ai_provider == "gemini":
            return bool(self.settings.gemini_api_key.strip())
        return bool(self.settings.openai_api_key.strip())

    def _build_gemini_client(self, *, timeout_ms: int = 30_000):
        from google import genai
        from google.genai import types

        http_kwargs: dict[str, Any] = {"timeout": timeout_ms}
        if self.settings.gemini_base_url.strip():
            http_kwargs["base_url"] = self.settings.gemini_base_url.strip().rstrip("/")
        return genai.Client(
            api_key=self.settings.gemini_api_key.strip(),
            http_options=types.HttpOptions(**http_kwargs),
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
                is_schema_err = isinstance(exc, (ValueError, json.JSONDecodeError)) or (
                    "validationerror" in type(exc).__name__.lower()
                )
                if attempt == 0:
                    if is_schema_err:
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
        per_call_timeout = 22.0 if tier == "fast" else 55.0
        client = self._build_gemini_client(timeout_ms=int(per_call_timeout * 1000))

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
            [
                model_name,
                "gemini-3.8-flash-lite",
                "gemini-3.8-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.5-flash",
                "gemini-3-flash-preview",
            ]
            if tier == "fast"
            else [
                model_name,
                "gemini-3.8-flash",
                "gemini-3.5-flash",
                "gemini-3.8-flash-lite",
                "gemini-3.5-flash-lite",
                "gemini-3-flash-preview",
            ]
        )
        queue: list[str] = []
        for m in fallback_chain:
            if m and m not in queue and m not in self._dead_gemini_models:
                queue.append(m)

        resp = None
        last_err: Exception | None = None
        last_non_404_err: Exception | None = None
        discovered_added = False
        idx = 0
        gemini_deadline = asyncio.get_running_loop().time() + (28.0 if tier == "fast" else 75.0)

        while idx < len(queue):
            if asyncio.get_running_loop().time() >= gemini_deadline:
                logger.warning("Gemini fallback budget exceeded (tier=%s), switching to relay fallback", tier)
                break
            candidate_model = queue[idx]
            idx += 1
            for retry in range(2):
                remaining = gemini_deadline - asyncio.get_running_loop().time()
                if remaining <= 2.0:
                    break
                try:
                    resp = await asyncio.wait_for(
                        asyncio.to_thread(_sync_call, candidate_model),
                        timeout=min(per_call_timeout, remaining),
                    )
                    break
                except Exception as exc:
                    err_raw = str(exc) or type(exc).__name__
                    err_str = err_raw.upper()
                    is_404 = "404" in err_str or "NOT_FOUND" in err_str
                    is_timeout = isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "TIMEOUT" in err_str
                    is_transient = (
                        is_timeout
                        or "500" in err_str
                        or "INTERNAL" in err_str
                        or "502" in err_str
                        or "503" in err_str
                        or "504" in err_str
                        or "UNAVAILABLE" in err_str
                        or "DEADLINE_EXCEEDED" in err_str
                        or "429" in err_str
                        or "RESOURCE_EXHAUSTED" in err_str
                        or "OVERLOADED" in err_str
                    )
                    last_err = exc
                    if not is_404:
                        last_non_404_err = exc

                    if is_404:
                        self._dead_gemini_models.add(candidate_model)
                        logger.warning(
                            "Gemini model %s unavailable (404), trying next fallback...",
                            candidate_model,
                        )
                        rec = self._parse_recommended_model_from_error(err_raw)
                        if rec and rec not in queue and rec not in self._dead_gemini_models:
                            queue.insert(idx, rec)
                            logger.info("Queued Google-recommended Gemini model: %s", rec)
                        if not discovered_added:
                            discovered_added = True
                            try:
                                live_models = await asyncio.wait_for(
                                    asyncio.to_thread(self._discover_gemini_flash_models_sync, client),
                                    timeout=8.0,
                                )
                            except Exception:
                                live_models = []
                            for lm in live_models:
                                if lm not in queue and lm not in self._dead_gemini_models:
                                    queue.append(lm)
                        break

                    if is_transient:
                        if retry == 0 and not is_timeout and (gemini_deadline - asyncio.get_running_loop().time()) > 8.0:
                            logger.warning(
                                "Gemini model %s returned transient error (%s), retrying in 1.5s...",
                                candidate_model,
                                err_raw[:120],
                            )
                            await asyncio.sleep(1.5)
                            continue
                        if not discovered_added and idx >= len(queue) and (gemini_deadline - asyncio.get_running_loop().time()) > 10.0:
                            discovered_added = True
                            try:
                                live_models = await asyncio.wait_for(
                                    asyncio.to_thread(self._discover_gemini_flash_models_sync, client),
                                    timeout=8.0,
                                )
                            except Exception:
                                live_models = []
                            for lm in live_models:
                                if lm not in queue and lm not in self._dead_gemini_models:
                                    queue.append(lm)
                        logger.warning(
                            "Gemini model %s still failing (%s), switching to next fallback...",
                            candidate_model,
                            err_raw[:120],
                        )
                        break
                    raise
            if resp is not None:
                break

        if resp is None:
            # Safety net: if Gemini models are temporarily unavailable/deprecated/rate-limited
            # and an OpenAI-compatible relay key (e.g. 302.ai) is configured, seamlessly fall back
            # so a radar scan never aborts mid-way.
            relay_key = (
                self.settings.openai_api_key.strip()
                or self.settings.resolved_openai_image_key()
            )
            relay_url = (
                self.settings.openai_base_url.strip()
                if self.settings.openai_api_key.strip()
                else self.settings.resolved_openai_image_base_url()
            )
            if relay_key:
                logger.warning(
                    "All Gemini models failed (%s); falling back to OpenAI-compatible relay (%s)",
                    last_non_404_err or last_err,
                    relay_url,
                )
                return await self._call_openai_compatible(
                    prompt=prompt,
                    tier=tier,
                    images=images,
                    video_bytes=video_bytes,
                    api_key_override=relay_key,
                    base_url_override=relay_url,
                )
            final_err = last_non_404_err or last_err
            assert final_err is not None
            raise final_err
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
        api_key_override: str = "",
        base_url_override: str = "",
    ) -> tuple[str, TokenUsage]:
        from openai import AsyncOpenAI

        resolved_key = (api_key_override or self.settings.openai_api_key).strip()
        resolved_url = (base_url_override or self.settings.openai_base_url).strip()
        is_302 = "302.ai" in resolved_url.lower() or "302ai.com" in resolved_url.lower()

        configured_model = (
            self.settings.openai_fast_model
            if tier == "fast"
            else self.settings.openai_deep_model
        )
        if is_302:
            raw_candidates = (
                ["gpt-4o-mini", "gpt-4.1-mini", "gemini-2.5-flash", configured_model]
                if tier == "fast"
                else ["gpt-4.1-mini", "gpt-4o-mini", "gemini-2.5-flash", "gpt-4.1", configured_model]
            )
        else:
            raw_candidates = (
                [configured_model, "gpt-4o-mini", "gpt-4.1-mini"]
                if tier == "fast"
                else [configured_model, "gpt-4.1-mini", "gpt-4o-mini", "gpt-4o"]
            )

        candidates: list[str] = []
        for m in raw_candidates:
            if m and m not in candidates:
                candidates.append(m)

        client = AsyncOpenAI(
            api_key=resolved_key,
            base_url=resolved_url,
            timeout=35.0 if tier == "fast" else 70.0,
            max_retries=0,
        )

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        all_images = list(images)
        if video_bytes:
            frames = await asyncio.to_thread(extract_keyframes_from_bytes, video_bytes, 10)
            all_images.extend([(f, "image/jpeg") for f in frames])

        img_detail = "high" if tier == "deep" else "low"
        max_imgs = 12 if tier == "deep" else 6
        for img_bytes, mime in all_images[:max_imgs]:
            b64 = base64.b64encode(img_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": img_detail},
                }
            )

        last_err: Exception | None = None
        tried_errors: list[str] = []
        for target_model in candidates:
            for use_json_mode in (True, False):
                try:
                    kwargs: dict[str, Any] = {
                        "model": target_model,
                        "messages": [{"role": "user", "content": content}],
                        "temperature": 0.35 if tier == "fast" else 0.5,
                    }
                    if use_json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    resp = await client.chat.completions.create(**kwargs)
                    text = resp.choices[0].message.content or ""
                    usage_obj = resp.usage
                    usage = TokenUsage(
                        input_tokens=int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                        output_tokens=int(getattr(usage_obj, "completion_tokens", 0) or 0),
                    )
                    return text, usage
                except Exception as exc:
                    last_err = exc
                    err_str = str(exc)
                    tried_errors.append(f"{target_model}: {err_str[:120]}")
                    logger.warning(
                        "OpenAI-compatible model %s (json_mode=%s) failed: %s",
                        target_model,
                        use_json_mode,
                        err_str[:220],
                    )
                    # Only retry same model without response_format if JSON mode might be unsupported
                    if use_json_mode and (
                        "response_format" in err_str.lower()
                        or "json_object" in err_str.lower()
                        or "400" in err_str
                    ):
                        continue
                    break

        raise RuntimeError(
            f"备选 AI 通道全部尝试失败（{' | '.join(tried_errors[-3:])}）"
        ) from last_err

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
                        is_cartoon_or_animation=False,
                        has_realistic_human=True,
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
                director_plan=DirectorPlan(
                    original_plot_summary="开场人物在真实室内空间展示原物品，镜头推进完成使用演示并以高级桌面定格收尾。",
                    original_video_prompt_cn=(
                        "写实电影级竖屏短视频：开场一位年轻人在自然采光的现代极简房间中坐在桌前，手持原片核心物品朝镜头展示细节；"
                        "随后镜头平稳推进，手指轻按演示核心动作与前后对比效果；最后镜头缓慢环绕桌面定格收尾，光影柔和真实。"
                    ),
                    original_video_prompt_en=(
                        "Photorealistic vertical 9:16 live-action video: Opening with a young person seated at a modern minimalist desk in natural daylight holding the original item; "
                        "camera smoothly pushes in as they demonstrate the item in action, finishing with a gentle 30-degree arc orbit on the clean tabletop."
                    ),
                    current_master_prompt_cn=(
                        "写实电影级竖屏短视频：开场一位年轻人在自然采光的现代极简房间中坐在桌前，手持原片核心物品朝镜头展示细节；"
                        "随后镜头平稳推进，手指轻按演示核心动作与前后对比效果；最后镜头缓慢环绕桌面定格收尾，光影柔和真实。"
                    ),
                    current_master_prompt_en=(
                        "Photorealistic vertical 9:16 live-action video: Opening with a young person seated at a modern minimalist desk in natural daylight holding the original item; "
                        "camera smoothly pushes in as they demonstrate the item in action, finishing with a gentle 30-degree arc orbit on the clean tabletop."
                    ),
                    has_user_customized=False,
                    ai_character_profile_cn="26 岁原创时尚女性创作者，深棕色微卷齐肩发、自然清透妆容，身穿米白色极简针织衫",
                    ai_character_profile_en="An original stylish 26-year-old woman with shoulder-length wavy dark brown hair, natural makeup, wearing a minimalist cream knit top",
                    product_placement_plan=f"等待你输入修改意见后，仅按你的要求替换指定人物、场景或【{pname}】，未提及部分保持原片不变。",
                    open_questions_for_user=[],
                    revision_status="draft",
                    revision_history=[],
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
                        adapted_visual_for_product=f"1:1 保留原片开场悬念场景，原创 AI 人物在冷暖撞色光影台面旁触发视觉钩子，镜头快速推进引出【{pname}】",
                        audio_sfx="清脆“咔哒”启动声 + 低频重音卡点",
                        production_mode="ai",
                        real_shoot_guide=f"若改为实拍：将【{pname}】摆在深色桌面上，手机开 2x 焦段从 35cm 匀速前推至 12cm，拍 3 秒。",
                        spoken_line="别划走！3秒让你看懂什么叫降维打击！",
                        replication_action="keep_scene",
                        director_advice="1:1 保留原片开场悬念构图与运镜，仅将原片人物换成统一的原创 AI 形象，先抓完播率。",
                        has_person=True,
                    ),
                    StoryboardShot(
                        shot_no=2,
                        time_range="00:03-00:10",
                        shot_size="近景手持",
                        camera_movement="平稳跟随横移",
                        original_visual="单手握持演示核心功能，画面干净无杂物",
                        adapted_visual_for_product=f"同一位原创 AI 人物自然握持/展示【{pname}】，在原片同款干净场景中直观呈现「{dna.core_selling_points[0] if dna.core_selling_points else '核心卖点'}」",
                        audio_sfx="节奏感轻快英文/电子鼓点 BGM 切入",
                        production_mode="real_shoot",
                        real_shoot_guide=f"📱 手机竖屏固定在桌面支架或单手握持，45° 侧自然光，真实单手拿起【{pname}】按下开关并展示效果，拍 5~6 秒即可。",
                        spoken_line=f"每天最烦人的痛点，用这个【{pname}】一按直接搞定。",
                        replication_action="insert_product",
                        director_advice=f"本镜为最佳产品替换槽位：1:1 沿用原片近景演示动作，把原物品无缝替换成【{pname}】。",
                        has_person=True,
                    ),
                    StoryboardShot(
                        shot_no=3,
                        time_range="00:10-00:18",
                        shot_size="中景分屏/对比",
                        camera_movement="固定机位微推",
                        original_visual="使用前烦躁痛点 vs 使用后轻松愉悦的强反差",
                        adapted_visual_for_product=f"沿用原片前后反差结构，对比没有【{pname}】与使用【{pname}】后的清爽高级状态",
                        audio_sfx="转场“嗖”音效 + 人声高潮金句",
                        production_mode="real_shoot",
                        real_shoot_guide=f"📱 同一个机位固定不动拍两段各 3 秒：先拍没放【{pname}】的普通画面，再把【{pname}】放上去并点亮/启动，剪辑一秒硬切反差拉满。",
                        spoken_line="前后对比太离谱了，难怪全网都在抢！",
                        replication_action="rewrite_scene",
                        director_advice=f"保留原片对比转场节奏，但将背景道具微调为更契合【{pname}】的真实使用场景以提升说服力。",
                        has_person=False,
                    ),
                    StoryboardShot(
                        shot_no=4,
                        time_range="00:18-00:24",
                        shot_size="特写定格",
                        camera_movement="缓慢环绕 30 度",
                        original_visual="产品精致摆放，四周虚化光斑收尾",
                        adapted_visual_for_product=f"1:1 复刻原片收尾环绕构图，【{pname}】精致陈列在桌面美学场景中，柔光勾勒轮廓，预留字幕引导区",
                        audio_sfx="BGM 干净收尾 + 轻柔提示音",
                        production_mode="ai",
                        real_shoot_guide=f"若改为实拍：将【{pname}】放在窗边桌面，手机缓慢向右弧形绕拍 30 度，拍 4 秒定格。",
                        spoken_line="想要同款直接看下方，用过一次真的回不去。",
                        replication_action="insert_product",
                        director_advice=f"1:1 复刻原片结尾电影级环绕定格，把原单品替换为【{pname}】强化品牌记忆与转化。",
                        has_person=False,
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

        if schema_cls is DirectorRevisionResponse:
            current_raw = ctx.get("current_analysis") or {}
            feedback = str(ctx.get("user_feedback") or "").strip()
            updated = VideoDeepAnalysis.model_validate(current_raw)
            base_cn = (
                updated.director_plan.current_master_prompt_cn
                or updated.director_plan.original_video_prompt_cn
            )
            updated.director_plan.current_master_prompt_cn = (
                f"{base_cn}（已按你的要求精准替换：{feedback}；未提及画面细节完全保持原视频不变）"
            )
            updated.director_plan.current_master_prompt_en = (
                f"{updated.director_plan.current_master_prompt_en or updated.director_plan.original_video_prompt_en} "
                f"[Surgically updated per user direction: {feedback}; all unmentioned framing and actions kept 100% identical]"
            )
            updated.director_plan.has_user_customized = True
            if updated.storyboard:
                updated.storyboard[0].adapted_visual_for_product = (
                    f"{updated.storyboard[0].adapted_visual_for_product}（已按你的意见调整：{feedback}）"
                )
                updated.storyboard[0].director_advice = f"已根据你的最新反馈「{feedback}」同步更新提示词"
            if any(k in feedback for k in ("人物", "女生", "男生", "亚洲", "穿搭", "换角")):
                updated.director_plan.ai_character_profile_cn = f"已按你要求更新的原创 AI 人物：{feedback}"
                updated.director_plan.ai_character_profile_en = (
                    f"Updated original AI character matching user direction: {feedback}"
                )
            if updated.chatgpt_images_prompts:
                updated.chatgpt_images_prompts[0].prompt_en = (
                    f"{updated.chatgpt_images_prompts[0].prompt_en} [Director revision applied: {feedback}]"
                )
            learned: list[LearnedMemoryItem] = []
            if len(feedback) >= 6:
                cat = (
                    "character"
                    if any(k in feedback for k in ("人物", "女生", "男生", "贵妇", "模特", "换角"))
                    else "product_replacement"
                )
                learned.append(
                    LearnedMemoryItem(
                        category=cat,
                        product_scope="global",
                        rule_summary=f"遵循用户创作偏好：{feedback[:52]}",
                        example_snippet=feedback[:80],
                    )
                )
            return (
                DirectorRevisionResponse(
                    director_reply=f"明白！已按你的意见「{feedback}」同步更新了分镜方案、AI 人物设定以及对应的生图/可灵提示词，并已沉淀至长期导演记忆库。你可以检查一下，满意就可以点击「确认定稿」开始按步骤出片啦！",
                    changed_shots=[1],
                    learned_memories=learned,
                    analysis=updated,
                ),
                TokenUsage(input_tokens=3200, output_tokens=1800),
            )  # type: ignore[return-value]

        raise ValueError(f"Unsupported mock schema: {schema_cls}")
