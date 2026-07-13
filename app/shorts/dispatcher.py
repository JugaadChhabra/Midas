"""Single owner of shorts-job launching. Registered as an APScheduler interval
job (max_instances=1) in app/main.py. Each tick reaps finished worker
subprocesses and launches queued (CREATED) jobs up to the concurrency cap.

Because there is exactly one dispatcher, `_running` (in-memory) is the source
of truth for what has been launched — no DB-level atomic claim is needed.
"""
from __future__ import annotations

import logging
import subprocess
import sys

from app.config import settings
from app.db import supabase

log = logging.getLogger("midas.shorts.dispatcher")

_TERMINAL = ("DONE", "FAILED")
# job_id -> Popen for workers this dispatcher launched
_running: dict[int, subprocess.Popen] = {}


def _spawn(job_id: int) -> subprocess.Popen:
    """Launch an isolated worker. cwd/env inherited from the server process
    (started at repo root), so `-m app.shorts.worker` resolves."""
    return subprocess.Popen([sys.executable, "-m", "app.shorts.worker", str(job_id)])


def _next_created_id(sb) -> int | None:
    """Oldest CREATED job not already launched by this dispatcher, or None."""
    running_ids = list(_running.keys())
    q = (sb.table("shorts_jobs").select("id")
         .eq("status", "CREATED").order("id", desc=False))
    if running_ids:
        q = q.not_.in_("id", running_ids)
    rows = (q.limit(1).execute().data) or []
    return rows[0]["id"] if rows else None


def dispatch_tick() -> None:
    sb = supabase()

    # 1. Reap finished workers.
    for job_id, proc in list(_running.items()):
        if proc.poll() is None:
            continue  # still running
        _running.pop(job_id, None)
        job = (sb.table("shorts_jobs").select("status")
               .eq("id", job_id).single().execute().data) or {}
        if job.get("status") not in _TERMINAL:
            sb.table("shorts_jobs").update({
                "status": "FAILED",
                "error_message": f"worker exited unexpectedly (rc={proc.returncode})",
            }).eq("id", job_id).execute()
            log.warning("shorts job %s: worker exited rc=%s (status=%s) -> FAILED",
                        job_id, proc.returncode, job.get("status"))

    # 2. Fill free slots with queued work.
    cap = settings.SHORTS_MAX_CONCURRENT_JOBS
    while len(_running) < cap:
        next_id = _next_created_id(sb)
        if next_id is None:
            break
        _running[next_id] = _spawn(next_id)
        log.info("shorts dispatch: launched worker for job %s (%d/%d slots)",
                 next_id, len(_running), cap)
