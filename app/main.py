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
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
# Quiet noisy library loggers — they emit one INFO line per HTTP call.
for noisy in ("httpx", "httpcore", "google_auth_httplib2", "googleapiclient.discovery_cache", "hpack"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("midas")

scheduler = BackgroundScheduler(daemon=True)


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
