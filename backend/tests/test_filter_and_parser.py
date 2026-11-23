from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from docx import Document
from PIL import Image

from app.services.collectors.base import CandidateVideo
from app.services.filter_engine import run_hard_filter
from app.services.product_parser import UploadedRawFile, parse_product_materials


def test_parse_multimodal_product_materials():
    # Generate sample PNG image in memory
    img = Image.new("RGB", (1200, 900), color=(40, 120, 220))
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")

    # Generate sample DOCX in memory
    doc = Document()
    doc.add_paragraph("产品名：迷你高速手持冰敷风扇")
    doc.add_paragraph("核心卖点：3秒冰敷降温，续航12小时，USB-C快充")
    doc_buf = io.BytesIO()
    doc.save(doc_buf)

    files = [
        UploadedRawFile("product.png", "image/png", img_buf.getvalue()),
        UploadedRawFile(
            "spec.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            doc_buf.getvalue(),
        ),
        UploadedRawFile("notes.txt", "text/plain", "主打欧美夏季户外场景".encode("utf-8")),
    ]
    bundle = parse_product_materials(files, product_text="磨砂白极简外观")

    assert "迷你高速手持冰敷风扇" in bundle.combined_text
    assert "主打欧美夏季户外场景" in bundle.combined_text
    assert "磨砂白极简外观" in bundle.combined_text
    assert len(bundle.ai_images) == 1
    assert len(bundle.assets_meta) == 3
    img_meta = bundle.assets_meta[0]
    assert img_meta["kind"] == "image"
    assert str(img_meta["thumbnail"]).startswith("data:image/jpeg;base64,")


def test_hard_filter_dedup_thresholds_and_relax():
    now = datetime.now(timezone.utc)
    cands = [
        CandidateVideo("tiktok", "1", "https://t/1", views=200_000, likes=12_000, duration_sec=22, published_at=(now - timedelta(days=2)).isoformat()),
        CandidateVideo("tiktok", "1", "https://t/1", views=200_000, likes=12_000, duration_sec=22, published_at=(now - timedelta(days=2)).isoformat()),  # duplicate
        CandidateVideo("instagram", "2", "https://i/2", views=5_000, likes=100, duration_sec=18, published_at=(now - timedelta(days=3)).isoformat()),  # below threshold
        CandidateVideo("youtube", "3", "https://y/3", views=500_000, likes=35_000, duration_sec=25, published_at=(now - timedelta(days=5)).isoformat()),
    ]
    res = run_hard_filter(
        cands,
        min_views=100_000,
        min_likes=5_000,
        date_range_days=30,
        target_count=2,
        auto_relax=False,
    )
    assert res.total_input == 4
    assert res.deduped_count == 3
    assert len(res.selected) == 2
    assert {c.platform_video_id for c in res.selected} == {"1", "3"}

    # With auto_relax=True and very strict thresholds, it should relax gracefully
    relaxed = run_hard_filter(
        cands,
        min_views=10_000_000,
        min_likes=500_000,
        date_range_days=30,
        target_count=2,
        auto_relax=True,
    )
    assert relaxed.relaxed_applied is True
    assert len(relaxed.selected) >= 2
