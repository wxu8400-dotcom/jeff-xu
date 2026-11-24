from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .video_processor import extract_keyframes_from_path

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml"}
DOC_EXTS = {".pdf", ".docx"}


@dataclass
class UploadedRawFile:
    filename: str
    content_type: str
    data: bytes


@dataclass
class ParsedProductBundle:
    combined_text: str
    ai_images: list[tuple[bytes, str]] = field(default_factory=list)
    assets_meta: list[dict[str, Any]] = field(default_factory=list)


def _resize_jpeg(
    raw_bytes: bytes,
    max_side: int = 768,
    quality: int = 80,
) -> bytes:
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()


def make_thumbnail_data_url(raw_bytes: bytes, max_side: int = 280) -> str:
    thumb = _resize_jpeg(raw_bytes, max_side=max_side, quality=68)
    b64 = base64.b64encode(thumb).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    chunks: list[str] = []
    for page in reader.pages[:25]:
        txt = page.extract_text() or ""
        if txt.strip():
            chunks.append(txt.strip())
    return "\n".join(chunks)


def _extract_docx_text(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            row_txt = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_txt:
                parts.append(row_txt)
    return "\n".join(parts)


def parse_product_materials(
    files: list[UploadedRawFile],
    product_text: str = "",
    max_text_chars: int = 6000,
) -> ParsedProductBundle:
    text_segments: list[str] = []
    if product_text.strip():
        text_segments.append(f"【用户文字说明】\n{product_text.strip()}")

    ai_images: list[tuple[bytes, str]] = []
    assets_meta: list[dict[str, Any]] = []

    for item in files:
        ext = Path(item.filename or "").suffix.lower()
        size_kb = round(len(item.data) / 1024, 1)
        try:
            if ext in IMAGE_EXTS or item.content_type.startswith("image/"):
                resized = _resize_jpeg(item.data, max_side=768, quality=80)
                if len(ai_images) < 6:
                    ai_images.append((resized, "image/jpeg"))
                thumb_url = make_thumbnail_data_url(item.data, max_side=280)
                ref_url = None
                # Store crisp reference images (max 960px JPEG) for up to 5 multi-angle product photos
                # so AI prompt rewriting & image generation see front/side/detail angles accurately.
                existing_refs = sum(1 for a in assets_meta if a.get("reference_image"))
                if existing_refs < 5:
                    ref_bytes = _resize_jpeg(item.data, max_side=960, quality=82)
                    ref_b64 = base64.b64encode(ref_bytes).decode("ascii")
                    ref_url = f"data:image/jpeg;base64,{ref_b64}"
                assets_meta.append(
                    {
                        "filename": item.filename,
                        "kind": "image",
                        "size_kb": size_kb,
                        "thumbnail": thumb_url,
                        "reference_image": ref_url,
                    }
                )
            elif ext in VIDEO_EXTS or item.content_type.startswith("video/"):
                fd, tmp_name = tempfile.mkstemp(prefix="radar_prod_", suffix=ext or ".mp4")
                os.close(fd)
                tmp_path = Path(tmp_name)
                try:
                    tmp_path.write_bytes(item.data)
                    frames = extract_keyframes_from_path(tmp_path, max_frames=4, max_width=768)
                finally:
                    if tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except OSError:
                            pass

                thumb_url = None
                if frames:
                    thumb_url = make_thumbnail_data_url(frames[0], max_side=280)
                    for frame in frames:
                        if len(ai_images) < 6:
                            ai_images.append((frame, "image/jpeg"))
                assets_meta.append(
                    {
                        "filename": item.filename,
                        "kind": "video",
                        "size_kb": size_kb,
                        "extracted_frames": len(frames),
                        "thumbnail": thumb_url,
                    }
                )
            elif ext == ".pdf":
                extracted = _extract_pdf_text(item.data)
                if extracted:
                    text_segments.append(f"【文档：{item.filename}】\n{extracted}")
                assets_meta.append(
                    {
                        "filename": item.filename,
                        "kind": "document",
                        "size_kb": size_kb,
                        "chars": len(extracted),
                    }
                )
            elif ext == ".docx":
                extracted = _extract_docx_text(item.data)
                if extracted:
                    text_segments.append(f"【文档：{item.filename}】\n{extracted}")
                assets_meta.append(
                    {
                        "filename": item.filename,
                        "kind": "document",
                        "size_kb": size_kb,
                        "chars": len(extracted),
                    }
                )
            elif ext in TEXT_EXTS or item.content_type.startswith("text/"):
                try:
                    extracted = item.data.decode("utf-8")
                except UnicodeDecodeError:
                    extracted = item.data.decode("gb18030", errors="ignore")
                if extracted.strip():
                    text_segments.append(f"【文档：{item.filename}】\n{extracted.strip()}")
                assets_meta.append(
                    {
                        "filename": item.filename,
                        "kind": "text",
                        "size_kb": size_kb,
                        "chars": len(extracted),
                    }
                )
            else:
                assets_meta.append(
                    {
                        "filename": item.filename,
                        "kind": "unsupported",
                        "size_kb": size_kb,
                    }
                )
        except Exception as exc:
            logger.warning("Failed to parse asset %s: %s", item.filename, exc)
            assets_meta.append(
                {
                    "filename": item.filename,
                    "kind": "error",
                    "size_kb": size_kb,
                    "error": str(exc),
                }
            )

    combined = "\n\n".join(text_segments).strip()
    if len(combined) > max_text_chars:
        combined = combined[:max_text_chars] + "\n...（文档过长已智能截断以节省 Token）"

    return ParsedProductBundle(
        combined_text=combined,
        ai_images=ai_images,
        assets_meta=assets_meta,
    )
