"""AutoShorts — the standalone YouTube-URL demo surface.

A product-demo front door for the shorts cutter: paste a YouTube link, watch it
cut, preview and download the clips. Deliberately self-contained (this module +
app/static/autoshorts.html) so the whole demo can be removed in one step.

Nothing here publishes to YouTube. Jobs are inserted with upload_cap=0, which the
runner already reads as "cut everything, hold every clip" — clips land on local
disk and are served by GET /shorts/clips/{id}/file.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings
from app.db import supabase
from app.shorts.cutter.download import is_youtube_url
from app.shorts.dispatcher import _spawn      # same worker launch the dispatcher uses
from app.shorts.status import DOWNLOADING, FAILED

log = logging.getLogger("midas.shorts.autoshorts")

router = APIRouter(tags=["autoshorts"])

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


class AutoShortsRequest(BaseModel):
    url: str


def _demo_channel_id(sb) -> str:
    """shorts_jobs.channel_id is NOT NULL and a FK to channels, so a job needs
    one even though this flow never touches a channel. Borrow any existing row —
    nothing is read back off it and nothing is ever published to it."""
    rows = sb.table("channels").select("id").limit(1).execute().data or []
    if not rows:
        raise HTTPException(
            503, "No channel is connected yet — connect one at /auth/login first. "
                 "AutoShorts doesn't publish to it; a job row just needs one to exist.")
    return rows[0]["id"]


@router.post("/autoshorts/jobs")
def create_autoshorts_job(body: AutoShortsRequest):
    if not settings.SHORTS_YT_DOWNLOAD_ENABLED:
        raise HTTPException(503, "YouTube-URL cutting is off. Set SHORTS_YT_DOWNLOAD_ENABLED=true and restart.")
    url = body.url.strip()
    if not is_youtube_url(url):
        raise HTTPException(400, "That doesn't look like a YouTube video link.")
    sb = supabase()
    # Inserted already-claimed (DOWNLOADING, not CREATED) and run by THIS process.
    # Going through the normal CREATED queue would offer the job to every
    # dispatcher sharing this Supabase, and a NAS-only deployment that wins the
    # race can only fail it with "download is retired" — which is exactly what
    # happened to jobs 3218-3220 on 2026-08-04. The demo must not depend on
    # winning that race, so it never enqueues work it isn't about to run itself.
    inserted = sb.table("shorts_jobs").insert({
        "channel_id":          _demo_channel_id(sb),
        "source_url":          url,
        "cut_mode":            "highlights",
        "camera_motion":       "calm",
        "upload_cap":          0,        # cut everything, publish nothing
        "autopilot_generated": False,
        "status":              DOWNLOADING,
    }).execute().data
    job_id = inserted[0]["id"]
    try:
        _spawn(job_id)
    except Exception as exc:
        sb.table("shorts_jobs").update({
            "status": FAILED, "error_message": f"could not start worker: {exc}"[:1000],
        }).eq("id", job_id).execute()
        log.exception("AutoShorts job %d: worker spawn failed", job_id)
        raise HTTPException(500, "Could not start the cutter process.")
    log.info("AutoShorts job %d started locally for %s", job_id, url)
    return {"job_id": job_id}


@router.get("/autoshorts")
def autoshorts_page():
    return FileResponse(_STATIC_DIR / "autoshorts.html")
