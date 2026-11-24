from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image, ImageDraw

from ..config import Settings, get_settings
from .video_stitcher import image_to_motion_clip

logger = logging.getLogger(__name__)


@dataclass
class GeneratedImageResult:
    image_bytes: bytes
    mime_type: str
    width: int
    height: int
    provider: str
    model_name: str


@dataclass
class GeneratedVideoResult:
    video_bytes: bytes
    mime_type: str
    duration_sec: float
    provider: str
    model_name: str
    external_task_id: str | None = None
    media_url: str | None = None


def decode_data_url_image(data_url: str | None) -> tuple[bytes, str] | None:
    if not data_url or not data_url.startswith("data:image/"):
        return None
    try:
        header, b64_part = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "").strip() or "image/jpeg"
        raw = base64.b64decode(b64_part)
        if len(raw) > 100:
            return raw, mime
    except Exception:
        return None
    return None


def _optimize_generated_jpeg(raw_bytes: bytes, max_side: int = 1280) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        w, h = img.size
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        return buf.getvalue(), w, h


def _generate_mock_product_image(
    *,
    scene_title: str,
    product_name: str,
    ref_images: list[tuple[bytes, str]],
    provider: str,
) -> GeneratedImageResult:
    w, h = 540, 960
    canvas = Image.new("RGB", (w, h), (15, 23, 42))
    draw = ImageDraw.Draw(canvas)

    # Stylized studio gradient backdrop
    for y in range(h):
        r = int(15 + (y / h) * 18)
        g = int(23 + (y / h) * 42)
        b = int(42 + (y / h) * 65)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Glowing frame & pedestal
    draw.rounded_rectangle([36, 48, w - 36, h - 48], radius=28, outline=(56, 189, 248), width=3)
    draw.ellipse([90, 560, w - 90, 660], fill=(30, 58, 138))

    # Embed actual product reference photo if present
    if ref_images:
        try:
            with Image.open(io.BytesIO(ref_images[0][0])) as prod:
                prod = prod.convert("RGB")
                prod.thumbnail((340, 340), Image.Resampling.LANCZOS)
                px = (w - prod.width) // 2
                py = 250 + (340 - prod.height) // 2
                canvas.paste(prod, (px, py))
        except Exception:
            pass
    else:
        draw.rounded_rectangle([140, 290, 400, 550], radius=24, fill=(56, 189, 248))

    draw.rectangle([48, 72, w - 48, 136], fill=(15, 23, 42))
    draw.text((68, 92), f"MOCK STUDIO [{provider.upper()}] 9:16", fill=(125, 211, 252))
    draw.rectangle([48, h - 180, w - 48, h - 72], fill=(15, 23, 42))
    draw.text((68, h - 156), f"Product: {product_name[:28]}", fill=(248, 250, 252))
    draw.text((68, h - 120), f"Scene: {scene_title[:32]}", fill=(148, 163, 184))

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=86, optimize=True)
    return GeneratedImageResult(
        image_bytes=buf.getvalue(),
        mime_type="image/jpeg",
        width=w,
        height=h,
        provider=provider,
        model_name=f"mock-{provider}-image",
    )


async def generate_product_image(
    *,
    prompt: str,
    ref_images: list[tuple[bytes, str]],
    provider: str | None = None,
    model_override: str = "",
    aspect_ratio: str = "9:16",
    scene_title: str = "",
    product_name: str = "",
    settings: Settings | None = None,
) -> GeneratedImageResult:
    """Generate a product-fused storyboard frame or poster via Gemini native image or OpenAI GPT Image 2.6."""
    cfg = settings or get_settings()
    chosen_provider = (provider or cfg.default_image_provider or "gemini").lower()

    if cfg.enable_mock_mode:
        return _generate_mock_product_image(
            scene_title=scene_title or "Storyboard Frame",
            product_name=product_name or "Product",
            ref_images=ref_images,
            provider=chosen_provider,
        )

    if chosen_provider == "openai":
        return await _generate_image_openai(
            cfg=cfg,
            prompt=prompt,
            ref_images=ref_images,
            aspect_ratio=aspect_ratio,
            model_override=model_override,
        )
    return await _generate_image_gemini(
        cfg=cfg,
        prompt=prompt,
        ref_images=ref_images,
        aspect_ratio=aspect_ratio,
    )


def _build_gemini_image_client(cfg: Settings):
    from google import genai
    from google.genai import types

    # google-genai >= 3.x defaults to api_version="v1", while Gemini native image
    # generation models (gemini-2.5-flash-image, gemini-3.1-flash-image-preview, etc.)
    # and image_config are served on "v1beta".
    http_kwargs: dict[str, Any] = {"api_version": "v1beta"}
    if cfg.gemini_base_url.strip():
        http_kwargs["base_url"] = cfg.gemini_base_url.strip().rstrip("/")
    return genai.Client(
        api_key=cfg.gemini_api_key.strip(),
        http_options=types.HttpOptions(**http_kwargs),
    )


def _discover_gemini_image_models(client: Any) -> tuple[list[str], list[str]]:
    """Query ListModels on the user's key to auto-discover available image models."""
    gen_content_models: list[str] = []
    imagen_models: list[str] = []
    try:
        for m in client.models.list():
            raw_name = str(getattr(m, "name", "") or "")
            short = raw_name.replace("models/", "").strip()
            if not short:
                continue
            low = short.lower()
            actions = [str(a).lower() for a in (getattr(m, "supported_actions", None) or [])]
            if "image" in low and "gemini" in low:
                if not actions or any("generatecontent" in a for a in actions):
                    gen_content_models.append(short)
            elif "imagen" in low:
                if not actions or any("predict" in a or "generateimages" in a for a in actions):
                    imagen_models.append(short)
    except Exception as exc:
        logger.warning("Gemini ListModels discovery skipped: %s", exc)
    return gen_content_models, imagen_models


async def _generate_image_gemini(
    *,
    cfg: Settings,
    prompt: str,
    ref_images: list[tuple[bytes, str]],
    aspect_ratio: str,
) -> GeneratedImageResult:
    if not cfg.gemini_api_key.strip():
        raise RuntimeError("未配置 GEMINI_API_KEY，无法使用 Gemini 生图引擎")

    from google.genai import types

    client = _build_gemini_image_client(cfg)

    full_prompt = (
        f"Generate a single photorealistic commercial image in vertical {aspect_ratio} aspect ratio. "
        f"CRITICAL: Keep the exact product shown in the attached reference image(s) 100% faithful in shape, "
        f"color, material, proportions, and surface details. Do NOT distort or replace the product design.\n\n"
        f"{prompt}"
    )

    parts: list[Any] = []
    for img_bytes, mime in ref_images[:2]:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
    parts.append(types.Part.from_text(text=full_prompt))

    fallback_models: list[str] = []
    for m in (
        cfg.gemini_image_model,
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image-preview",
        "gemini-3-pro-image-preview",
        "gemini-2.5-flash-image-preview",
        "gemini-2.0-flash-preview-image-generation",
    ):
        if m and m not in fallback_models:
            fallback_models.append(m)

    def _call_model(model_name: str, use_image_config: bool):
        gen_cfg_kwargs: dict[str, Any] = {"response_modalities": ["IMAGE", "TEXT"]}
        if use_image_config:
            try:
                image_cfg_cls = getattr(types, "ImageConfig", None)
                if image_cfg_cls is not None:
                    gen_cfg_kwargs["image_config"] = image_cfg_cls(aspect_ratio=aspect_ratio)
            except Exception:
                pass
        return client.models.generate_content(
            model=model_name,
            contents=parts,
            config=types.GenerateContentConfig(**gen_cfg_kwargs),
        )

    errors_by_model: list[str] = []
    quota_errors: list[str] = []
    discovered = False
    imagen_candidates: list[str] = [
        "imagen-4.0-fast-generate-001",
        "imagen-4.0-generate-001",
        "imagen-3.0-generate-002",
    ]

    idx = 0
    while idx < len(fallback_models):
        model_name = fallback_models[idx]
        idx += 1
        use_img_cfg = True

        for attempt in range(2):
            try:
                resp = await asyncio.to_thread(_call_model, model_name, use_img_cfg)
                img_bytes = _extract_gemini_image_bytes(resp)
                if img_bytes:
                    opt_bytes, w, h = _optimize_generated_jpeg(img_bytes)
                    return GeneratedImageResult(
                        image_bytes=opt_bytes,
                        mime_type="image/jpeg",
                        width=w,
                        height=h,
                        provider="gemini",
                        model_name=model_name,
                    )
                errors_by_model.append(f"{model_name}: 未返回图片（仅返回文本或触发安全过滤）")
                break
            except Exception as exc:
                err_str = str(exc)
                err_up = err_str.upper()

                # If ImageConfig parameter itself is rejected, retry the SAME model without image_config
                if use_img_cfg and "INVALID_ARGUMENT" in err_up and ("IMAGE_CONFIG" in err_up or "ASPECT_RATIO" in err_up or "UNKNOWN NAME" in err_up):
                    logger.warning("Gemini %s rejected image_config, retrying without it...", model_name)
                    use_img_cfg = False
                    continue

                is_404 = "404" in err_up or "NOT_FOUND" in err_up
                is_quota_zero = ("429" in err_up or "RESOURCE_EXHAUSTED" in err_up) and (
                    "LIMIT: 0" in err_up or "QUOTA" in err_up
                )
                is_transient = any(k in err_up for k in ("503", "UNAVAILABLE", "429", "OVERLOADED"))

                if is_quota_zero:
                    quota_errors.append(f"{model_name}: {err_str[:180]}")
                    logger.warning("Gemini image model %s quota exhausted/0, trying next...", model_name)
                    break
                if is_404:
                    errors_by_model.append(f"{model_name}: 404")
                    logger.warning("Gemini image model %s returned 404 on v1beta, trying next...", model_name)
                    # On first 404 wave, also dynamically discover any image models available on this key
                    if not discovered:
                        discovered = True
                        disc_gemini, disc_imagen = await asyncio.to_thread(
                            _discover_gemini_image_models, client
                        )
                        for dm in disc_gemini:
                            if dm not in fallback_models:
                                fallback_models.append(dm)
                        for im in disc_imagen:
                            if im not in imagen_candidates:
                                imagen_candidates.insert(0, im)
                    break
                if is_transient and attempt == 0:
                    await asyncio.sleep(3.0)
                    continue

                errors_by_model.append(f"{model_name}: {err_str[:180]}")
                logger.warning("Gemini image model %s failed: %s", model_name, exc)
                break

    # Final fallback: try Imagen generate_images (text-only fallback if Gemini multimodal image models are 404)
    if not quota_errors:
        for im_model in imagen_candidates:
            try:
                im_resp = await asyncio.to_thread(
                    client.models.generate_images,
                    model=im_model,
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio=aspect_ratio if aspect_ratio in ("1:1", "3:4", "4:3", "9:16", "16:9") else "9:16",
                    ),
                )
                gen_imgs = getattr(im_resp, "generated_images", None) or []
                if gen_imgs:
                    im_obj = getattr(gen_imgs[0], "image", None)
                    im_bytes = getattr(im_obj, "image_bytes", None)
                    if isinstance(im_bytes, bytes) and len(im_bytes) > 200:
                        opt_bytes, w, h = _optimize_generated_jpeg(im_bytes)
                        return GeneratedImageResult(
                            image_bytes=opt_bytes,
                            mime_type="image/jpeg",
                            width=w,
                            height=h,
                            provider="gemini",
                            model_name=im_model,
                        )
            except Exception as exc:
                err_up = str(exc).upper()
                if "429" in err_up or "RESOURCE_EXHAUSTED" in err_up:
                    quota_errors.append(f"{im_model}: {str(exc)[:160]}")
                else:
                    errors_by_model.append(f"{im_model}: {str(exc)[:120]}")

    if quota_errors:
        raise RuntimeError(
            "当前 Google Gemini 免费版 API Key 的生图模型配额已用尽或为 0（Google 近期限制了部分免费 Key 的生图额度）。"
            "解决办法：① 在 Google AI Studio 开启计费（按量几分钱一张）；或 ② 在 Render 环境变量填入 OPENAI_IMAGE_API_KEY 切换为 ChatGPT (gpt-image-2) 生图。"
            f" 详情：{quota_errors[0]}"
        )

    summary = " | ".join(errors_by_model[:4]) or "所有生图模型均不可用"
    raise RuntimeError(f"Gemini 一键生图失败（已自动通过 v1beta 尝试多模型）：{summary}")


def _extract_gemini_image_bytes(resp: Any) -> bytes | None:
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None:
                data = getattr(inline, "data", None)
                if isinstance(data, bytes) and len(data) > 200:
                    return data
                if isinstance(data, str) and len(data) > 200:
                    return base64.b64decode(data)
    return None


async def _generate_image_openai(
    *,
    cfg: Settings,
    prompt: str,
    ref_images: list[tuple[bytes, str]],
    aspect_ratio: str,
    model_override: str = "",
) -> GeneratedImageResult:
    api_key = cfg.resolved_openai_image_key()
    if not api_key:
        raise RuntimeError(
            "尚未配置 OPENAI_IMAGE_API_KEY 或 OPENAI_API_KEY，请在 Render 环境变量中配置后使用最新 GPT Image 2.6 (gpt-image-2.6-sunburst) 生图，或切换为 Gemini 生图。"
        )
    base_url = cfg.resolved_openai_image_base_url()
    size = "1024x1536" if aspect_ratio == "9:16" else ("1536x1024" if aspect_ratio == "16:9" else "1024x1024")
    headers = {"Authorization": f"Bearer {api_key}"}

    # Prioritize latest GPT Image 2.6 (sunburst / flare) -> gpt-image-2 -> earlier fallback
    model_chain: list[str] = []
    for m in (
        model_override.strip(),
        cfg.openai_image_model,
        "gpt-image-2.6-sunburst",
        "gpt-image-2.6-flare",
        "gpt-image-2",
        "gpt-image-1.5",
        "gpt-image-1",
    ):
        if m and m not in model_chain:
            model_chain.append(m)

    last_err = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        for model_name in model_chain:
            # 1) Prefer /images/edits when product reference image is available so GPT Image 2 fuses the real product!
            if ref_images:
                # Try both standard OpenAI `image[]` and single `image` field for maximum relay compatibility
                field_variants = [
                    [
                        ("image[]", (f"product_{i}.jpg", img_bytes, mime))
                        for i, (img_bytes, mime) in enumerate(ref_images[:2])
                    ],
                    [("image", ("product_0.jpg", ref_images[0][0], ref_images[0][1]))],
                ]
                model_not_found = False
                for files in field_variants:
                    try:
                        resp = await client.post(
                            f"{base_url}/images/edits",
                            headers=headers,
                            data={
                                "model": model_name,
                                "prompt": prompt,
                                "size": size,
                                "n": "1",
                            },
                            files=files,
                        )
                        if resp.status_code == 200:
                            raw_img = await _extract_openai_image_bytes(client, resp.json())
                            if raw_img:
                                opt_bytes, w, h = _optimize_generated_jpeg(raw_img)
                                return GeneratedImageResult(
                                    image_bytes=opt_bytes,
                                    mime_type="image/jpeg",
                                    width=w,
                                    height=h,
                                    provider="openai",
                                    model_name=model_name,
                                )
                        txt = resp.text[:260]
                        last_err = f"{model_name} /images/edits HTTP {resp.status_code}: {txt}"
                        low = txt.lower()
                        if resp.status_code == 404 or "model_not_found" in low or "does not exist" in low:
                            model_not_found = True
                            break
                        logger.warning("%s (trying next field/fallback)", last_err)
                    except Exception as exc:
                        last_err = f"{model_name} /images/edits error: {exc}"
                        logger.warning("%s", last_err)
                if model_not_found:
                    continue

            # 2) Fallback to /images/generations
            try:
                resp = await client.post(
                    f"{base_url}/images/generations",
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "size": size,
                        "n": 1,
                    },
                )
                if resp.status_code == 200:
                    raw_img = await _extract_openai_image_bytes(client, resp.json())
                    if raw_img:
                        opt_bytes, w, h = _optimize_generated_jpeg(raw_img)
                        return GeneratedImageResult(
                            image_bytes=opt_bytes,
                            mime_type="image/jpeg",
                            width=w,
                            height=h,
                            provider="openai",
                            model_name=model_name,
                        )
                txt = resp.text[:260]
                last_err = f"{model_name} /images/generations HTTP {resp.status_code}: {txt}"
                low = txt.lower()
                if resp.status_code == 404 or "model_not_found" in low or "does not exist" in low:
                    continue
                raise RuntimeError(f"OpenAI 生图接口返回错误：{last_err}")
            except RuntimeError:
                raise
            except Exception as exc:
                last_err = f"{model_name} error: {exc}"

    raise RuntimeError(f"OpenAI 一键生图失败：{last_err or '未返回有效图片数据'}")


async def _extract_openai_image_bytes(
    client: httpx.AsyncClient, payload: dict[str, Any]
) -> bytes | None:
    items = payload.get("data") or []
    if not items or not isinstance(items, list):
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    b64 = first.get("b64_json")
    if isinstance(b64, str) and len(b64) > 100:
        return base64.b64decode(b64)
    url = first.get("url")
    if isinstance(url, str) and url.startswith("http"):
        dl = await client.get(url)
        if dl.status_code == 200 and len(dl.content) > 200:
            return dl.content
    return None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_kling_auth_token(cfg: Settings) -> str:
    """Support:
    1) Direct Bearer token (KLING_API_KEY, or auto-reused 302.ai OPENAI_IMAGE_API_KEY);
    2) Official Kling Open Platform HS256 JWT signed with KLING_ACCESS_KEY + KLING_SECRET_KEY.
    """
    bearer = cfg.resolved_kling_api_key()
    if bearer:
        return bearer
    ak = cfg.kling_access_key.strip()
    sk = cfg.kling_secret_key.strip()
    if not ak or not sk:
        raise RuntimeError(
            "尚未配置可灵 Kling API 凭据（请配置 KLING_API_KEY，或官方 KLING_ACCESS_KEY + KLING_SECRET_KEY）"
        )
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps({"iss": ak, "exp": now + 1800, "nbf": now - 5}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    sig = hmac.new(sk.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def _extract_kling_video_url(payload: Any) -> str | None:
    """Extract final MP4 URL from all known Kling official & 302.ai response schemas."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    # 1) Official Kling: data.task_result.videos[0].url
    task_res = data.get("task_result")
    if isinstance(task_res, dict):
        videos = task_res.get("videos")
        if isinstance(videos, list):
            for v in videos:
                if isinstance(v, dict) and isinstance(v.get("url"), str) and v["url"].startswith("http"):
                    return v["url"]
        if isinstance(task_res.get("url"), str) and task_res["url"].startswith("http"):
            return task_res["url"]

    # 2) 302.ai / Kling works format: data.works[0].resource.resource_url or resource
    works = data.get("works")
    if isinstance(works, list):
        for w in works:
            if not isinstance(w, dict):
                continue
            res = w.get("resource")
            if isinstance(res, dict):
                for key in ("resource_url", "resource", "url", "video_url"):
                    val = res.get(key)
                    if isinstance(val, str) and val.startswith("http"):
                        return val
            for key in ("url", "video_url"):
                val = w.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    return val

    # 3) Direct list or flat URL fields
    videos = data.get("videos")
    if isinstance(videos, list):
        for v in videos:
            if isinstance(v, dict) and isinstance(v.get("url"), str) and v["url"].startswith("http"):
                return v["url"]
    for key in ("video_url", "output_url", "response_url", "url"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val

    # 4) Recursive fallback for any .mp4 URL
    def _scan_mp4(obj: Any) -> str | None:
        if isinstance(obj, str):
            if obj.startswith("http") and ".mp4" in obj.lower():
                return obj
            return None
        if isinstance(obj, list):
            for item in obj:
                found = _scan_mp4(item)
                if found:
                    return found
        elif isinstance(obj, dict):
            for v in obj.values():
                found = _scan_mp4(v)
                if found:
                    return found
        return None

    return _scan_mp4(payload)


async def generate_kling_video_clip(
    *,
    image_bytes: bytes,
    prompt: str,
    negative_prompt: str = "",
    duration_sec: int = 5,
    model_override: str = "",
    settings: Settings | None = None,
) -> GeneratedVideoResult:
    """Generate a 5s/10s vertical I2V video clip via Kling AI (302.ai relay or official API),
    or realistic FFmpeg Ken Burns MP4 in Mock mode."""
    cfg = settings or get_settings()
    dur = 10 if int(duration_sec) >= 8 else 5

    if cfg.enable_mock_mode:
        mp4 = await asyncio.to_thread(
            image_to_motion_clip,
            image_bytes,
            duration_sec=3.0,
            zoom_direction="in",
        )
        return GeneratedVideoResult(
            video_bytes=mp4,
            mime_type="video/mp4",
            duration_sec=3.0,
            provider="kling",
            model_name=model_override.strip() or "mock-kling-v3",
            external_task_id="mock-task-001",
        )

    token = build_kling_auth_token(cfg)
    base_url = cfg.resolved_kling_base_url()
    is_302 = "302.ai" in base_url.lower() or "302ai.com" in base_url.lower()
    mode = cfg.kling_mode.strip() or "std"
    img_b64 = base64.b64encode(image_bytes).decode("ascii")
    img_data_url = f"data:image/jpeg;base64,{img_b64}"

    model_chain: list[str] = []
    for m in (
        model_override.strip(),
        cfg.kling_model_name.strip(),
        "kling-v3",
        "kling-v2-6",
        "kling-v2-5-turbo",
        "kling-v2-1",
        "kling-v2-master",
        "kling-v1-6",
    ):
        if m and m not in model_chain:
            model_chain.append(m)

    submit_paths = (
        ["/klingai/v1/videos/image2video", "/kling/v1/videos/image2video", "/v1/videos/image2video"]
        if is_302
        else ["/v1/videos/image2video", "/klingai/v1/videos/image2video", "/kling/v1/videos/image2video"]
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    task_id: str | None = None
    active_prefix = submit_paths[0]
    chosen_model = model_chain[0]
    last_err_text = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        for path in submit_paths:
            path_not_found = False
            for candidate_model in model_chain:
                for img_val in (img_b64, img_data_url):
                    body: dict[str, Any] = {
                        "model_name": candidate_model,
                        "mode": mode,
                        "duration": str(dur),
                        "image": img_val,
                        "prompt": prompt[:2400],
                        "cfg_scale": 0.5,
                    }
                    if negative_prompt.strip():
                        body["negative_prompt"] = negative_prompt.strip()[:1000]

                    resp = await client.post(f"{base_url}{path}", headers=headers, json=body)
                    if resp.status_code == 200:
                        payload = resp.json()
                        code = payload.get("code")
                        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                        tid = (
                            data.get("task_id")
                            or data.get("id")
                            or payload.get("task_id")
                        )
                        if tid:
                            task_id = str(tid)
                            active_prefix = path
                            chosen_model = candidate_model
                            break
                        msg = str(payload.get("message") or resp.text[:260])
                        last_err_text = f"{candidate_model} ({path}): code={code} {msg}"
                        low_msg = msg.lower()
                        if "image" in low_msg and img_val == img_b64:
                            continue
                        if any(k in low_msg for k in ("model", "not support", "invalid")):
                            break
                        break
                    else:
                        txt = resp.text[:280]
                        last_err_text = f"{candidate_model} ({path}) HTTP {resp.status_code}: {txt}"
                        low = txt.lower()
                        if resp.status_code in (404, 405) and "model" not in low:
                            path_not_found = True
                            break
                        if "image" in low and img_val == img_b64:
                            continue
                        if any(k in low for k in ("model", "not exist", "unsupported", "invalid_model")):
                            break
                        # Auth / balance errors should fail immediately without spamming retries
                        if resp.status_code in (401, 402, 403):
                            raise RuntimeError(f"可灵 Kling 鉴权或余额异常：{last_err_text}")
                        break
                if task_id or path_not_found:
                    break
            if task_id:
                break

        if not task_id:
            raise RuntimeError(f"可灵 Kling 提交任务失败：{last_err_text}")

        # Poll task status up to ~6 minutes
        video_url: str | None = None
        for _ in range(72):
            await asyncio.sleep(5.0)
            poll_headers = {"Authorization": f"Bearer {build_kling_auth_token(cfg)}"}
            poll_resp = await client.get(
                f"{base_url}{active_prefix}/{task_id}",
                headers=poll_headers,
            )
            if poll_resp.status_code != 200:
                continue
            p_json = poll_resp.json()
            p_data = p_json.get("data") if isinstance(p_json.get("data"), dict) else p_json
            st = str(p_data.get("task_status") or p_data.get("status") or "").lower()
            if st in ("succeed", "succeeded", "completed", "success", "99"):
                video_url = _extract_kling_video_url(p_json)
                if video_url:
                    break
            if st in ("failed", "error", "canceled", "50"):
                msg = p_data.get("task_status_msg") or p_data.get("message") or "任务失败"
                raise RuntimeError(f"可灵 Kling 生成失败：{msg}")

        if not video_url:
            raise RuntimeError(f"可灵 Kling 任务 {task_id} 等待超时或未返回视频地址，请稍后重试")

        dl = await client.get(video_url, follow_redirects=True)
        if dl.status_code != 200 or len(dl.content) < 1000:
            raise RuntimeError(f"下载可灵生成视频失败（HTTP {dl.status_code}）")

        return GeneratedVideoResult(
            video_bytes=dl.content,
            mime_type="video/mp4",
            duration_sec=float(dur),
            provider="kling",
            model_name=chosen_model,
            external_task_id=task_id,
            media_url=video_url,
        )
