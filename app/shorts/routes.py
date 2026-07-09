import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import supabase
from app.shorts.cutter.download import is_youtube_url
from app.shorts.runner import has_active_job, start_job_thread
from app.shorts.youtube_upload import upload_short

log = logging.getLogger("midas.shorts.routes")

router = APIRouter(prefix="/shorts", tags=["shorts"])


class CreateJob(BaseModel):
    channel_id: str
    source_url: str
    cut_mode: str = "highlights"        # highlights | coverage
    camera_motion: str = "calm"         # locked | calm | follow


@router.post("/jobs")
def create_job(body: CreateJob):
    sb = supabase()
    chan = sb.table("channels").select("id").eq("id", body.channel_id).single().execute().data
    if not chan:
        raise HTTPException(404, f"Channel {body.channel_id} not found")
    if not is_youtube_url(body.source_url):
        raise HTTPException(400, "source_url must be a YouTube video link")
    if has_active_job():
        raise HTTPException(409, "A shorts job is already running; wait for it to finish")

    inserted = sb.table("shorts_jobs").insert({
        "channel_id":    body.channel_id,
        "source_url":    body.source_url,
        "cut_mode":      body.cut_mode,
        "camera_motion": body.camera_motion,
        "status":        "CREATED",
    }).execute().data
    job_id = inserted[0]["id"]
    start_job_thread(job_id)
    log.info("Shorts job %d created for %s", job_id, body.source_url)
    return {"job_id": job_id}


@router.get("/jobs")
def list_jobs():
    sb = supabase()
    return sb.table("shorts_jobs").select("*").order("id", desc=True).limit(50).execute().data or []


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    sb = supabase()
    job = sb.table("shorts_jobs").select("*").eq("id", job_id).single().execute().data
    if not job:
        raise HTTPException(404, "Job not found")
    clips = sb.table("shorts_clips").select("*").eq("job_id", job_id).order("rank").execute().data or []
    return {"job": job, "clips": clips}


@router.post("/clips/{clip_id}/upload")
def upload_clip(clip_id: int):
    sb = supabase()
    clip = sb.table("shorts_clips").select("*").eq("id", clip_id).single().execute().data
    if not clip:
        raise HTTPException(404, "Clip not found")
    if clip["upload_status"] not in ("PENDING", "FAILED"):
        raise HTTPException(409, f"Clip is {clip['upload_status']}, not uploadable")
    job = sb.table("shorts_jobs").select("channel_id").eq("id", clip["job_id"]).single().execute().data
    if not job:
        raise HTTPException(404, "Parent job not found")
    sb.table("shorts_clips").update({"upload_status": "UPLOADING"}).eq("id", clip_id).execute()
    try:
        video_id = upload_short(job["channel_id"], clip["local_path"],
                                clip.get("title") or "Short", "", ["shorts"])
    except Exception as exc:
        sb.table("shorts_clips").update(
            {"upload_status": "FAILED", "upload_error": f"{type(exc).__name__}: {exc}"[:1000]}
        ).eq("id", clip_id).execute()
        raise HTTPException(502, f"Upload failed: {exc}")
    sb.table("shorts_clips").update(
        {"upload_status": "UPLOADED", "yt_video_id": video_id}
    ).eq("id", clip_id).execute()
    return {"clip_id": clip_id, "yt_video_id": video_id}


# Video-scoped shorts endpoint. No /shorts prefix so it sits next to /videos/{id}/audit.
video_router = APIRouter(tags=["shorts"])


class MakeShort(BaseModel):
    cut_mode: str = "highlights"        # highlights | coverage
    camera_motion: str = "calm"         # locked | calm | follow


@video_router.post("/videos/{video_id}/short")
def make_short(video_id: str, body: MakeShort | None = None):
    body = body or MakeShort()
    sb = supabase()
    video = sb.table("videos").select("id,channel_id").eq("id", video_id).single().execute().data
    if not video:
        raise HTTPException(404, f"Video {video_id} not found")
    if has_active_job():
        raise HTTPException(409, "A shorts job is already running; wait for it to finish")
    inserted = sb.table("shorts_jobs").insert({
        "channel_id":         video["channel_id"],
        "source_video_id":    video_id,
        "source_url":         f"https://www.youtube.com/watch?v={video_id}",
        "cut_mode":           body.cut_mode,
        "camera_motion":      body.camera_motion,
        "upload_cap":         None,       # manual button uploads all clips
        "autopilot_generated": False,
        "status":             "CREATED",
    }).execute().data
    job_id = inserted[0]["id"]
    start_job_thread(job_id)
    log.info("Shorts job %d created for video %s", job_id, video_id)
    return {"job_id": job_id}
