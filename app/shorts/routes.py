from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import supabase
from app.shorts.wayin_client import submit_clipping, WayinVideoError
from app.shorts.poller import schedule_poll

router = APIRouter(prefix="/shorts", tags=["shorts"])


class CreateJob(BaseModel):
    channel_id: str
    source_url: str


@router.post("/jobs")
def create_job(body: CreateJob):
    sb = supabase()
    chan = sb.table("channels").select("id").eq("id", body.channel_id).single().execute().data
    if not chan:
        raise HTTPException(404, f"Channel {body.channel_id} not found")

    inserted = sb.table("shorts_jobs").insert({
        "channel_id": body.channel_id,
        "source_url": body.source_url,
        "status":     "CREATED",
    }).execute().data
    job_id = inserted[0]["id"]

    try:
        project_id = submit_clipping(body.source_url)
    except WayinVideoError as e:
        sb.table("shorts_jobs").update({
            "status": "FAILED",
            "error_message": str(e)[:1000],
        }).eq("id", job_id).execute()
        raise HTTPException(502, f"WayinVideo rejected the submission: {e}")

    sb.table("shorts_jobs").update({
        "status": "QUEUED",
        "wayinvideo_project_id": project_id,
    }).eq("id", job_id).execute()

    schedule_poll(job_id, delay_seconds=15)
    return {"job_id": job_id, "wayinvideo_project_id": project_id}


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
