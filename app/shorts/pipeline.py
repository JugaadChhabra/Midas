import logging
import os
from typing import Any

import httpx

from app.config import settings
from app.db import supabase
from app.shorts.youtube_upload import upload_short

log = logging.getLogger("midas.shorts.pipeline")

# Synonyms WayinVideo may emit for the same logical field. The first present
# key wins. Real v2 names are listed first; the rest are defensive fallbacks.
_URL_KEYS   = ("export_link", "source_url", "video_url", "download_url", "url", "mp4_url")
_START_KEYS = ("begin_ms", "start_ms", "start_s", "start_seconds", "start", "start_time")
_END_KEYS   = ("end_ms", "end_s", "end_seconds", "end", "end_time")


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _seconds(d: dict, keys: tuple[str, ...]) -> float | None:
    """Return a start/end time in seconds; *_ms keys are converted from ms."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k] / 1000.0 if k.endswith("_ms") else d[k]
    return None


def normalize_clips(raw: list[dict]) -> list[dict]:
    """Coerce WayinVideo clip dicts to our internal shape."""
    out: list[dict] = []
    for i, c in enumerate(raw, start=1):
        out.append({
            "rank":        (c["idx"] + 1) if isinstance(c.get("idx"), int) else (c.get("rank") or i),
            "title":       c.get("title") or "",
            "description": c.get("desc") or c.get("description") or "",
            "hashtags":    list(c.get("tags") or c.get("hashtags") or []),
            "start_s":     _seconds(c, _START_KEYS),
            "end_s":       _seconds(c, _END_KEYS),
            "source_url":  _first(c, _URL_KEYS),
        })
    return out


def _stream_upload(channel_id: str, clip: dict) -> str:
    """Stream WayinVideo's mp4 directly into a YouTube resumable upload."""
    with httpx.stream("GET", clip["source_url"], timeout=None, follow_redirects=True) as r:
        r.raise_for_status()
        # Wrap the chunk iterator in a file-like object that .read() can consume.
        reader = _IterReader(r.iter_bytes())
        return upload_short(channel_id, reader, clip["title"], clip["description"], clip["hashtags"])


def _download_then_upload(channel_id: str, clip: dict) -> tuple[str, str]:
    """Download to SHORTS_CACHE_DIR/<job_id>/<rank>.mp4, then upload from disk."""
    cache_dir = os.path.join(settings.SHORTS_CACHE_DIR, str(clip.get("job_id", "_")))
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, f"{clip['rank']}.mp4")
    with httpx.stream("GET", clip["source_url"], timeout=None, follow_redirects=True) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    vid = upload_short(channel_id, local_path, clip["title"], clip["description"], clip["hashtags"])
    return vid, local_path


def _upload_one_clip(channel_id: str, clip: dict) -> dict:
    """Try streaming upload first; on failure, download to disk and retry.

    Returns a patch dict for the shorts_clips row. The local_path is preserved
    even on final failure so the operator can manually upload later.
    """
    # 1) Streaming attempt.
    try:
        vid = _stream_upload(channel_id, clip)
        return {"yt_video_id": vid, "upload_status": "UPLOADED", "upload_error": None, "local_path": None}
    except Exception as e:
        log.warning("Streaming upload failed for clip rank=%s: %s — falling back to disk", clip.get("rank"), e)

    # 2) Disk fallback.
    try:
        vid, local_path = _download_then_upload(channel_id, clip)
        return {"yt_video_id": vid, "upload_status": "UPLOADED", "upload_error": None, "local_path": local_path}
    except Exception as e:
        log.error("Disk-fallback upload failed for clip rank=%s: %s", clip.get("rank"), e)
        # Try to surface the local_path even if upload itself blew up.
        local_path = os.path.join(
            settings.SHORTS_CACHE_DIR, str(clip.get("job_id", "_")), f"{clip['rank']}.mp4"
        )
        return {
            "upload_status": "FAILED",
            "upload_error":  f"{type(e).__name__}: {e}"[:1000],
            "local_path":    local_path if os.path.exists(local_path) else None,
        }


def process_job_clips(job_id: int) -> None:
    """Upload every clip on this job, sequentially, in rank order."""
    sb = supabase()
    job = sb.table("shorts_jobs").select("*").eq("id", job_id).single().execute().data
    if not job:
        log.error("process_job_clips: job %s not found", job_id)
        return
    channel_id = job["channel_id"]

    clips = (
        sb.table("shorts_clips").select("*").eq("job_id", job_id)
        .order("rank").execute().data or []
    )
    sb.table("shorts_jobs").update({"status": "UPLOADING"}).eq("id", job_id).execute()

    for clip in clips:
        sb.table("shorts_clips").update({"upload_status": "UPLOADING"}).eq("id", clip["id"]).execute()
        clip_with_job = {**clip, "job_id": job_id}
        patch_dict = _upload_one_clip(channel_id, clip_with_job)
        sb.table("shorts_clips").update(patch_dict).eq("id", clip["id"]).execute()

    final_clips = sb.table("shorts_clips").select("upload_status").eq("job_id", job_id).execute().data or []
    all_ok = all(c["upload_status"] == "UPLOADED" for c in final_clips)
    sb.table("shorts_jobs").update({
        "status": "DONE" if all_ok else "FAILED",
        "error_message": None if all_ok else "One or more clips failed to upload",
    }).eq("id", job_id).execute()


class _IterReader:
    """Adapt an iterator of bytes chunks to a `.read(n)`-style file-like object.

    googleapiclient's MediaIoBaseUpload calls read(chunksize) repeatedly; this
    buffers iter_bytes() output and serves it out in those chunks.
    """
    def __init__(self, it):
        self._it = it
        self._buf = bytearray()
        self._eof = False

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            # Drain everything.
            while not self._eof:
                self._pull()
            out = bytes(self._buf)
            self._buf.clear()
            return out
        while len(self._buf) < n and not self._eof:
            self._pull()
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _pull(self):
        try:
            self._buf += next(self._it)
        except StopIteration:
            self._eof = True
