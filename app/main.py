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
from app.quota import router as quota_router
from app.performance import router as performance_router
from app.autopilot import router as autopilot_router, tick as autopilot_tick
from app.dashboard import router as dashboard_router
from app.config import settings
from app.db import supabase
from app.playlists import reconcile_channel
from app.playlists_sync import sync_playlists
from app.playlist_discovery import discover_playlists
from app.playlists_router import router as playlists_router
from app.reflection import reflect as reflection_reflect, router as reflection_router
from app.shorts.routes import router as shorts_router
from app.metrics_poll import poll_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
_main_log = logging.getLogger("midas.main")
# Quiet noisy library loggers — they emit one INFO line per HTTP call.
for noisy in ("httpx", "httpcore", "google_auth_httplib2", "googleapiclient.discovery_cache", "hpack"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("midas")

scheduler = BackgroundScheduler(daemon=True)


def _all_channel_ids() -> list[str]:
    rows = supabase().table("channels").select("id").execute().data or []
    return [r["id"] for r in rows]


def _daily_reconcile():
    for channel_id in _all_channel_ids():
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
        # Behavior is best-effort; the loud .exception() log is the operator
        # signal to investigate.
        try:
            sync_result = sync_playlists(channel_id)
            _main_log.info("Daily playlist sync %s: %s", channel_id, sync_result)
        except Exception as e:
            _main_log.exception("Daily playlist sync failed for %s: %s", channel_id, e)
        try:
            result = reconcile_channel(channel_id)
            _main_log.info("Daily reconcile %s: %s", channel_id, result)
        except Exception as e:
            _main_log.exception("Daily reconcile failed for %s: %s", channel_id, e)


def _weekly_discovery():
    for channel_id in _all_channel_ids():
        try:
            result = discover_playlists(channel_id)
            _main_log.info("Weekly discovery %s: %s", channel_id, result)
        except Exception as e:
            _main_log.exception("Weekly discovery failed for %s: %s", channel_id, e)


def _weekly_reflection():
    for channel_id in _all_channel_ids():
        try:
            result = reflection_reflect(channel_id)
            _main_log.info("Weekly reflection %s: %s", channel_id, result)
        except Exception as e:
            _main_log.exception("Weekly reflection failed for %s: %s", channel_id, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        autopilot_tick,
        "interval",
        seconds=settings.AUTOPILOT_TICK_SECONDS,
        id="autopilot",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _daily_reconcile,
        "cron",
        hour=2,
        minute=0,
        id="playlist_reconcile",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _weekly_discovery,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="playlist_discovery",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _weekly_reflection,
        "cron",
        day_of_week="mon",
        hour=4,
        minute=0,
        id="reflection",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
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
    scheduler.start()
    log.info("Autopilot scheduler started (every %ds, DRY_RUN=%s)",
             settings.AUTOPILOT_TICK_SECONDS, settings.DRY_RUN)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


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

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/channel")
def channel_page():
    return FileResponse(STATIC_DIR / "channel.html")


@app.get("/performance")
def performance_page():
    return FileResponse(STATIC_DIR / "performance.html")


@app.get("/health")
def health():
    return {"ok": True, "dry_run": settings.DRY_RUN}
