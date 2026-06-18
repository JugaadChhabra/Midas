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
    # Filter to units > 0 BEFORE Supabase's 1000-row default cap kicks in.
    # Loop 0's metrics_poll writes one units=0 telemetry row per analytics
    # call; without this filter those zero rows can crowd real Data API rows
    # out of the 1000-row window mid-day, silently under-reporting quota and
    # letting can_afford() return True past the real budget. See
    # docs/PHASE_0_GAPS.md Gap 8.
    res = (
        supabase().table("quota_log")
        .select("units")
        .gte("occurred_at", _today_start_iso())
        .gt("units", 0)
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
