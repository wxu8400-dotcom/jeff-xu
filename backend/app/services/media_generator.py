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
    aspect_ratio: str = "9:16",
    scene_title: str = "",
    product_name: str = "",
    settings: Settings | None = None,
) -> GeneratedImageResult:
    """Generate a product-fused storyboard frame or poster via Gemini native image or OpenAI gpt-image-1."""
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
        )
    return await _generate_image_gemini(
        cfg=cfg,
        prompt=prompt,
        ref_images=ref_images,
        aspect_ratio=aspect_ratio,
    )


async def _generate_image_gemini(
    *,
    cfg: Settings,
    prompt: str,
    ref_images: list[tuple[bytes, str]],
    aspect_ratio: str,
) -> GeneratedImageResult:
    if not cfg.gemini_api_key.strip():
        raise RuntimeError("未配置 GEMINI_API_KEY，无法使用 Gemini 生图引擎")

    from google import genai
    from google.genai import types

    http_options = None
    if cfg.gemini_base_url.strip():
        http_options = types.HttpOptions(
            base_url=cfg.gemini_base_url.strip().rstrip("/")
        )
    client = genai.Client(api_key=cfg.gemini_api_key.strip(), http_options=http_options)

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
        "gemini-2.0-flash-exp-image-generation",
    ):
        if m and m not in fallback_models:
            fallback_models.append(m)

    def _call_model(model_name: str):
        # Try passing image_config aspect_ratio if supported by SDK version; fallback cleanly otherwise
        gen_cfg_kwargs: dict[str, Any] = {"response_modalities": ["IMAGE", "TEXT"]}
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

    last_err: Exception | None = None
    for idx, model_name in enumerate(fallback_models):
        for retry in range(2):
            try:
                resp = await asyncio.to_thread(_call_model, model_name)
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
                last_err = RuntimeError(f"模型 {model_name} 未返回图片数据（可能触发安全策略或仅返回文本）")
                break
            except Exception as exc:
                last_err = exc
                err_up = str(exc).upper()
                is_404 = "404" in err_up or "NOT_FOUND" in err_up or "INVALID_ARGUMENT" in err_up
                is_transient = any(
                    k in err_up for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "OVERLOADED")
                )
                if is_404:
                    logger.warning("Gemini image model %s unavailable, trying next...", model_name)
                    break
                if is_transient and retry == 0:
                    await asyncio.sleep(3.0)
                    continue
                if idx < len(fallback_models) - 1:
                    logger.warning("Gemini image model %s failed (%s), switching fallback...", model_name, exc)
                    break
                raise

    raise RuntimeError(f"Gemini 一键生图失败：{last_err}")


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
) -> GeneratedImageResult:
    api_key = cfg.resolved_openai_image_key()
    if not api_key:
        raise RuntimeError(
            "尚未配置 OPENAI_IMAGE_API_KEY 或 OPENAI_API_KEY，请在 Render 环境变量中配置后使用 ChatGPT (gpt-image-1) 生图，或切换为 Gemini 生图。"
        )
    base_url = cfg.resolved_openai_image_base_url()
    model_name = cfg.openai_image_model or "gpt-image-1"
    size = "1024x1536" if aspect_ratio == "9:16" else ("1536x1024" if aspect_ratio == "16:9" else "1024x1024")
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        # Prefer /images/edits when product reference image is available so gpt-image-1 fuses the real product!
        if ref_images:
            try:
                files = [
                    ("image[]", (f"product_{i}.jpg", img_bytes, mime))
                    for i, (img_bytes, mime) in enumerate(ref_images[:2])
                ]
                data = {
                    "model": model_name,
                    "prompt": prompt,
                    "size": size,
                    "n": "1",
                }
                resp = await client.post(
                    f"{base_url}/images/edits",
                    headers=headers,
                    data=data,
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
                logger.warning(
                    "OpenAI /images/edits HTTP %s: %s (trying /images/generations fallback)",
                    resp.status_code,
                    resp.text[:240],
                )
            except Exception as exc:
                logger.warning("OpenAI /images/edits error: %s (trying /images/generations fallback)", exc)

        # Fallback to /images/generations
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
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI 生图接口返回 HTTP {resp.status_code}：{resp.text[:300]}")
        raw_img = await _extract_openai_image_bytes(client, resp.json())
        if not raw_img:
            raise RuntimeError("OpenAI 生图接口未返回有效图片数据")
        opt_bytes, w, h = _optimize_generated_jpeg(raw_img)
        return GeneratedImageResult(
            image_bytes=opt_bytes,
            mime_type="image/jpeg",
            width=w,
            height=h,
            provider="openai",
            model_name=model_name,
        )


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
    """Support BOTH:
    1) Direct Bearer token (KLING_API_KEY) for Alipay/WeChat relay gateways;
    2) Official Kling Open Platform HS256 JWT signed with KLING_ACCESS_KEY + KLING_SECRET_KEY.
    """
    if cfg.kling_api_key.strip():
        return cfg.kling_api_key.strip()
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


async def generate_kling_video_clip(
    *,
    image_bytes: bytes,
    prompt: str,
    negative_prompt: str = "",
    duration_sec: int = 5,
    settings: Settings | None = None,
) -> GeneratedVideoResult:
    """Generate a 5s/10s vertical I2V video clip via Kling AI (official or relay),
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
            model_name="mock-kling-i2v",
            external_task_id="mock-task-001",
        )

    token = build_kling_auth_token(cfg)
    base_url = cfg.kling_api_base_url.strip().rstrip("/")
    model_name = cfg.kling_model_name.strip() or "kling-v2-master"
    mode = cfg.kling_mode.strip() or "std"
    img_b64 = base64.b64encode(image_bytes).decode("ascii")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model_name": model_name,
        "mode": mode,
        "duration": str(dur),
        "image": img_b64,
        "prompt": prompt[:2400],
        "cfg_scale": 0.5,
    }
    if negative_prompt.strip():
        body["negative_prompt"] = negative_prompt.strip()[:1000]

    submit_paths = ["/v1/videos/image2video", "/kling/v1/videos/image2video"]
    task_id: str | None = None
    active_prefix = "/v1/videos/image2video"
    last_err_text = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        for path in submit_paths:
            resp = await client.post(f"{base_url}{path}", headers=headers, json=body)
            if resp.status_code == 200:
                payload = resp.json()
                data = payload.get("data") or payload
                tid = (
                    data.get("task_id")
                    or data.get("id")
                    or payload.get("task_id")
                )
                if tid:
                    task_id = str(tid)
                    active_prefix = path
                    break
                last_err_text = resp.text[:300]
            else:
                last_err_text = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in (404, 405):
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
            p_data = p_json.get("data") or p_json
            st = str(p_data.get("task_status") or p_data.get("status") or "").lower()
            if st in ("succeed", "succeeded", "completed", "success"):
                task_res = p_data.get("task_result") or {}
                videos = task_res.get("videos") or p_data.get("videos") or []
                if videos and isinstance(videos, list) and isinstance(videos[0], dict):
                    video_url = videos[0].get("url")
                if not video_url:
                    video_url = p_data.get("video_url") or task_res.get("url")
                break
            if st in ("failed", "error", "canceled"):
                msg = p_data.get("task_status_msg") or p_data.get("message") or "任务失败"
                raise RuntimeError(f"可灵 Kling 生成失败：{msg}")

        if not video_url:
            raise RuntimeError(f"可灵 Kling 任务 {task_id} 等待超时，请稍后重试")

        dl = await client.get(video_url, follow_redirects=True)
        if dl.status_code != 200 or len(dl.content) < 1000:
            raise RuntimeError(f"下载可灵生成视频失败（HTTP {dl.status_code}）")

        return GeneratedVideoResult(
            video_bytes=dl.content,
            mime_type="video/mp4",
            duration_sec=float(dur),
            provider="kling",
            model_name=model_name,
            external_task_id=task_id,
            media_url=video_url,
        )
