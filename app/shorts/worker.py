"""Isolated shorts-cutter worker. Launched by the dispatcher as a subprocess:

    python -m app.shorts.worker <job_id>

Running in its own process gives this worker its own YOLO/Whisper model
instances and its own CUDA context, so multiple jobs can run in parallel
without sharing the (non-thread-safe) global model singletons. All state is
written to the shorts_jobs/shorts_clips tables — no IPC beyond the DB.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from app.db import supabase
from app.shorts.runner import run_shorts_job

log = logging.getLogger("midas.shorts.worker")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m app.shorts.worker <job_id>", file=sys.stderr)
        return 2
    job_id = int(argv[0])
    # Record this process so the startup reaper can kill us if we're orphaned.
    supabase().table("shorts_jobs").update({
        "worker_pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()
    run_shorts_job(job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
