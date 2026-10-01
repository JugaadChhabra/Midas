import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler

from app.auth import router as auth_router
from app.sync import router as sync_router
from app.audits import router as audits_router
from app import eligibility, job_status, measurement, quota, sync, tracing
from app.quota import router as quota_router, JobBudget
from app.rows import all_rows
from app.youtube_client import TokenExpiredError
from app.performance import router as performance_router
from app.autopilot import router as autopilot_router, tick as autopilot_tick
from app.dashboard import router as dashboard_router
from app.config import settings
from app.db import supabase
from app.playlists import reconcile_channel, tune_thresholds
from app.playlists_sync import sync_playlists
from app.playlist_discovery import discover_playlists
from app.playlists_router import router as playlists_router
from app.reflection import reflect as reflection_reflect, router as reflection_router
from app.shorts.routes import router as shorts_router, video_router as shorts_video_router
from app.shorts.autoshorts import router as autoshorts_router
from app.shorts.dispatcher import dispatch_tick
from app.backup import run_nightly_backup
from app.provision import ensure_database_populated
from app.metrics_poll import poll_metrics
from app.reporting_poll import poll_reporting
from app.measurement import router as measurement_router
from app.playlist_health import score_channel as playlist_health_score_channel

def _configure_logging() -> None:
    """Log to stdout AND a rotating file under settings.LOG_DIR.

    The file handler is what lets you trace a job that failed on a YouTube
    quota hit after the container is gone — docker's own logs vanish on prune,
    but LOG_DIR is bind-mounted to the host.
    """
    from logging.handlers import RotatingFileHandler

    level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir = Path(settings.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        # 10 MB × 5 files ≈ 50 MB ceiling — plenty to cover a run's history
        # without letting the bind mount grow unbounded on a long-lived host.
        fh = RotatingFileHandler(
            log_dir / "midas.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
        )
        handlers.append(fh)
    except OSError as exc:  # read-only mount, permissions — don't crash boot
        logging.getLogger("midas.main").warning("file logging disabled: %s", exc)

    for h in handlers:
        h.setFormatter(fmt)
    logging.basicConfig(level=level, handlers=handlers)


_configure_logging()
_main_log = logging.getLogger("midas.main")
# Quiet noisy library loggers — they emit one INFO line per HTTP call.
for noisy in ("httpx", "httpcore", "google_auth_httplib2", "googleapiclient.discovery_cache", "hpack"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("midas")

scheduler = BackgroundScheduler(daemon=True)


def _run_per_channel(fn, label, channel_ids=None, job_id="-") -> None:
    """Fan a per-channel job out over every channel, isolating failures.

    Calls ``fn(channel_id)`` for each id (every channel unless ``channel_ids``
    is supplied). ``fn`` is responsible for its own success
    logging; a raised exception is caught and logged per channel at ERROR, with
    traceback, as ``"<label> (job <job_id>) failed for <id>: <err>"`` so one bad
    channel never kills the loop — the shared shape behind the daily/weekly
    scheduler jobs. ``job_id`` is the APScheduler id, the key in /health/jobs.

    Once every channel has run, any failure raises one ``JobRunFailed`` naming
    the failed channels, so APScheduler records the run as failed instead of
    "executed successfully" (see app/job_status.py).
    """
    ids = (
        eligibility.channel_ids_for(eligibility.Job.EVERY)
        if channel_ids is None else channel_ids
    )
    failed: dict[str, str] = {}
    for channel_id in ids:
        try:
            fn(channel_id)
        except Exception as e:
            _main_log.exception("%s (job %s) failed for %s: %s", label, job_id, channel_id, e)
            failed[channel_id] = job_status.describe(e)
    if failed:
        raise job_status.JobRunFailed(label, failed)


def _reconcile_channel_order(ids: list[str]) -> list[str]:
    """Order channels least-recently-walked first.

    The reconcile budget is shared across the whole pass, so whoever runs first
    spends it. In a fixed order that starves the tail of the allowlist every
    single night — the same unfairness `_walk_plan` avoids within a channel, one
    level up. Sorting by each channel's oldest un-walked playlist rotates who
    gets the budget across nights. NULL (never walked) sorts first.
    """
    oldest: dict[str, str] = {}
    rows = all_rows(
        supabase().table("playlists")
        .select("channel_id,membership_walked_at")
        .in_("channel_id", ids)
    )
    for r in rows:
        cid = r["channel_id"]
        walked = r.get("membership_walked_at") or ""
        if cid not in oldest or walked < oldest[cid]:
            oldest[cid] = walked
    # A channel with no playlist rows at all has nothing to walk; "" puts it
    # first, where it costs one cheap playlists.list and drops through.
    return sorted(ids, key=lambda c: oldest.get(c, ""))


def _daily_reconcile():
    # One budget for the whole pass, not per channel: the quota ceiling it
    # protects is fleet-wide. Built here (not inside _one) so every channel
    # draws from the same pool and the pass stops when the pool is dry.
    budget = JobBudget(
        "playlist_sync",
        settings.PLAYLIST_SYNC_QUOTA_BUDGET,
        reserve=settings.YT_QUOTA_APPLY_RESERVE,
    )

    def _one(channel_id):
        # Sync playlist inventory FIRST so any new playlists created in
        # YouTube Studio since yesterday have rows (with role / item_count /
        # last_synced_at populated) before reconcile_channel re-scores
        # assignments and before playlist_health (Phase 1B Step 2) reads
        # the inventory. Failures here are logged but do not block
        # reconcile_channel — the older inventory is still better than no
        # reconcile this tick.
        #
        # Partial-failure caveat: sync_playlists is not transactional (each
        # supabase .execute() is its own round-trip). If sync crashes after
        # upserting some playlists but before completing membership seeding,
        # reconcile_channel runs against a partially-updated state and may
        # produce add/remove decisions that the next clean sync will revert.
        # Behavior is best-effort. Either step failing still fails the channel
        # (re-raised below, after reconcile has had its turn), so the cycle
        # ends failed in /health/jobs as well as in the loud .exception() log.
        errors = []
        try:
            sync_result = sync_playlists(channel_id, budget=budget)
            _main_log.info("Daily playlist sync %s: %s", channel_id, sync_result)
        except Exception as e:
            _main_log.exception("Daily playlist sync (job playlist_reconcile) failed for %s: %s", channel_id, e)
            errors.append(f"sync: {job_status.describe(e)}")
        if not settings.PLAYLIST_RECONCILE_WRITES_ENABLED:
            _main_log.info(
                "Daily reconcile %s: add/remove skipped (PLAYLIST_RECONCILE_WRITES_ENABLED=false)",
                channel_id,
            )
        else:
            try:
                result = reconcile_channel(channel_id)
                _main_log.info("Daily reconcile %s: %s", channel_id, result)
            except Exception as e:
                _main_log.exception("Daily reconcile (job playlist_reconcile) failed for %s: %s", channel_id, e)
                errors.append(f"reconcile: {job_status.describe(e)}")
        if errors:
            raise RuntimeError("; ".join(errors))

    ids = _reconcile_channel_order(eligibility.channel_ids_for(eligibility.Job.RECONCILE))
    try:
        _run_per_channel(_one, "Daily reconcile cycle", channel_ids=ids,
                         job_id="playlist_reconcile")
    finally:
        _main_log.info("Daily reconcile cycle done — %s", budget)


def _weekly_discovery():
    def _one(channel_id):
        result = discover_playlists(channel_id)
        _main_log.info("Weekly discovery %s: %s", channel_id, result)

    _run_per_channel(_one, "Weekly discovery", job_id="playlist_discovery")


def _weekly_reflection():
    def _one(channel_id):
        result = reflection_reflect(channel_id)
        _main_log.info("Weekly reflection %s: %s", channel_id, result)

    _run_per_channel(_one, "Weekly reflection", job_id="reflection")


def _weekly_playlist_tuning():
    """Nudge each channel's PLAYLIST_JOIN_HIGH from its assignment churn.

    This used to piggyback the weekly reflection tick, which conflated playlist
    tuning with CTR-driven prompt reflection. It now runs as its own weekly job
    over the same channel set (Job.EVERY, via _run_per_channel's default), so
    the cadence is unchanged — only the ownership is: the logic lives with the
    playlist engine that reads the threshold.
    """
    def _one(channel_id):
        result = tune_thresholds(channel_id)
        _main_log.info("Weekly playlist tuning %s: %s", channel_id, result)

    _run_per_channel(_one, "Weekly playlist tuning", job_id="playlist_tuning")


def _daily_playlist_health_score():
    """Phase 1B Step 4 — score every channel where playlist_health_enabled=true.

    Runs after metrics_poll (UTC 05:00) so each tick scores against fresh
    playlist_metrics rows. Per-channel exceptions are isolated; one bad
    channel does not kill the loop, but the run still ends failed
    (``JobRunFailed``, visible at /health/jobs). Channels with the flag false are
    skipped silently — same graceful-degradation pattern as Phase 0's
    metrics_poll skipping `analytics_authorized=false`.
    """
    ids = eligibility.channel_ids_for(eligibility.Job.PLAYLIST_HEALTH)
    if not ids:
        _main_log.info("playlist_health_score: no channels with playlist_health_enabled=true")
        return

    def _one(channel_id):
        summary = playlist_health_score_channel(channel_id)
        _main_log.info("Daily playlist_health_score %s: %s", channel_id, summary)

    _run_per_channel(_one, "Daily playlist_health_score", channel_ids=ids,
                     job_id="playlist_health_score")


def _daily_video_sync():
    """Sync every channel's video list once a day, independent of autopilot.

    Video sync used to run only inside autopilot's title-audit path, so pausing
    title autopilot (~2026-09-23) stopped it on every channel. This keeps the
    sensor running whatever autopilot is doing. It's read-only against YouTube:
    an incremental pass (new uploads + refresh_stats) normally, a full pass every
    `sync.FULL_SYNC_INTERVAL`. Channels autopilot synced within
    `sync.SYNC_STALE_AFTER` are skipped. An expired token is an expected skip
    (re-consent fixes it), not a failure; anything else fails the run for that
    channel.
    """
    rows = {c["id"]: c for c in eligibility.channels_for(
        eligibility.Job.EVERY, columns="id,last_synced_at,last_full_synced_at")}

    def _one(channel_id: str) -> None:
        try:
            kind = sync.routine_sync(rows[channel_id])
        except TokenExpiredError:
            _main_log.warning("video_sync %s: OAuth token expired; skipping until re-consent",
                              channel_id)
            return
        _main_log.info("video_sync %s: %s", channel_id, kind)

    _run_per_channel(_one, "Daily video sync", channel_ids=list(rows), job_id="video_sync")


def _daily_measurement_eval():
    """Scheduler wrapper for the measurement pass.

    `eval_measurements` also serves `POST /measurement/evaluate`, which must
    keep answering with its summary, so the raise lives here: any audit that
    errored fails the run, with the failing audits grouped by channel.
    """
    _summary, failed = measurement.evaluate_with_failures()
    if failed:
        raise job_status.JobRunFailed("measurement_eval", failed)


def _refresh_pot_provider():
    """Periodically re-establish the bgutil PO-token sidecar's session so a
    long-lived provider never drifts into serving a stale integrity token — the
    failure mode that makes downloads report live videos as 'not available'."""
    from app.shorts.cutter.download import refresh_pot_provider

    refresh_pot_provider()
    _main_log.info("Refreshed PO-token provider session")


def _register_jobs(sched) -> None:
    """Add every scheduled job to ``sched`` without starting it.

    Split out of lifespan() so tests can introspect what registers under a
    given set of flags. The A4 freeze flags decide which writers register.
    """
    sched.add_job(
        autopilot_tick,
        "interval",
        seconds=settings.AUTOPILOT_TICK_SECONDS,
        id="autopilot",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        dispatch_tick,
        "interval",
        seconds=settings.SHORTS_DISPATCH_INTERVAL_SECONDS,
        id="shorts_dispatch",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _daily_reconcile,
        "cron",
        hour=2,
        minute=0,
        id="playlist_reconcile",
        max_instances=1,
        coalesce=True,
    )
    if not settings.PLAYLIST_RECONCILE_WRITES_ENABLED:
        _main_log.info("playlist_reconcile registered for sync only: add/remove "
                       "skipped (PLAYLIST_RECONCILE_WRITES_ENABLED=false)")
    if settings.PLAYLIST_DISCOVERY_ENABLED:
        sched.add_job(
            _weekly_discovery,
            "cron",
            day_of_week="sun",
            hour=3,
            minute=0,
            id="playlist_discovery",
            max_instances=1,
            coalesce=True,
        )
    else:
        _main_log.info("playlist_discovery not registered: PLAYLIST_DISCOVERY_ENABLED=false")
    if settings.REFLECTION_ENABLED:
        sched.add_job(
            _weekly_reflection,
            "cron",
            day_of_week="mon",
            hour=4,
            minute=0,
            id="reflection",
            max_instances=1,
            coalesce=True,
        )
    else:
        _main_log.info("reflection not registered: REFLECTION_ENABLED=false")
    if settings.PLAYLIST_TUNING_ENABLED:
        sched.add_job(
            _weekly_playlist_tuning,
            "cron",
            day_of_week="mon",
            hour=3,
            minute=30,
            id="playlist_tuning",
            max_instances=1,
            coalesce=True,
        )
    else:
        _main_log.info("playlist_tuning not registered: PLAYLIST_TUNING_ENABLED=false")
    sched.add_job(
        _daily_video_sync,
        "cron",
        hour=4,
        minute=0,
        # UTC, an hour before metrics_poll, so the polls and the scorer work
        # from today's video list. Read-only against YouTube, so it's not one
        # of the A4 frozen writers.
        timezone="UTC",
        id="video_sync",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        poll_metrics,
        "cron",
        hour=5,
        minute=0,
        # Pinned to UTC unlike the other cron jobs above (which run in
        # server-local time). Window math in metrics_poll._window_dates is
        # anchored to UTC and the ~2-day Analytics data lag is UTC-anchored,
        # so a server-tz shift would silently move the fire time and the
        # window together — pin avoids that coupling.
        #
        # Side-effect: depending on server TZ, this UTC-05:00 fire may land
        # before OR after the server-local 02:00 _daily_reconcile on the same
        # calendar day. The two jobs touch disjoint tables, so there's no
        # data race — but operators reading logs across TZs should expect
        # the relative ordering to differ.
        timezone="UTC",
        id="metrics_poll",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        poll_reporting,
        "cron",
        hour=6,
        minute=0,
        # UTC, one hour after metrics_poll (05:00): the window backfill in
        # reporting_poll fills impressions/ctr on video_metrics rows that
        # metrics_poll writes, so running after it means today's fresh window
        # gets checked for reach coverage the same day it's created (it'll
        # usually still be pending — reach CSVs for a data-day arrive 1-6
        # days later per the 2026-07-02 probe — but the ordering avoids a
        # systematic +1-day fill delay). No hard serialization guarantee,
        # same caveat as playlist_health_score below; a missed pass self-
        # heals next day since backfill re-scans NULL-impression windows.
        timezone="UTC",
        id="reporting_poll",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _daily_playlist_health_score,
        "cron",
        hour=7,
        minute=0,
        # UTC, two hours after metrics_poll's UTC 05:00 fire. The gap is the
        # only ordering guarantee we have — APScheduler does not serialize
        # across job IDs, so if metrics_poll spills past this fire time the
        # scorer reads stale (yesterday's) playlist_metrics. Two hours covers
        # the current fleet comfortably (analytics API ≈ 1s/video; ~7k videos
        # ≈ 2hr ceiling). If we approach that ceiling, options are: widen the
        # gap further, or chain `_daily_playlist_health_score()` at the tail
        # of `poll_metrics` to make the ordering atomic. UTC pin rationale
        # is the same as metrics_poll above.
        timezone="UTC",
        id="playlist_health_score",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _daily_measurement_eval,
        "cron",
        hour=8,
        minute=0,
        # UTC, two hours after reporting_poll (06:00) so the freshest reach
        # CSVs and window backfills are in place before verdicts are read.
        # Ordering is soft (same caveat as the other UTC crons); a pass that
        # runs against yesterday's coverage just leaves audits in
        # awaiting_window/measuring and self-heals tomorrow.
        timezone="UTC",
        id="measurement_eval",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        run_nightly_backup,
        "cron",
        hour=settings.BACKUP_HOUR,
        minute=0,
        # Server-local, not UTC: "midnight" here means the office's midnight,
        # which is what bounds the accepted one-day data loss. Self-hosting put
        # the DB on one machine, so this snapshot is the whole recovery story.
        id="nightly_db_backup",
        max_instances=1,
        coalesce=True,
    )
    import os
    if os.getenv("BGUTIL_POT_HTTP_BASE_URL"):
        # Only meaningful for the Docker HTTP sidecar; the Mac mints per-request
        # via a local script, so there's no long-lived session to go stale.
        sched.add_job(
            _refresh_pot_provider,
            "interval",
            hours=2,
            id="pot_provider_refresh",
            max_instances=1,
            coalesce=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # BEFORE anything else, and before a single scheduled job is registered: on
    # a machine that has never run Midas, ./pgdata is an empty cluster and this
    # restores last night's NAS snapshot into it. Raising here keeps the app
    # down, which is the intended behaviour when the NAS is unreachable — see
    # app/provision.py for why serving an empty database is the worse outcome.
    ensure_database_populated()

    _register_jobs(scheduler)
    # After every add_job: each registered job shows as never_run until it
    # fires, and every run (success or failure) lands in the registry.
    job_status.registry.watch(scheduler)
    from app.shorts.runner import reap_stuck_jobs
    try:
        reap_stuck_jobs()
    except Exception:
        log.exception("Startup reap of stuck shorts jobs failed")
    tracing.configure()
    scheduler.start()
    log.info("Autopilot scheduler started (every %ds, DRY_RUN=%s)",
             settings.AUTOPILOT_TICK_SECONDS, settings.DRY_RUN)
    try:
        yield
    finally:
        # Scheduler first, telemetry second — deliberately. The spans worth
        # having at shutdown are the ones the jobs just produced and
        # BatchSpanProcessor is still holding, but `wait=False` means stopping
        # the scheduler does not wait on them, while a flush against a dead
        # Phoenix does wait (bounded, see tracing.FLUSH_TIMEOUT_MS). Flushing
        # first put a telemetry outage between the process and a clean scheduler
        # stop; this ordering cannot.
        scheduler.shutdown(wait=False)
        tracing.flush()


app = FastAPI(title="Midas", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(audits_router)
app.include_router(quota_router)
app.include_router(performance_router)
app.include_router(autopilot_router)
app.include_router(dashboard_router)
app.include_router(playlists_router)
app.include_router(reflection_router)
app.include_router(shorts_router)
app.include_router(shorts_video_router)
app.include_router(autoshorts_router)
app.include_router(measurement_router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/channel")
def channel_page():
    return FileResponse(STATIC_DIR / "channel.html")


@app.get("/health")
def health():
    return {"ok": True, "dry_run": settings.DRY_RUN}


@app.get("/health/jobs")
def health_jobs():
    """Last run of every scheduled job (in-memory; a restart clears it)."""
    return {"jobs": job_status.registry.snapshot()}
