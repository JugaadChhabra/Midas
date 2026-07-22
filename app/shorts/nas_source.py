"""Scan a NAS language folder and enqueue one shorts_job per uncut video.

Shared by the manual POST /shorts/cut endpoint and (at deploy time) the
autopilot shorts action. Additive — YouTube-URL jobs are unaffected."""
from __future__ import annotations

import logging
from collections import defaultdict

from app.config import settings
from app.db import supabase
from app.services.nas_service import nas_service

log = logging.getLogger("midas.shorts.nas_source")

# A job a worker has queued or is actively running (mirrors runner.WORKING_STATUSES).
WORKING_STATUSES = ("CREATED", "DOWNLOADING", "ANALYSING", "RENDERING", "UPLOADING")
# A source whose cut keeps failing is left in place (not moved), so without a cap
# it would be re-enqueued forever. Same value/rationale as app/autopilot.py.
MAX_SHORTS_RETRY_ATTEMPTS = 3


def list_source_languages() -> list[str]:
    """Language subfolders under the source root."""
    # nas_service exposes files, not dirs; list dirs directly per mode.
    if nas_service.mode == "local":
        base = nas_service._local(settings.NAS_SOURCE_ROOT_PATH)
        if not base.is_dir():
            return []
        return sorted([e.name for e in base.iterdir() if e.is_dir()])
    import smbclient
    nas_service._connect()
    base = nas_service._remote(settings.NAS_SOURCE_ROOT_PATH)
    if not smbclient.path.exists(base):
        return []
    return sorted([e.name for e in smbclient.scandir(base) if e.is_dir()])


def uncut_source_paths(language: str) -> list[str]:
    """`<LANG>/<file>` paths with no in-flight job and under the FAILED cap."""
    files = nas_service.list_video_files(f"{settings.NAS_SOURCE_ROOT_PATH}/{language}")
    paths = [f"{language}/{name}" for name in files]
    if not paths:
        return []
    rows = (supabase().table("shorts_jobs")
            .select("source_nas_path,status")
            .in_("source_nas_path", paths).execute().data) or []
    in_flight: set[str] = set()
    failed: dict[str, int] = defaultdict(int)
    for r in rows:
        p = r.get("source_nas_path")
        status = (r.get("status") or "").upper()
        if not p:
            continue
        if status in WORKING_STATUSES:
            in_flight.add(p)
        elif status == "FAILED":
            failed[p] += 1
    return [p for p in paths
            if p not in in_flight and failed[p] < MAX_SHORTS_RETRY_ATTEMPTS]


def uncut_count(language: str) -> int:
    return len(uncut_source_paths(language))


def enqueue_language_jobs(language: str, *, channel_id: str | None = None,
                          autopilot: bool = False, limit: int | None = None,
                          cut_mode: str = "highlights",
                          camera_motion: str = "calm") -> int:
    if language not in list_source_languages():
        raise ValueError(f"Unknown NAS language folder: {language!r}")
    todo = uncut_source_paths(language)
    if limit is not None:
        todo = todo[:limit]
    for path in todo:
        supabase().table("shorts_jobs").insert({
            "channel_id":          channel_id,
            "language":            language,
            "source_nas_path":     path,
            "cut_mode":            cut_mode,
            "camera_motion":       camera_motion,
            "autopilot_generated": autopilot,
            "status":              "CREATED",
        }).execute()
    log.info("NAS enqueue: %d job(s) for language %s", len(todo), language)
    return len(todo)
