from datetime import datetime, timezone, timedelta
from fastapi import APIRouter

from app.config import settings
from app.db import supabase

router = APIRouter(tags=["quota"])


def _today_start_iso() -> str:
    # YouTube quota resets at midnight Pacific. We use UTC date here as a close-enough
    # approximation; tightening this is a future improvement.
    today = datetime.now(timezone.utc).date()
    return datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).isoformat()


def units_used_today() -> int:
    res = (
        supabase().table("quota_log")
        .select("units")
        .gte("occurred_at", _today_start_iso())
        .execute()
    )
    return sum((row.get("units") or 0) for row in (res.data or []))


def units_remaining() -> int:
    return settings.YT_DAILY_QUOTA - settings.YT_QUOTA_SAFETY_BUFFER - units_used_today()


def can_afford(cost: int) -> bool:
    return units_remaining() >= cost


@router.get("/quota")
def quota_status():
    used = units_used_today()
    recent = (
        supabase().table("quota_log")
        .select("occurred_at,channel_id,operation,units,success")
        .order("occurred_at", desc=True)
        .limit(20)
        .execute()
    )
    return {
        "used_today": used,
        "remaining": settings.YT_DAILY_QUOTA - settings.YT_QUOTA_SAFETY_BUFFER - used,
        "limit": settings.YT_DAILY_QUOTA,
        "safety_buffer": settings.YT_QUOTA_SAFETY_BUFFER,
        "recent": recent.data or [],
    }
