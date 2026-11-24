from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Uniform vertical 9:16 spec tuned for Render 512MB RAM (-threads 1 -preset ultrafast)
TARGET_W = 720
TARGET_H = 1280
TARGET_FPS = 25


def _ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("当前运行环境未检测到 FFmpeg，无法执行视频合成")
    return path


def _ffprobe_duration(video_path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        res = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return round(float(res.stdout.strip()), 2)
    except Exception:
        return None
    return None


def _has_audio_stream(video_path: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False
    try:
        res = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return res.returncode == 0 and "audio" in (res.stdout or "")
    except Exception:
        return False


def image_to_motion_clip(
    image_bytes: bytes,
    *,
    duration_sec: float = 3.5,
    zoom_direction: str = "in",
) -> bytes:
    """Convert a still storyboard image into a smooth 9:16 vertical Ken Burns MP4 clip."""
    ffmpeg = _ffmpeg_bin()
    dur = max(1.5, min(float(duration_sec), 10.0))
    total_frames = max(int(round(dur * TARGET_FPS)), 25)

    with tempfile.TemporaryDirectory(prefix="radar_imgclip_") as tmpdir:
        in_img = Path(tmpdir) / "frame.jpg"
        out_mp4 = Path(tmpdir) / "clip.mp4"
        in_img.write_bytes(image_bytes)

        if zoom_direction == "out":
            zoom_expr = f"max(1.0,1.12-0.12*(on/{total_frames}))"
        else:
            zoom_expr = f"min(1.12,1.0+0.12*(on/{total_frames}))"

        vf = (
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={total_frames}:s={TARGET_W}x{TARGET_H}:fps={TARGET_FPS},"
            f"setsar=1,format=yuv420p"
        )

        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(in_img),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            vf,
            "-t",
            f"{dur:.2f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "27",
            "-maxrate",
            "2400k",
            "-bufsize",
            "4800k",
            "-threads",
            "1",
            "-r",
            str(TARGET_FPS),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
        if res.returncode != 0 or not out_mp4.exists() or out_mp4.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg 图片转动态镜头失败：{res.stderr[-300:]}")
        return out_mp4.read_bytes()


def normalize_video_clip_to_path(src_path: Path, dst_path: Path) -> float:
    """Normalize any video (Kling MP4 or user smartphone MOV/MP4) to uniform 9:16 H.264/AAC."""
    ffmpeg = _ffmpeg_bin()
    has_audio = _has_audio_stream(src_path)

    vf = (
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={TARGET_FPS},setsar=1,format=yuv420p"
    )

    if has_audio:
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(src_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "27",
            "-maxrate",
            "2400k",
            "-bufsize",
            "4800k",
            "-threads",
            "1",
            "-r",
            str(TARGET_FPS),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(dst_path),
        ]
    else:
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(src_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "27",
            "-maxrate",
            "2400k",
            "-bufsize",
            "4800k",
            "-threads",
            "1",
            "-r",
            str(TARGET_FPS),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            "-movflags",
            "+faststart",
            str(dst_path),
        ]

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if res.returncode != 0 or not dst_path.exists() or dst_path.stat().st_size == 0:
        raise RuntimeError(f"FFmpeg 视频规范化失败：{res.stderr[-300:]}")

    return _ffprobe_duration(dst_path) or 5.0


def stitch_media_items_to_mp4(
    items: list[tuple[str, bytes, float]],
) -> tuple[bytes, float]:
    """Stitch an ordered list of ('video' | 'image', data_bytes, duration_hint) into one 9:16 MP4.

    Sequential normalization + stream-copy concat keeps peak RAM safely under Render's 512MB cap.
    """
    if not items:
        raise ValueError("没有可用于合成成片的素材片段")
    ffmpeg = _ffmpeg_bin()

    with tempfile.TemporaryDirectory(prefix="radar_stitch_") as tmpdir:
        tmp = Path(tmpdir)
        norm_paths: list[Path] = []
        total_dur = 0.0

        for idx, (kind, data, dur_hint) in enumerate(items):
            norm_out = tmp / f"part_{idx:03d}.mp4"
            if kind == "image":
                clip_bytes = image_to_motion_clip(
                    data,
                    duration_sec=dur_hint or 3.5,
                    zoom_direction="in" if idx % 2 == 0 else "out",
                )
                norm_out.write_bytes(clip_bytes)
                total_dur += _ffprobe_duration(norm_out) or (dur_hint or 3.5)
            else:
                raw_in = tmp / f"raw_{idx:03d}.mp4"
                raw_in.write_bytes(data)
                clip_dur = normalize_video_clip_to_path(raw_in, norm_out)
                total_dur += clip_dur
                try:
                    os.unlink(raw_in)
                except OSError:
                    pass
            norm_paths.append(norm_out)

        if len(norm_paths) == 1:
            return norm_paths[0].read_bytes(), round(total_dur, 2)

        concat_txt = tmp / "concat.txt"
        lines = [f"file '{p.as_posix()}'" for p in norm_paths]
        concat_txt.write_text("\n".join(lines), encoding="utf-8")

        final_mp4 = tmp / "final.mp4"
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(final_mp4),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
        if res.returncode != 0 or not final_mp4.exists() or final_mp4.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg 拼接成片失败：{res.stderr[-300:]}")

        final_dur = _ffprobe_duration(final_mp4) or total_dur
        return final_mp4.read_bytes(), round(final_dur, 2)
