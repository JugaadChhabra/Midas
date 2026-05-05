from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.auth import router as auth_router
from app.sync import router as sync_router
from app.audits import router as audits_router
from app.config import settings

app = FastAPI(title="Midas")
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(audits_router)

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
