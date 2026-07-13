import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import supabase
from app.shorts.cutter.download import is_youtube_url
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

    inserted = sb.table("shorts_jobs").insert({
        "channel_id":    body.channel_id,
        "source_url":    body.source_url,
        "cut_mode":      body.cut_mode,
        "camera_motion": body.camera_motion,
        "status":        "CREATED",
    }).execute().data
    job_id = inserted[0]["id"]
    log.info("Shorts job %d queued for %s", job_id, body.source_url)
    return {"job_id": job_id}


@router.get("/jobs")
def list_jobs(channel_id: str | None = None):
    sb = supabase()
    q = sb.table("shorts_jobs").select("*")
    if channel_id:
        q = q.eq("channel_id", channel_id)
    return q.order("id", desc=True).limit(50).execute().data or []


@router.post("/jobs/clear-failed")
def clear_failed_jobs(channel_id: str | None = None):
    """Delete FAILED shorts jobs (and their clips) so the list can start fresh.
    Scoped to one channel when channel_id is given, else all channels."""
    sb = supabase()
    q = sb.table("shorts_jobs").select("id").eq("status", "FAILED")
    if channel_id:
        q = q.eq("channel_id", channel_id)
    ids = [r["id"] for r in (q.execute().data or [])]
    if ids:
        # child rows first (FK), then the jobs; chunk to keep the URL short.
        for i in range(0, len(ids), 100):
            batch = ids[i:i + 100]
            sb.table("shorts_clips").delete().in_("job_id", batch).execute()
            sb.table("shorts_jobs").delete().in_("id", batch).execute()
    return {"deleted": len(ids)}


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
    video = sb.table("videos").select("id,channel_id,privacy_status").eq("id", video_id).single().execute().data
    if not video:
        raise HTTPException(404, f"Video {video_id} not found")
    # Only cut confirmed-public videos: refuse private, unlisted, or unknown
    # (unsynced NULL) privacy — cutting a non-public source risks reuploading
    # content the owner did not make public.
    if video.get("privacy_status") != "public":
        raise HTTPException(
            409, f"Video is {video.get('privacy_status') or 'of unknown privacy'}; "
                 "only public videos can be cut into shorts")
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
    log.info("Shorts job %d queued for video %s", job_id, video_id)
    return {"job_id": job_id}
