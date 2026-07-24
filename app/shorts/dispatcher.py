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
from app.shorts.status import CREATED, DOWNLOADING, FAILED, TERMINAL_STATUSES

log = logging.getLogger("midas.shorts.dispatcher")

_TERMINAL = TERMINAL_STATUSES
# job_id -> Popen for workers this dispatcher launched
_running: dict[int, subprocess.Popen] = {}


def _spawn(job_id: int) -> subprocess.Popen:
    """Launch an isolated worker. cwd/env inherited from the server process
    (started at repo root), so `-m app.shorts.worker` resolves."""
    return subprocess.Popen([sys.executable, "-m", "app.shorts.worker", str(job_id)])


def _claim_next(sb) -> int | None:
    """Atomically claim the oldest CREATED job this dispatcher hasn't launched.

    The claim is a conditional flip CREATED -> DOWNLOADING that only lands while
    the row is still CREATED. If another dispatcher (e.g. a not-yet-retired
    instance during a rolling redeploy) grabbed it first, the update returns no
    row and we move to the next job. This closes the double-spawn race that the
    in-memory ``_running`` set alone cannot cover once more than one dispatcher
    is briefly live — the failure mode that let a stale worker fail NAS jobs
    it had raced a healthy worker for.
    """
    running_ids = list(_running.keys())
    while True:
        q = (sb.table("shorts_jobs").select("id")
             .eq("status", CREATED).order("id", desc=False))
        if running_ids:
            q = q.not_.in_("id", running_ids)
        rows = (q.limit(1).execute().data) or []
        if not rows:
            return None
        jid = rows[0]["id"]
        won = (sb.table("shorts_jobs").update({"status": DOWNLOADING})
               .eq("id", jid).eq("status", CREATED).execute().data)
        if won:
            return jid
        # Lost the race — the row is no longer CREATED, so the next pass skips it.


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
                "status": FAILED,
                "error_message": f"worker exited unexpectedly (rc={proc.returncode})",
            }).eq("id", job_id).execute()
            log.warning("shorts job %s: worker exited rc=%s (status=%s) -> FAILED",
                        job_id, proc.returncode, job.get("status"))

    # 2. Fill free slots with queued work — unless dispatch is held.
    if not settings.SHORTS_DISPATCH_ENABLED:
        return
    cap = settings.SHORTS_MAX_CONCURRENT_JOBS
    while len(_running) < cap:
        next_id = _claim_next(sb)
        if next_id is None:
            break
        try:
            _running[next_id] = _spawn(next_id)
        except Exception:
            # Spawn failed after we claimed the row — release it back to CREATED
            # so it is retried next tick rather than stranded in DOWNLOADING.
            log.exception("shorts dispatch: spawn failed for job %s; releasing claim", next_id)
            sb.table("shorts_jobs").update({"status": CREATED}).eq("id", next_id).execute()
            break
        log.info("shorts dispatch: launched worker for job %s (%d/%d slots)",
                 next_id, len(_running), cap)
