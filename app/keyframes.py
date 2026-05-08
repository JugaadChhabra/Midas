"""Extract keyframes from YouTube videos using yt-dlp + ffmpeg.

Frames are uploaded to Supabase Storage and returned as signed URLs that the
audit LLM can read directly. We do NOT analyze frames in a separate vision
pass — they go straight into the audit call as image attachments alongside
the thumbnail. The audit model reasons about visual moments inline.

yt-dlp stream URLs expire (~6h), so extraction must happen in the same call
that resolved the URL. This module enforces that by keeping the URL helper
private.
"""
import logging
import os
import shutil
import subprocess
from pathlib import Path

import yt_dlp

from app.config import settings
from app.db import supabase

log = logging.getLogger("midas.keyframes")


def _get_stream_url(video_id: str) -> str | None:
    """Resolve a direct stream URL via yt-dlp. Lowest 480p we can find."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[height<=480]/best",
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False,
            )
            return info.get("url")
    except Exception as e:
        log.warning("yt-dlp failed for %s: %s", video_id, e)
        return None


def _probe_duration(stream_url: str) -> float | None:
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                stream_url,
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(r.stdout.strip())
    except Exception as e:
        log.warning("ffprobe failed: %s", e)
        return None


def _smart_timestamps(duration: float, n: int) -> list[float]:
    """Spread n timestamps across the video, skipping intro/outro padding."""
    if n <= 0:
        return []
    if duration < 30:
        return [duration * i / (n + 1) for i in range(1, n + 1)]

    start = 5.0
    end = max(duration - 5.0, start + 1)
    if n == 1:
        return [(start + end) / 2]

    # First near the hook (5s in or 5% in, whichever is later up to 8s),
    # last near outro, rest evenly spaced.
    first = max(start, min(8.0, duration * 0.05))
    last = end
    if n == 2:
        return [first, last]

    middle = []
    step = (last - first) / (n - 1)
    for i in range(1, n - 1):
        middle.append(first + step * i)
    return sorted({first, *middle, last})


def _extract_frame(stream_url: str, ts: float, out_path: Path) -> bool:
    """One frame at `ts` via ffmpeg. -ss before -i is fast keyframe-snap."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-ss", str(ts),
                "-i", stream_url,
                "-vframes", "1",
                "-vf", "scale=1280:-1",
                "-q:v", "2",
                str(out_path),
                "-y",
            ],
            capture_output=True,
            timeout=settings.KEYFRAME_FFMPEG_TIMEOUT,
            check=True,
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        log.warning("ffmpeg failed at ts=%.1f: %s", ts, e)
        return False


def extract_keyframes(video_id: str) -> list[dict]:
    """Resolve, extract, upload. Returns rows with signed URLs for the audit LLM.

    Each row: {"storage_path": str, "timestamp": float, "url": str}.
    Cleans up local temp files. Returns [] on any catastrophic failure
    (audit code degrades gracefully without keyframes).
    """
    stream_url = _get_stream_url(video_id)
    if not stream_url:
        return []

    duration = _probe_duration(stream_url)
    if not duration or duration <= 0:
        return []

    timestamps = _smart_timestamps(duration, settings.KEYFRAME_MAX_FRAMES)
    out_dir = Path(settings.KEYFRAMES_LOCAL_DIR) / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    local: list[tuple[Path, float]] = []
    for ts in timestamps:
        path = out_dir / f"{int(ts):05d}.jpg"
        if _extract_frame(stream_url, ts, path):
            local.append((path, ts))

    uploaded: list[dict] = []
    sb = supabase()
    bucket = sb.storage.from_("keyframes")
    for path, ts in local:
        try:
            with open(path, "rb") as f:
                content = f.read()
            storage_path = f"{video_id}/{path.name}"
            try:
                bucket.upload(
                    path=storage_path,
                    file=content,
                    file_options={"content-type": "image/jpeg", "upsert": "true"},
                )
            except Exception as e:
                # Treat already-exists as ok — same path/ts collision means
                # we re-extracted the same frame.
                if "exist" not in str(e).lower():
                    raise
            signed = bucket.create_signed_url(path=storage_path, expires_in=3600)
            url = signed.get("signedURL") or signed.get("signed_url")
            if not url:
                continue
            sb.table("video_keyframes").insert({
                "video_id": video_id,
                "timestamp_seconds": ts,
                "storage_path": storage_path,
            }).execute()
            uploaded.append({"storage_path": storage_path, "timestamp": ts, "url": url})
        except Exception as e:
            log.warning("keyframe upload failed for %s ts=%.1f: %s", video_id, ts, e)

    # Clean up local temp dir entirely.
    try:
        shutil.rmtree(out_dir, ignore_errors=True)
    except Exception:
        pass

    log.info("keyframes for %s: extracted=%d uploaded=%d", video_id, len(local), len(uploaded))
    return uploaded
