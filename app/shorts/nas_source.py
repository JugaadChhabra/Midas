"""Scan a NAS language folder and enqueue one shorts_job per uncut video.

Shared by the manual POST /shorts/cut endpoint and (at deploy time) the
autopilot shorts action. Additive — YouTube-URL jobs are unaffected."""
from __future__ import annotations

import logging
from collections import defaultdict

from app.config import settings
from app.db import supabase
from app.services.nas_service import nas_service
from app.shorts.status import CREATED, FAILED, WORKING_STATUSES

log = logging.getLogger("midas.shorts.nas_source")

# WORKING_STATUSES is owned by app.shorts.status; re-exported here for callers.
# A source whose cut keeps failing is left in place (not moved), so without a cap
# it would be re-enqueued forever. Same value/rationale as app/autopilot.py.
MAX_SHORTS_RETRY_ATTEMPTS = 3

# Not every FAILED row means the *source* is bad. Infrastructure failures — a
# mid-job redeploy (reap_stuck_jobs), a NAS transport hiccup, or the (now-fixed)
# split-brain stale-worker bug — say nothing about whether the file is cuttable,
# yet each one used to burn a retry. Three such blips permanently blacklisted a
# perfectly good source (the incident that silenced whole channels). These
# markers classify a FAILED row as transient so it does NOT count toward the cap;
# the file is retried on the next tick instead of being poisoned forever. Matched
# case-insensitively as a substring of shorts_jobs.error_message.
TRANSIENT_FAILURE_MARKERS = (
    "server restarted mid-job",         # reap_stuck_jobs on redeploy (runner.py)
    'unsupported url scheme: "nas"',    # legacy split-brain stale worker (fixed)
    "nas transport:",                   # NAS copy/move I/O failure (runner.py)
)


def _is_transient_failure(error_message: str | None) -> bool:
    """True when a FAILED row reflects infrastructure noise, not a bad source."""
    msg = (error_message or "").lower()
    return any(marker in msg for marker in TRANSIENT_FAILURE_MARKERS)


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
            .select("source_nas_path,status,error_message")
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
        elif status == FAILED and not _is_transient_failure(r.get("error_message")):
            # Transient/infra failures don't count toward the cap (see markers above)
            # so a NAS blip or redeploy never permanently blacklists a good file.
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
            # shorts_jobs.source_url is NOT NULL. NAS jobs have no YouTube URL,
            # so store a self-describing nas:// URI: it satisfies the constraint,
            # is ignored by the runner (which branches on source_nas_path), and
            # renders sanely in the legacy job-list UI.
            "source_url":          f"nas://{path}",
            "cut_mode":            cut_mode,
            "camera_motion":       camera_motion,
            "autopilot_generated": autopilot,
            "status":              CREATED,
        }).execute()
    log.info("NAS enqueue: %d job(s) for language %s", len(todo), language)
    return len(todo)
