from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


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


def extract_keyframes_from_bytes(
    video_bytes: bytes, max_frames: int = 10, max_width: int = 960
) -> list[bytes]:
    fd, tmp_name = tempfile.mkstemp(prefix="radar_vb_", suffix=".mp4")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_bytes(video_bytes)
        return extract_keyframes_from_path(
            tmp_path, max_frames=max_frames, max_width=max_width
        )
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def extract_filmstrip_previews(video_bytes: bytes, max_frames: int = 6) -> list[str]:
    """Extract compact base64 JPEG preview strip starting at 0.15s so the UI displays
    the genuine original video frames right above the prompt."""
    import base64
    import io
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
