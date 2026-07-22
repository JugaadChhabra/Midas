"""Local shorts-cutter job orchestration. Replaces the WayinVideo poller.

Jobs run in a plain daemon thread (minutes of CPU: Whisper + YOLO + ffmpeg).
All state lives in the shorts_jobs/shorts_clips tables; the UI polls those.
The cutter itself is imported lazily so app startup never pays the torch tax
and a container without requirements-ml.txt fails with a clear message only
when a job is actually created.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from app.config import settings
from app.db import supabase
from app.services.nas_service import nas_service
from app.shorts.cutter.util import safe_name
from app.shorts.youtube_upload import upload_short

log = logging.getLogger("midas.shorts.runner")

WORKING_STATUSES = ("CREATED", "DOWNLOADING", "ANALYSING", "RENDERING", "UPLOADING")

# The subset of WORKING_STATUSES a worker has actually started (excludes the
# queued CREATED state). Only these are reaped on restart; CREATED jobs survive
# to be re-dispatched.
IN_PROGRESS_STATUSES = tuple(s for s in WORKING_STATUSES if s != "CREATED")


def _fetch_video(url: str, dest_dir: Path):
    from app.shorts.cutter.download import fetch_video
    return fetch_video(url, dest_dir)


def _cut_video(*args, **kwargs):
    from app.shorts.cutter.pipeline import cut_video
    return cut_video(*args, **kwargs)


def _set_job(job_id: int, **fields) -> None:
    supabase().table("shorts_jobs").update(fields).eq("id", job_id).execute()


def active_job_count() -> int:
    """Number of shorts jobs in flight (queued CREATED + actively running)."""
    rows = (supabase().table("shorts_jobs").select("id")
            .in_("status", list(WORKING_STATUSES)).execute().data) or []
    return len(rows)


def run_shorts_job(job_id: int) -> None:
    sb = supabase()
    job = sb.table("shorts_jobs").select("*").eq("id", job_id).single().execute().data
    if not job:
        log.error("run_shorts_job: job %s not found", job_id)
        return
    if job.get("source_nas_path"):
        return _run_nas_shorts_job(job_id, job)
    job_dir = Path(settings.SHORTS_CACHE_DIR) / str(job_id)
    source = None
    try:
        _set_job(job_id, status="DOWNLOADING", progress=5, progress_label="downloading video")
        source, title = _fetch_video(job["source_url"], job_dir / "src")

        def progress(stage: str, percent: int) -> None:
            status = "RENDERING" if "render" in stage else "ANALYSING"
            _set_job(job_id, status=status, progress=percent, progress_label=stage)

        result = _cut_video(
            source, job_dir, preferred_name=title,
            cut_mode=job.get("cut_mode") or "highlights",
            camera_motion=job.get("camera_motion") or "calm", progress=progress,
        )

        clips = result["clips"]
        cap = job.get("upload_cap")
        # PASS-graded clips first, then by rank. With a cap, upload only the first N; hold the rest.
        ordered = sorted(clips, key=lambda c: (0 if c.get("verdict") == "PASS" else 1, c["rank"]))
        hold_ranks = set() if cap is None else {c["rank"] for c in ordered[cap:]}

        n_upload = len(clips) - len(hold_ranks)
        _set_job(job_id, status="UPLOADING", progress=95,
                 progress_label=f"uploading {n_upload} of {len(clips)} clips to YouTube")
        all_ok = True
        for clip in ordered:
            clip_title = f"{title.replace('_', ' ')} — Part {clip['rank']}"[:100]
            held = clip["rank"] in hold_ranks
            row = sb.table("shorts_clips").insert({
                "job_id": job_id, "rank": clip["rank"], "title": clip_title,
                "description": "", "hashtags": ["shorts"],
                "start_s": clip["start_s"], "end_s": clip["end_s"],
                "local_path": clip["path"],
                "upload_status": "PENDING" if held else "UPLOADING",
            }).execute().data[0]
            if held:
                continue
            try:
                video_id = upload_short(job["channel_id"], clip["path"],
                                        clip_title, "", ["shorts"])
                sb.table("shorts_clips").update(
                    {"upload_status": "UPLOADED", "yt_video_id": video_id}
                ).eq("id", row["id"]).execute()
            except Exception as exc:
                all_ok = False
                log.exception("Job %s: upload failed for clip rank=%s", job_id, clip["rank"])
                sb.table("shorts_clips").update(
                    {"upload_status": "FAILED",
                     "upload_error": f"{type(exc).__name__}: {exc}"[:1000]}
                ).eq("id", row["id"]).execute()

        held_note = f" ({len(hold_ranks)} held for review)" if hold_ranks else ""
        _set_job(job_id, status="DONE" if all_ok else "FAILED", progress=100,
                 progress_label="done",
                 error_message=None if all_ok else "One or more clips failed to upload")
        _notify_macos("Midas Shorts",
                      f"Job {job_id}: {len(clips)} clips cut, "
                      f"{n_upload} uploaded{held_note}"
                      + ("" if all_ok else " — some uploads FAILED"))
    except Exception as exc:
        log.exception("Job %s failed", job_id)
        _set_job(job_id, status="FAILED", error_message=str(exc)[:1000])
        _notify_macos("Midas Shorts", f"Job {job_id} failed: {exc}"[:120])
    finally:
        shutil.rmtree(job_dir / "src", ignore_errors=True)
        shutil.rmtree(job_dir / "tmp", ignore_errors=True)


def _run_nas_shorts_job(job_id: int, job: dict) -> None:
    """Cut a NAS-sourced video: copy from NAS, cut, push clips + move the source
    into COMPLETED/<language>/. No YouTube upload."""
    sb = supabase()
    job_dir = Path(settings.SHORTS_CACHE_DIR) / str(job_id)
    language = job["language"]
    src_rel = job["source_nas_path"]                 # e.g. "HINDI/song.mp4"
    filename = src_rel.rsplit("/", 1)[-1]
    dest_dir = f"{settings.NAS_DESTINATION_ROOT_PATH}/{language}"
    try:
        _set_job(job_id, status="DOWNLOADING", progress=5, progress_label="fetching from NAS")
        local_src = nas_service.copy_to_local(
            f"{settings.NAS_SOURCE_ROOT_PATH}/{src_rel}", job_dir / "src" / filename)
        title = safe_name(Path(filename).stem)

        def progress(stage: str, percent: int) -> None:
            status = "RENDERING" if "render" in stage else "ANALYSING"
            _set_job(job_id, status=status, progress=percent, progress_label=stage)

        result = _cut_video(
            local_src, job_dir, preferred_name=title,
            cut_mode=job.get("cut_mode") or "highlights",
            camera_motion=job.get("camera_motion") or "calm", progress=progress,
        )
        clips = result["clips"]

        _set_job(job_id, status="UPLOADING", progress=95,
                 progress_label=f"saving {len(clips)} clips to NAS")
        for clip in clips:
            clip_name = Path(clip["path"]).name
            nas_path = f"{dest_dir}/{clip_name}"
            nas_service.copy_from_local(Path(clip["path"]), nas_path)
            sb.table("shorts_clips").insert({
                "job_id": job_id, "rank": clip["rank"],
                "title": f"{title.replace('_', ' ')} — Part {clip['rank']}"[:100],
                "description": "", "hashtags": ["shorts"],
                "start_s": clip["start_s"], "end_s": clip["end_s"],
                "local_path": clip["path"], "nas_path": nas_path,
                "upload_status": "SAVED",
            }).execute()

        # Move the consumed source out of RHYMES so it is never re-cut.
        nas_service.move(f"{settings.NAS_SOURCE_ROOT_PATH}/{src_rel}",
                         f"{dest_dir}/{filename}")
        _set_job(job_id, status="DONE", progress=100, progress_label="done",
                 error_message=None)
        _notify_macos("Midas Shorts", f"Job {job_id}: {len(clips)} clips cut from {filename}")
    except Exception as exc:
        log.exception("NAS job %s failed", job_id)
        _set_job(job_id, status="FAILED", error_message=str(exc)[:1000])
        _notify_macos("Midas Shorts", f"Job {job_id} failed: {exc}"[:120])
    finally:
        shutil.rmtree(job_dir / "src", ignore_errors=True)
        shutil.rmtree(job_dir / "tmp", ignore_errors=True)


def reap_stuck_jobs() -> int:
    """Fail jobs a worker had started but a server restart abandoned.

    Scans IN_PROGRESS_STATUSES (never CREATED — those stay queued and get
    re-dispatched). Any still-alive worker process for a stuck job is killed
    first so it can't keep writing to the row or hog ffmpeg/GPU.
    """
    sb = supabase()
    stuck = (sb.table("shorts_jobs").select("id,worker_pid")
             .in_("status", list(IN_PROGRESS_STATUSES)).execute().data) or []
    for row in stuck:
        _kill_pid_if_alive(row.get("worker_pid"))
        sb.table("shorts_jobs").update({
            "status": "FAILED", "error_message": "server restarted mid-job",
        }).eq("id", row["id"]).execute()
    if stuck:
        log.warning("Reaped %d stuck shorts job(s) on startup", len(stuck))
    return len(stuck)


def _kill_pid_if_alive(pid: int | None) -> None:
    """Best-effort terminate a possibly-orphaned worker process. Cross-platform."""
    if not pid:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass  # already gone / not ours — nothing to do


def _notify_macos(title: str, body: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{body}" with title "{title}"'],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:
        pass  # notification is best-effort
