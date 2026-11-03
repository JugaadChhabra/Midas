"""Run, once, the daily jobs whose time passed while Midas was down.

APScheduler keeps its jobs in memory: a fire time that passes while the app is
down is dropped, not run late. Since the 2026-10-29 move the office machine is
often down until early afternoon IST, after the 04:00-07:00 UTC sync and polls,
so the reach and traffic frontier froze for five days (2026-10-29 to 11-02)
and every verdict sat in `awaiting_window`.

`run` is added as a one-off job when the scheduler starts (main.lifespan). It
pauses the jobs in CATCH_UP, runs in that order each one whose latest fire
time in the last LOOKBACK passed with no run recorded since (the registry is
kept across restarts, app/job_status.py), repeats until a pass finds none (one
that fell due meanwhile), then resumes them. Pausing keeps a regular fire from
running beside or ahead of the catch-up: Monday's lever_measurement waits for
the traffic it measures. Each run lands in the registry under the job's own id.

Every job here is safe to run again: the polls ingest only reports not yet
ingested, video_sync skips a channel synced within 6 hours, the measurements
recompute in place, and the backup replaces today's slot. Left out: the
playlist reconcile (Data API budget), the playlist test apply and the Short-link
refresh (YouTube writes, LLM calls); they wait for their next fire.
"""
import logging
import traceback
from datetime import datetime, timedelta, timezone

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent

log = logging.getLogger("midas.catch_up")

JOB_ID = "startup_catch_up"

# Run order: the sync and polls before what reads them, the health check after
# them, the snapshot last so it holds the rest.
CATCH_UP = (
    "video_sync",
    "metrics_poll",
    "reporting_poll",
    "traffic_poll",
    "playlist_health_score",
    "measurement_eval",
    "lever_measurement",
    "channel_health",
    "nightly_db_backup",
)

# How far back a missed fire counts. A daily job's older miss is followed by a
# fire that also counts; a weekly one (lever_measurement, Monday) is caught up
# if the app starts by Tuesday at that hour.
LOOKBACK = timedelta(hours=24)


def due(job, now: datetime) -> datetime | None:
    """The job's latest fire time in [now - LOOKBACK, now], or None."""
    last = None
    at = job.trigger.get_next_fire_time(None, now - LOOKBACK)
    while at is not None and at <= now:
        last = at
        at = job.trigger.get_next_fire_time(at, at + timedelta(seconds=1))
    return last


def missed(scheduler, registry, now: datetime, *, skip=()) -> list:
    """The CATCH_UP jobs, in order, with a fire time in the lookback that no
    recorded run (any outcome) has come at or after."""
    out = []
    for job_id in CATCH_UP:
        job = scheduler.get_job(job_id)
        if job is None or job_id in skip:
            continue                             # not registered (a freeze flag), or done
        fire = due(job, now)
        last = registry.last_run_at(job_id)
        if fire is not None and (last is None or last < fire):
            out.append(job)
    return out


def _run_one(job, registry, started: datetime) -> None:
    log.info("startup catch-up: running %s", job.id)
    try:
        retval = job.func(*job.args, **job.kwargs)
    except Exception as e:
        log.exception("startup catch-up: %s failed: %s", job.id, e)
        event = JobExecutionEvent(EVENT_JOB_ERROR, job.id, "default", started,
                                  exception=e, traceback=traceback.format_exc())
    else:
        event = JobExecutionEvent(EVENT_JOB_EXECUTED, job.id, "default", started,
                                  retval=retval)
    registry.on_event(event)


def run(scheduler, registry, *, clock=lambda: datetime.now(timezone.utc)) -> list[str]:
    """Run the missed CATCH_UP jobs (see the module docstring); returns their
    ids in the order run. Each runs at most once, whatever the registry says."""
    ids = [j for j in CATCH_UP if scheduler.get_job(j) is not None]
    for job_id in ids:
        scheduler.pause_job(job_id)
    ran: list[str] = []
    try:
        while jobs := missed(scheduler, registry, clock(), skip=ran):
            for job in jobs:
                _run_one(job, registry, clock())
                ran.append(job.id)
    finally:
        for job_id in ids:
            scheduler.resume_job(job_id)
    log.info("startup catch-up: %s", ", ".join(ran) if ran else "nothing missed")
    return ran
