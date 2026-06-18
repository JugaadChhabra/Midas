import logging
from datetime import datetime, timezone, timedelta

from app.db import supabase
from app.shorts.wayin_client import get_status, WayinVideoError
from app.shorts.pipeline import normalize_clips, process_job_clips

log = logging.getLogger("midas.shorts.poller")

_POLL_INTERVAL_SECONDS = 30
# Hard ceiling so a runaway WayinVideo job doesn't keep scheduling forever.
_MAX_AGE_HOURS = 4


def schedule_poll(job_id: int, delay_seconds: int = 0) -> None:
    # Lazy import: app.main imports this module → can't import main at module load.
    from app.main import scheduler
    run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    scheduler.add_job(
        poll_job,
        "date",
        run_date=run_at,
        args=[job_id],
        id=f"shorts_poll_{job_id}_{int(run_at.timestamp())}",
        misfire_grace_time=120,
    )


def poll_job(job_id: int) -> None:
    sb = supabase()
    job = sb.table("shorts_jobs").select("*").eq("id", job_id).single().execute().data
    if not job:
        log.error("poll_job: job %s not found", job_id)
        return

    if job["status"] in ("DONE", "FAILED"):
        return

    age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
    if age_hours > _MAX_AGE_HOURS:
        sb.table("shorts_jobs").update({
            "status": "FAILED",
            "error_message": f"Timed out after {_MAX_AGE_HOURS}h",
        }).eq("id", job_id).execute()
        return

    project_id = job.get("wayinvideo_project_id")
    if not project_id:
        log.error("poll_job: job %s has no wayinvideo_project_id", job_id)
        return

    try:
        data = get_status(project_id)
    except WayinVideoError as e:
        log.warning("WayinVideo status error for job %s: %s — retry in %ds", job_id, e, _POLL_INTERVAL_SECONDS)
        schedule_poll(job_id, _POLL_INTERVAL_SECONDS)
        return

    status = data.get("status", "ONGOING")
    sb.table("shorts_jobs").update({"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", job_id).execute()

    if status in ("CREATED", "QUEUED", "ONGOING"):
        schedule_poll(job_id, _POLL_INTERVAL_SECONDS)
        return

    if status == "FAILED":
        sb.table("shorts_jobs").update({"error_message": data.get("error_message", "unknown")}).eq("id", job_id).execute()
        return

    if status == "SUCCEEDED":
        raw_clips = data.get("clips") or data.get("data", {}).get("clips") or []
        normalized = normalize_clips(raw_clips)
        if not normalized:
            sb.table("shorts_jobs").update({
                "status": "FAILED",
                "error_message": "WayinVideo returned 0 clips",
            }).eq("id", job_id).execute()
            return
        rows = [{"job_id": job_id, **c} for c in normalized]
        sb.table("shorts_clips").upsert(rows, on_conflict="job_id,rank").execute()
        process_job_clips(job_id)
        return

    log.warning("Unknown WayinVideo status %r for job %s", status, job_id)
    schedule_poll(job_id, _POLL_INTERVAL_SECONDS)
