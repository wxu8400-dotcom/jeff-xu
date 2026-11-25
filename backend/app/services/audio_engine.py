from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

VOICE_PRESETS: dict[str, str] = {
    "zh-CN-YunxiNeural": "中文活力男声（种草爆款推荐）",
    "zh-CN-XiaoxiaoNeural": "中文自然女声（亲切推荐）",
    "zh-CN-YunjianNeural": "中文磁性男声（商业大片）",
    "en-US-AndrewNeural": "英文自然男声（出海推荐）",
    "en-US-AvaNeural": "英文爆款女声（TikTok/INS）",
}


def _ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("当前运行环境未检测到 FFmpeg")
    return path


def _ffprobe_duration(media_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 10.0
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
                str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return max(1.0, float(res.stdout.strip()))
    except Exception:
        pass
    return 10.0


async def generate_tts_voiceover(
    text: str,
    *,
    voice: str = "zh-CN-YunxiNeural",
    rate: str = "+5%",
    mock_mode: bool = False,
) -> bytes:
    """Generate crisp, 100% free AI neural voiceover (MP3) via Microsoft edge-tts."""
    clean_text = (text or "").strip()[:1500]
    if not clean_text:
        raise ValueError("口播文案为空，无法生成配音")

    chosen_voice = voice if voice in VOICE_PRESETS else "zh-CN-YunxiNeural"

    if mock_mode:
        return await asyncio.to_thread(_generate_mock_voice_mp3, 3.0)

    try:
        import edge_tts

        communicate = edge_tts.Communicate(clean_text, chosen_voice, rate=rate)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        audio_bytes = b"".join(chunks)
        if len(audio_bytes) < 500:
            raise RuntimeError("AI 配音服务未返回有效音频数据")
        return audio_bytes
    except Exception as exc:
        logger.warning("edge-tts synthesis failed: %s", exc)
        raise RuntimeError(f"免费 AI 配音生成失败：{exc}") from exc


def _generate_mock_voice_mp3(duration_sec: float = 3.0) -> bytes:
    ffmpeg = _ffmpeg_bin()
    with tempfile.TemporaryDirectory(prefix="radar_mocktts_") as tmpdir:
        out_mp3 = Path(tmpdir) / "voice.mp3"
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration_sec:.1f}",
            "-af",
            "volume=0.25",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(out_mp3),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if res.returncode != 0 or not out_mp3.exists():
            raise RuntimeError("Mock 配音生成失败")
        return out_mp3.read_bytes()


def generate_builtin_bgm_mp3(style: str, duration_sec: float) -> bytes:
    """Synthesize a clean, royalty-free commercial background music pad via FFmpeg."""
    ffmpeg = _ffmpeg_bin()
    dur = max(3.0, min(float(duration_sec) + 1.0, 120.0))

    if style == "upbeat_pulse":
        # Modern rhythmic commercial pulse (soft sub + warm harmonic pulse at ~120 BPM)
        expr = (
            "0.22*sin(2*PI*110*t)*(0.5+0.5*sin(2*PI*2*t))"
            "+0.14*sin(2*PI*220*t)*(0.5+0.5*sin(2*PI*4*t))"
            "+0.10*sin(2*PI*330*t)*(0.5+0.5*sin(2*PI*1*t))"
            "+0.08*sin(2*PI*440*t)"
        )
        af = f"lowpass=f=1400,afade=t=in:st=0:d=0.8,afade=t=out:st={max(dur-1.8, 0.5):.2f}:d=1.6"
    else:
        # Luxury minimalist ambient warm chord (Cadd9 soft pad)
        expr = (
            "0.20*sin(2*PI*130.81*t)"
            "+0.15*sin(2*PI*196.00*t)*(0.65+0.35*sin(2*PI*0.25*t))"
            "+0.12*sin(2*PI*246.94*t)*(0.65+0.35*sin(2*PI*0.33*t))"
            "+0.09*sin(2*PI*293.66*t)"
        )
        af = f"lowpass=f=1100,afade=t=in:st=0:d=1.0,afade=t=out:st={max(dur-2.0, 0.5):.2f}:d=1.8"

    with tempfile.TemporaryDirectory(prefix="radar_bgm_") as tmpdir:
        out_mp3 = Path(tmpdir) / "bgm.mp3"
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc={expr}:s=44100:d={dur:.2f}:c=stereo",
            "-af",
            af,
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-threads",
            "1",
            str(out_mp3),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=False)
        if res.returncode != 0 or not out_mp3.exists():
            raise RuntimeError(f"内置 BGM 合成失败：{res.stderr[-200:]}")
        return out_mp3.read_bytes()


def _has_audio_stream(media_path: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return True
    try:
        res = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return bool(res.returncode == 0 and res.stdout.strip())
    except Exception:
        return True


def align_source_audio_to_duration(
    source_audio_bytes: bytes,
    target_duration_sec: float,
) -> bytes:
    """Align the original video's real audio/SFX track to the new stitched video's exact
    duration using pitch-preserving FFmpeg atempo (for 0.55x-1.85x ratios) or clean loop/trim,
    preserving the original video's exact pacing of sound effects and ambience."""
    ffmpeg = _ffmpeg_bin()
    target_dur = max(1.5, float(target_duration_sec))
    with tempfile.TemporaryDirectory(prefix="radar_align_sfx_") as tmpdir:
        tmp = Path(tmpdir)
        in_aud = tmp / "source.mp3"
        out_aud = tmp / "aligned.mp3"
        in_aud.write_bytes(source_audio_bytes)
        src_dur = _ffprobe_duration(in_aud)
        ratio = src_dur / target_dur if target_dur > 0 else 1.0

        fade_out_start = max(target_dur - 1.0, 0.4)
        if 0.55 <= ratio <= 1.85:
            # Smooth pitch-preserving tempo stretch so climax SFX aligns with the new video's arc
            af = (
                f"atempo={ratio:.3f},"
                f"apad=whole_dur={target_dur:.2f},"
                f"atrim=0:{target_dur:.2f},"
                f"afade=t=in:st=0:d=0.25,"
                f"afade=t=out:st={fade_out_start:.2f}:d=0.9,"
                f"alimiter=limit=0.95"
            )
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                str(in_aud),
                "-af",
                af,
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-threads",
                "1",
                str(out_aud),
            ]
        else:
            af = (
                f"atrim=0:{target_dur:.2f},"
                f"afade=t=in:st=0:d=0.25,"
                f"afade=t=out:st={fade_out_start:.2f}:d=0.9,"
                f"alimiter=limit=0.95"
            )
            cmd = [
                ffmpeg,
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(in_aud),
                "-af",
                af,
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-threads",
                "1",
                str(out_aud),
            ]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=False)
        if res.returncode == 0 and out_aud.exists() and out_aud.stat().st_size > 500:
            return out_aud.read_bytes()
        logger.warning("Source audio alignment failed: %s", res.stderr[-250:])
        return source_audio_bytes


async def generate_kling_video_to_audio(
    *,
    video_url: str,
    sound_effect_prompt: str,
    bgm_prompt: str = "",
    asmr_mode: bool = True,
    api_key: str,
    base_url: str,
) -> bytes | None:
    """Call Kling Video-to-Audio (via 302.ai or official Kling gateway) to synthesize
    frame-synchronized Foley SFX directly matching the stitched video. Returns MP4 bytes
    with synced audio, or None if unavailable so callers cleanly fall back to source audio."""
    if not video_url.startswith("http") or not api_key.strip():
        return None

    clean_base = base_url.rstrip("/")
    if clean_base.endswith("/v1"):
        clean_base = clean_base[:-3]
    endpoint = f"{clean_base}/kling/v1/audio/video-to-audio"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "video_url": video_url,
        "sound_effect_prompt": (sound_effect_prompt or "realistic cinematic sound effects")[:200],
        "asmr_mode": bool(asmr_mode),
    }
    if bgm_prompt.strip():
        payload["bgm_prompt"] = bgm_prompt.strip()[:180]

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.info(
                    "Kling video-to-audio unavailable (%s): %s",
                    resp.status_code,
                    resp.text[:220],
                )
                return None
            data = resp.json()
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            task_id = str(inner.get("task_id") or inner.get("id") or "").strip()
            if not task_id:
                return None

            poll_url = f"{endpoint}/{task_id}"
            for _ in range(36):
                await asyncio.sleep(2.5)
                pr = await client.get(poll_url, headers=headers)
                if pr.status_code >= 400:
                    continue
                pdata = pr.json()
                pinner = pdata.get("data") if isinstance(pdata.get("data"), dict) else pdata
                st = str(pinner.get("task_status") or pinner.get("status") or "").lower()
                if st in ("succeed", "succeeded", "completed", "success"):
                    res_obj = pinner.get("task_result") or pinner
                    videos = res_obj.get("videos") if isinstance(res_obj, dict) else None
                    out_url = None
                    if isinstance(videos, list) and videos and isinstance(videos[0], dict):
                        out_url = videos[0].get("url")
                    if not out_url and isinstance(res_obj, dict):
                        out_url = res_obj.get("video_url") or res_obj.get("url")
                    if isinstance(out_url, str) and out_url.startswith("http"):
                        dl = await client.get(out_url, follow_redirects=True, timeout=45.0)
                        if dl.status_code == 200 and len(dl.content) > 5000:
                            return dl.content
                    return None
                if st in ("failed", "error", "canceled"):
                    logger.info("Kling video-to-audio task failed: %s", pinner.get("task_status_msg"))
                    return None
    except Exception as exc:
        logger.info("Kling video-to-audio call skipped due to error: %s", exc)
    return None


def mix_audio_into_mp4(
    video_mp4_bytes: bytes,
    *,
    sfx_track_bytes: bytes | None = None,
    voiceover_bytes: bytes | None = None,
    bgm_bytes: bytes | None = None,
    keep_original_audio: bool = True,
    sfx_volume: float = 0.90,
    bgm_volume: float = 0.20,
) -> bytes:
    """Mux matched SFX track + AI voiceover + ducked BGM + original clip audio into MP4
    WITHOUT re-encoding video."""
    if not sfx_track_bytes and not voiceover_bytes and not bgm_bytes:
        return video_mp4_bytes

    ffmpeg = _ffmpeg_bin()
    with tempfile.TemporaryDirectory(prefix="radar_mix_") as tmpdir:
        tmp = Path(tmpdir)
        in_vid = tmp / "input.mp4"
        out_vid = tmp / "mixed.mp4"
        in_vid.write_bytes(video_mp4_bytes)
        vid_dur = _ffprobe_duration(in_vid)
        vid_has_audio = _has_audio_stream(in_vid)

        cmd: list[str] = [ffmpeg, "-y", "-i", str(in_vid)]
        input_idx = 1
        mix_labels: list[str] = []
        filter_parts: list[str] = []

        if keep_original_audio and vid_has_audio:
            orig_vol = 0.55 if sfx_track_bytes else 0.85
            filter_parts.append(f"[0:a]volume={orig_vol:.2f},atrim=0:{vid_dur:.2f}[a_orig]")
            mix_labels.append("[a_orig]")

        if sfx_track_bytes:
            sfx_path = tmp / "sfx.mp3"
            sfx_path.write_bytes(sfx_track_bytes)
            cmd.extend(["-i", str(sfx_path)])
            fade_start = max(vid_dur - 0.9, 0.4)
            filter_parts.append(
                f"[{input_idx}:a]apad=whole_dur={vid_dur:.2f},atrim=0:{vid_dur:.2f},"
                f"volume={sfx_volume:.2f},afade=t=out:st={fade_start:.2f}:d=0.8[a_sfx]"
            )
            mix_labels.append("[a_sfx]")
            input_idx += 1

        if voiceover_bytes:
            vo_path = tmp / "voiceover.mp3"
            vo_path.write_bytes(voiceover_bytes)
            vo_dur = _ffprobe_duration(vo_path)
            cmd.extend(["-i", str(vo_path)])
            # Gently speed up voiceover (up to 1.25x) if slightly longer than video so it fits cleanly
            atempo = ""
            if vo_dur > vid_dur * 1.03:
                factor = min(1.30, max(1.02, vo_dur / max(vid_dur - 0.3, 1.0)))
                atempo = f"atempo={factor:.2f},"
            filter_parts.append(
                f"[{input_idx}:a]{atempo}volume=1.35,apad=whole_dur={vid_dur:.2f},atrim=0:{vid_dur:.2f}[a_vo]"
            )
            mix_labels.append("[a_vo]")
            input_idx += 1

        if bgm_bytes:
            bgm_path = tmp / "bgm.mp3"
            bgm_path.write_bytes(bgm_bytes)
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
            vol = bgm_volume if (voiceover_bytes or sfx_track_bytes) else max(bgm_volume, 0.45)
            fade_start = max(vid_dur - 1.5, 0.5)
            filter_parts.append(
                f"[{input_idx}:a]atrim=0:{vid_dur:.2f},volume={vol:.2f},afade=t=out:st={fade_start:.2f}:d=1.4[a_bgm]"
            )
            mix_labels.append("[a_bgm]")
            input_idx += 1

        if not mix_labels:
            return video_mp4_bytes

        if len(mix_labels) == 1:
            filter_parts.append(f"{mix_labels[0]}alimiter=limit=0.95[a_out]")
        else:
            joined = "".join(mix_labels)
            filter_parts.append(
                f"{joined}amix=inputs={len(mix_labels)}:duration=first:dropout_transition=2:normalize=0,alimiter=limit=0.95[a_out]"
            )

        cmd.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "0:v:0",
                "-map",
                "[a_out]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-t",
                f"{vid_dur:.2f}",
                "-threads",
                "1",
                "-movflags",
                "+faststart",
                str(out_vid),
            ]
        )

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
        if res.returncode != 0 or not out_vid.exists() or out_vid.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg 混音失败：{res.stderr[-300:]}")
        return out_vid.read_bytes()
