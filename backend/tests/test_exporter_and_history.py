from __future__ import annotations

import time


def _wait_done(client, session_id: str) -> dict:
    for _ in range(100):
        detail = client.get(f"/api/scans/{session_id}").json()
        if detail["status"] in ("completed", "failed"):
            return detail
        time.sleep(0.1)
    raise AssertionError("timeout")


def test_history_crud_export_and_direct_urls(make_client):
    client = make_client(password="", mock_mode=True)

    # 1. Run Direct URL analysis
    resp = client.post(
        "/api/scans/analyze-urls",
        data={
            "urls": "https://www.tiktok.com/@demo/video/99887766\nhttps://www.youtube.com/shorts/abc123xyz",
            "product_name_override": "磁吸便携咖啡杯",
            "product_text": "316不锈钢磁吸防漏咖啡杯",
        },
    )
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    detail = _wait_done(client, sid)
    assert detail["status"] == "completed"
    assert detail["mode"] == "direct_urls"
    assert len(detail["videos"]) == 2
    assert " · 磁吸便携咖啡杯" in detail["history_title"]

    # 2. History listing & search
    history = client.get("/api/scans").json()
    assert len(history) == 1
    assert history[0]["video_count"] == 2
    assert len(client.get("/api/scans?q=咖啡杯").json()) == 1
    assert len(client.get("/api/scans?q=不存在的产品").json()) == 0

    # 3. Export Markdown & JSON
    md_resp = client.get(f"/api/scans/{sid}/export?format=md")
    assert md_resp.status_code == 200
    md_text = md_resp.text
    assert "磁吸便携咖啡杯" in md_text
    assert "ChatGPT Images 提示词" in md_text
    assert "可灵 Kling 视频生成提示词" in md_text

    json_resp = client.get(f"/api/scans/{sid}/export?format=json")
    assert json_resp.status_code == 200
    assert len(json_resp.json()["videos"]) == 2

    # 4. Delete history record cascades properly
    del_resp = client.delete(f"/api/scans/{sid}")
    assert del_resp.status_code == 200
    assert client.get(f"/api/scans/{sid}").status_code == 404
    assert client.get("/api/scans").json() == []
