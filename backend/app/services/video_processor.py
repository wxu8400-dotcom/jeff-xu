from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_PTS_TIME_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def compress_video_for_analysis(
    input_path: Path,
    max_duration_sec: int = 60,
    target_height: int = 540,
    target_fps: int = 2,
) -> bytes:
    """Compress video to crisp 540p/2fps + 48kbps mono audio so quick opening frames stay clear."""
    if not is_ffmpeg_available():
        return input_path.read_bytes()

    out_fd, out_name = tempfile.mkstemp(prefix="radar_cmp_", suffix=".mp4")
    os.close(out_fd)
    out_path = Path(out_name)
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-t",
            str(max_duration_sec),
            "-vf",
            f"scale=-2:{target_height},fps={target_fps}",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "ultrafast",
            "-crf",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "48k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
        if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 1024:
            return out_path.read_bytes()
        logger.warning(
            "FFmpeg compression failed (code=%s): %s",
            result.returncode,
            result.stderr.decode("utf-8", errors="ignore")[-400:],
        )
        return input_path.read_bytes()
    finally:
        if out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass


def _compute_inclusive_timestamps(duration: float, max_frames: int) -> list[float]:
    """Always include the VERY FIRST opening frame (~0.15s) through the ending frame
    so opening scenes (e.g. sitting in an airplane at 0:00) are NEVER skipped."""
    count = max(1, max_frames)
    if duration <= 0.6 or count == 1:
        return [0.1]
    start_ts = 0.15
    end_ts = max(start_ts + 0.1, duration - 0.25)
    if count == 2:
        return [round(start_ts, 2), round(end_ts, 2)]
    step = (end_ts - start_ts) / (count - 1)
    return [round(start_ts + step * i, 2) for i in range(count)]


def detect_scene_cut_timestamps(
    input_path: Path,
    *,
    threshold: float = 0.22,
    max_cuts: int = 12,
) -> list[float]:
    """Detect sharp shot cuts / transitions using FFmpeg scene-change scoring so fast
    transitions (e.g. occlusion wipes, explosions, sudden cuts) are never missed."""
    if not is_ffmpeg_available():
        return []
    try:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(input_path),
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-vsync",
            "vfr",
            "-f",
            "null",
            "-",
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25,
            check=False,
        )
        stderr_text = res.stderr.decode("utf-8", errors="ignore")
        raw_cuts = [float(m.group(1)) for m in _PTS_TIME_RE.finditer(stderr_text)]
        deduped: list[float] = []
        for ts in sorted(raw_cuts):
            if ts < 0.25:
                continue
            if not deduped or (ts - deduped[-1]) >= 0.45:
                deduped.append(round(ts, 2))
            if len(deduped) >= max_cuts:
                break
        return deduped
    except Exception as exc:
        logger.debug("Scene cut detection skipped: %s", exc)
        return []


def merge_shot_and_uniform_timestamps(
    duration: float,
    scene_cuts: list[float],
    max_frames: int = 16,
) -> list[float]:
    """Merge FFmpeg scene-cut timestamps (offset +0.12s into the new shot) with
    inclusive uniform timestamps so both steady beats AND sudden cuts are captured."""
    if duration <= 0.6 or max_frames <= 2:
        return _compute_inclusive_timestamps(duration, max_frames)

    end_ts = max(0.25, duration - 0.2)
    anchors: list[float] = [0.15, round(end_ts, 2)]
    for cut in scene_cuts:
        # Sample right after the cut so the new shot is crisp rather than mid-dissolve
        settled = round(min(end_ts, max(0.2, cut + 0.12)), 2)
        anchors.append(settled)

    # Deduplicate anchors within 0.35s
    anchors.sort()
    chosen: list[float] = []
    for ts in anchors:
        if not chosen or (ts - chosen[-1]) >= 0.35:
            chosen.append(ts)
    if len(chosen) > max_frames:
        # Keep first, last, and evenly spread interior cuts
        step = (len(chosen) - 1) / (max_frames - 1)
        chosen = [chosen[round(i * step)] for i in range(max_frames)]
        return sorted(set(chosen))

    # Fill remaining budget with uniform timestamps
    uniform = _compute_inclusive_timestamps(duration, max_frames)
    min_gap = max(0.28, (duration / max(max_frames, 1)) * 0.45)
    for ts in uniform:
        if len(chosen) >= max_frames:
            break
        if all(abs(ts - existing) >= min_gap for existing in chosen):
            chosen.append(ts)
    return sorted(chosen)[:max_frames]


def extract_keyframes_from_path(
    input_path: Path,
    max_frames: int = 10,
    max_width: int = 960,
) -> list[bytes]:
    """Extract evenly spaced JPEG keyframes from a local video file, guaranteed to start at ~0.15s."""
    if not is_ffmpeg_available():
        return []

    tmp_dir = Path(tempfile.mkdtemp(prefix="radar_frames_"))
    try:
        duration = _probe_duration_sec(input_path)
        frames: list[bytes] = []
        if duration and duration > 0.6:
            timestamps = _compute_inclusive_timestamps(duration, max_frames)
            for idx, ts in enumerate(timestamps):
                out_jpg = tmp_dir / f"frame_{idx:02d}.jpg"
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(ts),
                    "-i",
                    str(input_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale='min({max_width},iw)':-2",
                    "-q:v",
                    "3",
                    str(out_jpg),
                ]
                subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=False,
                )
                if out_jpg.exists() and out_jpg.stat().st_size > 200:
                    frames.append(out_jpg.read_bytes())
        else:
            out_pattern = str(tmp_dir / "frame_%02d.jpg")
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-vf",
                f"fps=1,scale='min({max_width},iw)':-2",
                "-frames:v",
                str(max_frames),
                "-q:v",
                "3",
                out_pattern,
            ]
            subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25, check=False
            )
            for jpg in sorted(tmp_dir.glob("frame_*.jpg"))[:max_frames]:
                frames.append(jpg.read_bytes())
        return frames
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def extract_keyframes_with_timestamps(
    video_bytes: bytes, max_frames: int = 16, max_width: int = 960
) -> list[tuple[float, bytes]]:
    """Extract dense keyframes paired with exact timestamps (starting at 0.15s) so fast
    1-second transitions (e.g. object flying back into cabin) are NEVER missed."""
    if not is_ffmpeg_available():
        return []
    fd, tmp_name = tempfile.mkstemp(prefix="radar_vb_", suffix=".mp4")
    os.close(fd)
    tmp_path = Path(tmp_name)
    tmp_dir = Path(tempfile.mkdtemp(prefix="radar_frames_"))
    try:
        tmp_path.write_bytes(video_bytes)
        duration = _probe_duration_sec(tmp_path)
        results: list[tuple[float, bytes]] = []
        if duration and duration > 0.6:
            scene_cuts = detect_scene_cut_timestamps(tmp_path, threshold=0.22, max_cuts=10)
            timestamps = merge_shot_and_uniform_timestamps(
                duration, scene_cuts, max_frames=max_frames
            )
            for idx, ts in enumerate(timestamps):
                out_jpg = tmp_dir / f"frame_{idx:02d}.jpg"
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(ts),
                    "-i",
                    str(tmp_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale='min({max_width},iw)':-2",
                    "-q:v",
                    "3",
                    str(out_jpg),
                ]
                subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=False,
                )
                if out_jpg.exists() and out_jpg.stat().st_size > 200:
                    results.append((ts, out_jpg.read_bytes()))
        else:
            raw_frames = extract_keyframes_from_path(
                tmp_path, max_frames=max_frames, max_width=max_width
            )
            results = [(round(0.15 + i * 1.0, 2), f) for i, f in enumerate(raw_frames)]
        return results
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def extract_keyframes_from_bytes(
    video_bytes: bytes, max_frames: int = 10, max_width: int = 960
) -> list[bytes]:
    return [
        frame
        for _, frame in extract_keyframes_with_timestamps(
            video_bytes, max_frames=max_frames, max_width=max_width
        )
    ]


def extract_filmstrip_previews(video_bytes: bytes, max_frames: int = 8) -> list[str]:
    """Extract compact base64 JPEG preview strip starting at 0.15s so the UI displays
    the genuine original video frames right above the prompt."""
    from PIL import Image

    raw_frames = extract_keyframes_from_bytes(
        video_bytes, max_frames=max_frames, max_width=320
    )
    out: list[str] = []
    for raw in raw_frames:
        try:
            with Image.open(io.BytesIO(raw)) as im:
                rgb = im.convert("RGB")
                rgb.thumbnail((240, 360))
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG", quality=66, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                out.append(f"data:image/jpeg;base64,{b64}")
        except Exception:
            continue
    return out


def build_timestamped_contact_sheet(
    frames_with_ts: list[tuple[float, bytes]],
    *,
    cols: int = 4,
    tile_width: int = 270,
    tile_height: int = 420,
) -> bytes | None:
    """Render a crisp timestamp-labeled contact sheet (inspired by replicate-video-ad &
    video-prompt-reverse) so Vision LLMs can see the complete shot timeline in one glance."""
    if not frames_with_ts:
        return None
    from PIL import Image, ImageDraw, ImageOps

    count = len(frames_with_ts)
    actual_cols = max(1, min(cols, count))
    rows = (count + actual_cols - 1) // actual_cols
    pad = 8
    sheet_w = actual_cols * tile_width + (actual_cols + 1) * pad
    sheet_h = rows * tile_height + (rows + 1) * pad
    canvas = Image.new("RGB", (sheet_w, sheet_h), (12, 16, 28))
    draw = ImageDraw.Draw(canvas)

    for idx, (ts, raw) in enumerate(frames_with_ts):
        r = idx // actual_cols
        c = idx % actual_cols
        x0 = pad + c * (tile_width + pad)
        y0 = pad + r * (tile_height + pad)
        try:
            with Image.open(io.BytesIO(raw)) as im:
                tile = ImageOps.fit(im.convert("RGB"), (tile_width, tile_height))
                canvas.paste(tile, (x0, y0))
        except Exception:
            continue
        label = f"#{idx + 1}  {ts:05.2f}s"
        badge_w = min(tile_width - 12, 118)
        draw.rectangle(
            [x0 + 6, y0 + 6, x0 + 6 + badge_w, y0 + 28],
            fill=(0, 0, 0),
        )
        draw.text((x0 + 12, y0 + 11), label, fill=(255, 255, 255))

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue()


def extract_and_save_source_audio(
    video_id: str,
    video_bytes: bytes,
    media_dir: Path,
) -> bool:
    """Extract the original video's real audio track to disk (MP3) so the Studio can
    automatically tempo-align and match original-video-style sound effects into the final MP4."""
    if not is_ffmpeg_available() or not video_bytes:
        return False
    fd, tmp_name = tempfile.mkstemp(prefix="radar_srcaud_", suffix=".mp4")
    os.close(fd)
    tmp_path = Path(tmp_name)
    out_mp3 = media_dir / f"source_audio_{video_id}.mp3"
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(video_bytes)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(tmp_path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-threads",
            "1",
            str(out_mp3),
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if res.returncode == 0 and out_mp3.exists() and out_mp3.stat().st_size > 1024:
            return True
        if out_mp3.exists():
            try:
                out_mp3.unlink()
            except OSError:
                pass
        return False
    except Exception as exc:
        logger.debug("Source audio extraction skipped for %s: %s", video_id, exc)
        return False
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_source_audio_bytes(video_id: str, media_dir: Path) -> bytes | None:
    path = media_dir / f"source_audio_{video_id}.mp3"
    if path.exists() and path.stat().st_size > 1024:
        return path.read_bytes()
    return None


def save_source_evidence_pack(
    video_id: str,
    video_bytes: bytes,
    media_dir: Path,
    *,
    max_frames: int = 16,
) -> dict[str, object]:
    """Extract scene-cut + dense HD keyframes, build a timestamped contact sheet, and persist
    them to disk so later prompt-audit / revision calls can re-inspect the genuine source video."""
    frames_with_ts = extract_keyframes_with_timestamps(
        video_bytes, max_frames=max_frames, max_width=720
    )
    if not frames_with_ts:
        return {"timestamps": [], "previews": [], "contact_sheet_saved": False}

    ev_dir = media_dir / f"source_evidence_{video_id}"
    ev_dir.mkdir(parents=True, exist_ok=True)

    timestamps: list[float] = []
    manifest_frames: list[dict[str, object]] = []
    for idx, (ts, raw) in enumerate(frames_with_ts):
        fname = f"frame_{idx:02d}.jpg"
        (ev_dir / fname).write_bytes(raw)
        timestamps.append(ts)
        manifest_frames.append({"index": idx + 1, "timestamp_sec": ts, "file": fname})

    sheet_bytes = build_timestamped_contact_sheet(frames_with_ts)
    if sheet_bytes:
        (ev_dir / "contact_sheet.jpg").write_bytes(sheet_bytes)

    audio_saved = extract_and_save_source_audio(video_id, video_bytes, media_dir)

    manifest = {
        "video_id": video_id,
        "frame_count": len(frames_with_ts),
        "timestamps": timestamps,
        "frames": manifest_frames,
        "has_contact_sheet": bool(sheet_bytes),
        "has_source_audio": audio_saved,
    }
    (ev_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Also build compact base64 previews (up to 10 evenly selected frames) for UI display
    from PIL import Image

    if len(frames_with_ts) <= 10:
        preview_items = frames_with_ts
    else:
        step = (len(frames_with_ts) - 1) / 9.0
        preview_items = [frames_with_ts[round(i * step)] for i in range(10)]

    previews: list[str] = []
    preview_timestamps: list[float] = []
    for ts, raw in preview_items:
        try:
            with Image.open(io.BytesIO(raw)) as im:
                rgb = im.convert("RGB")
                rgb.thumbnail((240, 360))
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG", quality=66, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                previews.append(f"data:image/jpeg;base64,{b64}")
                preview_timestamps.append(ts)
        except Exception:
            continue

    return {
        "timestamps": preview_timestamps,
        "all_timestamps": timestamps,
        "previews": previews,
        "contact_sheet_saved": bool(sheet_bytes),
    }


def load_source_evidence_images(
    video_id: str,
    media_dir: Path,
    *,
    max_key_frames: int = 8,
) -> tuple[list[tuple[bytes, str]], list[float]]:
    """Load the persisted timestamped contact sheet + representative HD keyframes for a video
    so the AI auditor can visually verify a user's prompt against the real source footage."""
    ev_dir = media_dir / f"source_evidence_{video_id}"
    if not ev_dir.exists():
        return [], []

    images: list[tuple[bytes, str]] = []
    timestamps: list[float] = []

    sheet_path = ev_dir / "contact_sheet.jpg"
    if sheet_path.exists() and sheet_path.stat().st_size > 500:
        images.append((sheet_path.read_bytes(), "image/jpeg"))

    manifest_path = ev_dir / "manifest.json"
    frame_entries: list[dict[str, object]] = []
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            frame_entries = list(data.get("frames") or [])
            timestamps = [float(t) for t in (data.get("timestamps") or [])]
        except Exception:
            frame_entries = []

    if frame_entries:
        if len(frame_entries) <= max_key_frames:
            picked = frame_entries
        else:
            step = (len(frame_entries) - 1) / max(1, max_key_frames - 1)
            picked = [frame_entries[round(i * step)] for i in range(max_key_frames)]
        for entry in picked:
            fpath = ev_dir / str(entry.get("file") or "")
            if fpath.exists() and fpath.stat().st_size > 200:
                images.append((fpath.read_bytes(), "image/jpeg"))
    else:
        for fpath in sorted(ev_dir.glob("frame_*.jpg"))[:max_key_frames]:
            if fpath.stat().st_size > 200:
                images.append((fpath.read_bytes(), "image/jpeg"))

    return images, timestamps


def _probe_duration_sec(input_path: Path) -> float | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(input_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if res.returncode == 0:
            return float(res.stdout.decode().strip())
    except Exception:
        return None
    return None


async def download_and_compress_video(
    *,
    video_url: str,
    download_url: str | None = None,
    max_download_mb: int = 80,
) -> bytes | None:
    """Download video via direct URL first, then yt-dlp fallback; compress and clean up /tmp."""
    import asyncio

    fd, tmp_name = tempfile.mkstemp(prefix="radar_dl_", suffix=".mp4")
    os.close(fd)
    raw_path = Path(tmp_name)
    downloaded = False
    try:
        if download_url and download_url.startswith("http"):
            downloaded = await _download_direct(
                download_url,
                raw_path,
                max_bytes=max_download_mb * 1024 * 1024,
                referer=video_url,
            )
        if not downloaded and video_url.startswith("http"):
            try:
                downloaded = await asyncio.wait_for(
                    _download_via_ytdlp(video_url, raw_path),
                    timeout=28.0,
                )
            except asyncio.TimeoutError:
                logger.warning("yt-dlp download timed out for %s", video_url)
                downloaded = False

        if not downloaded or not raw_path.exists() or raw_path.stat().st_size < 2048:
            return None

        return await asyncio.to_thread(compress_video_for_analysis, raw_path)
    except Exception as exc:
        logger.warning("Video download/compression failed for %s: %s", video_url, exc)
        return None
    finally:
        if raw_path.exists():
            try:
                raw_path.unlink()
            except OSError:
                pass


async def _download_direct(
    url: str,
    dest: Path,
    max_bytes: int,
    referer: str = "",
) -> bool:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }
    if referer and referer.startswith("http"):
        if "tiktok" in referer.lower() or "tiktok" in url.lower():
            headers["Referer"] = "https://www.tiktok.com/"
        elif "instagram" in referer.lower() or "cdninstagram" in url.lower():
            headers["Referer"] = "https://www.instagram.com/"
        elif "douyin" in referer.lower() or "douyin" in url.lower():
            headers["Referer"] = "https://www.douyin.com/"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(28.0, connect=10.0),
            follow_redirects=True,
            headers=headers,
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    return False
                ctype = resp.headers.get("content-type", "").lower()
                if "text/html" in ctype or "application/json" in ctype:
                    return False
                total = 0
                with dest.open("wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        total += len(chunk)
                        if total > max_bytes:
                            return False
                        f.write(chunk)
                return total > 2048
    except Exception:
        return False


async def _download_via_ytdlp(video_url: str, dest: Path) -> bool:
    import asyncio

    def _run() -> bool:
        try:
            import yt_dlp

            ydl_opts = {
                "format": "worst[height>=360][ext=mp4]/best[height<=480][ext=mp4]/best[ext=mp4]/best",
                "outtmpl": str(dest),
                "overwrites": True,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "socket_timeout": 20,
                "max_filesize": 80 * 1024 * 1024,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            return dest.exists() and dest.stat().st_size > 2048
        except Exception as exc:
            logger.debug("yt-dlp download failed for %s: %s", video_url, exc)
            return False

    return await asyncio.to_thread(_run)
