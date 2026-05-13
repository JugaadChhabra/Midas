"""Aggregate stats for the home / index dashboard.

Adds endpoints used by index.html. Existing endpoints (e.g. /auth/channels) are
left untouched so other pages keep working.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter

from app.config import settings
from app.db import supabase
from app import quota as quota_mod

router = APIRouter(tags=["dashboard"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/dashboard")
def dashboard():
    """One-shot payload for the home page.

    Returns:
      channels: per-channel rows enriched with pending/applied/Δviews/autopilot pace
      kpis: global counts (channels, total pending, applied today, applied 7d, quota used)
      quota: today's used + safety + 7d sparkline (per-day usage)
    """
    now = _now()
    today_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
    seven_d_ago = now - timedelta(days=7)

    channels = (
        supabase().table("channels").select(
            "id,name,handle,last_synced_at,default_language,"
            "autopilot_enabled,autopilot_paused_reason,autopilot_daily_cap,autopilot_last_tick_at"
        ).execute()
    ).data or []

    # Pull all videos and audits once, then aggregate in Python — cheaper than N round-trips.
    videos = (
        supabase().table("videos").select("id,channel_id,view_count").execute()
    ).data or []
    video_to_channel: dict[str, str] = {v["id"]: v["channel_id"] for v in videos}
    channel_video_counts: dict[str, int] = {}
    for v in videos:
        channel_video_counts[v["channel_id"]] = channel_video_counts.get(v["channel_id"], 0) + 1

    # Latest audit per video → state per video.
    audits_state = (
        supabase().table("audits")
        .select("id,video_id,status,applied_at,created_at,view_count_at_apply")
        .order("created_at", desc=True)
        .execute()
    ).data or []
    latest_per_video: dict[str, dict] = {}
    for a in audits_state:
        latest_per_video.setdefault(a["video_id"], a)

    # Per-channel aggregates
    pending_by_channel: dict[str, int] = {}
    applied_today_by_channel: dict[str, int] = {}
    applied_7d_by_channel: dict[str, int] = {}
    delta_views_7d_by_channel: dict[str, int] = {}
    total_applied_by_channel: dict[str, int] = {}

    # current view counts for delta calc
    cur_views_by_video: dict[str, int] = {v["id"]: (v.get("view_count") or 0) for v in videos}

    # For pending: count latest audit == 'pending' per video
    for vid, a in latest_per_video.items():
        ch = video_to_channel.get(vid)
        if not ch:
            continue
        if a["status"] == "pending":
            pending_by_channel[ch] = pending_by_channel.get(ch, 0) + 1

    # For applied counts and Δviews 7d: scan ALL applied audits (not just latest)
    for a in audits_state:
        if a["status"] != "applied":
            continue
        ch = video_to_channel.get(a["video_id"])
        if not ch:
            continue
        total_applied_by_channel[ch] = total_applied_by_channel.get(ch, 0) + 1
        ap = _parse_iso(a.get("applied_at"))
        if ap and ap >= today_start:
            applied_today_by_channel[ch] = applied_today_by_channel.get(ch, 0) + 1
        if ap and ap >= seven_d_ago:
            applied_7d_by_channel[ch] = applied_7d_by_channel.get(ch, 0) + 1
            cur = cur_views_by_video.get(a["video_id"], 0)
            base = a.get("view_count_at_apply") or 0
            delta_views_7d_by_channel[ch] = delta_views_7d_by_channel.get(ch, 0) + (cur - base)

    # Sync-freshness color buckets done client-side; we just send last_synced_at.
    enriched = []
    for c in channels:
        cid = c["id"]
        last_sync = _parse_iso(c.get("last_synced_at"))
        hours_since_sync = None
        if last_sync:
            hours_since_sync = round((now - last_sync).total_seconds() / 3600.0, 2)
        enriched.append({
            **c,
            "video_count": channel_video_counts.get(cid, 0),
            "pending_count": pending_by_channel.get(cid, 0),
            "applied_today": applied_today_by_channel.get(cid, 0),
            "applied_7d": applied_7d_by_channel.get(cid, 0),
            "applied_total": total_applied_by_channel.get(cid, 0),
            "delta_views_7d": delta_views_7d_by_channel.get(cid, 0),
            "hours_since_sync": hours_since_sync,
        })

    # ── System health ─────────────────────────────────────────────────────
    running_count = sum(1 for c in enriched if c.get("autopilot_enabled") and not c.get("autopilot_paused_reason"))
    paused_count = sum(1 for c in enriched if c.get("autopilot_paused_reason"))
    enabled_count = sum(1 for c in enriched if c.get("autopilot_enabled"))
    sync_hours = [c["hours_since_sync"] for c in enriched if c["hours_since_sync"] is not None]
    worst_sync_hours = round(max(sync_hours), 1) if sync_hours else None

    # ── Pipeline funnel ───────────────────────────────────────────────────
    total_videos_global = sum(channel_video_counts.values())
    # A video is "audited" if it has any audit record belonging to a known channel
    audited_video_ids = {vid for vid in latest_per_video if vid in video_to_channel}
    total_audited_global = len(audited_video_ids)
    total_not_audited_global = max(0, total_videos_global - total_audited_global)
    total_applied_global = sum(
        1 for vid, a in latest_per_video.items()
        if vid in video_to_channel and a["status"] == "applied"
    )
    applied_7d_total = sum(applied_7d_by_channel.values())
    daily_rate = applied_7d_total / 7.0
    eta_days = round(total_not_audited_global / daily_rate) if daily_rate > 0 and total_not_audited_global > 0 else None
    progress_pct = round(100.0 * total_audited_global / total_videos_global, 1) if total_videos_global > 0 else 0
    apply_pct_of_audited = round(100.0 * total_applied_global / total_audited_global, 1) if total_audited_global > 0 else 0

    # ── Quota reset countdown (YouTube resets midnight Pacific = 07:00 UTC PDT) ─
    QUOTA_RESET_HOUR_UTC = 7
    reset_time = now.replace(hour=QUOTA_RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if reset_time <= now:
        reset_time += timedelta(days=1)
    quota_reset_in_seconds = int((reset_time - now).total_seconds())

    # ── Activity feed (cross-channel, last 8 events) ──────────────────────
    recent_audits = (
        supabase().table("audits")
        .select("id,video_id,status,applied_at,created_at,ai_reasoning")
        .in_("status", ["applied", "pending", "quarantined", "failed"])
        .order("created_at", desc=True)
        .limit(8)
        .execute()
    ).data or []
    feed_video_ids = [a["video_id"] for a in recent_audits]
    feed_video_map: dict[str, dict] = {}
    if feed_video_ids:
        feed_vids = (
            supabase().table("videos")
            .select("id,title,channel_id")
            .in_("id", feed_video_ids)
            .execute()
        ).data or []
        feed_video_map = {v["id"]: v for v in feed_vids}
    channel_name_map = {c["id"]: c.get("name") or c["id"] for c in channels}
    activity_feed = []
    for a in recent_audits:
        fv = feed_video_map.get(a["video_id"], {})
        ch_id = fv.get("channel_id")
        activity_feed.append({
            "status": a["status"],
            "video_id": a["video_id"],
            "video_title": fv.get("title"),
            "channel_id": ch_id,
            "channel_name": channel_name_map.get(ch_id) if ch_id else None,
            "applied_at": a.get("applied_at"),
            "created_at": a.get("created_at"),
        })

    # ── KPIs ──────────────────────────────────────────────────────────────
    kpis = {
        "channels": len(channels),
        "videos": total_videos_global,
        "pending_total": sum(pending_by_channel.values()),
        "applied_today_total": sum(applied_today_by_channel.values()),
        "applied_7d_total": applied_7d_total,
        "delta_views_7d_total": sum(delta_views_7d_by_channel.values()),
    }

    health = {
        "autopilot_running": running_count,
        "autopilot_paused": paused_count,
        "autopilot_enabled": enabled_count,
        "autopilot_total": len(channels),
        "worst_sync_hours": worst_sync_hours,
    }

    pipeline = {
        "total": total_videos_global,
        "audited": total_audited_global,
        "pending": sum(pending_by_channel.values()),
        "applied": total_applied_global,
        "not_audited": total_not_audited_global,
        "progress_pct": progress_pct,
        "apply_pct_of_audited": apply_pct_of_audited,
        "daily_rate": round(daily_rate, 1),
        "eta_days": eta_days,
    }

    # Quota: today's used (authoritative via quota module) + 7-day sparkline.
    # The sparkline query fetches at most 1000 rows and is only used for the
    # chart; we never derive used_today from it to avoid silent truncation.
    used_today = quota_mod.units_used_today()
    quota_log = (
        supabase().table("quota_log")
        .select("units,occurred_at")
        .gte("occurred_at", _iso(now - timedelta(days=7)))
        .order("occurred_at", desc=False)
        .execute()
    ).data or []
    by_day: dict[str, int] = {}
    for r in quota_log:
        dt = _parse_iso(r.get("occurred_at"))
        if not dt:
            continue
        u = r.get("units") or 0
        day = dt.date().isoformat()
        by_day[day] = by_day.get(day, 0) + u
    spark: list[dict] = []
    for i in range(7, -1, -1):
        d = (now.date() - timedelta(days=i)).isoformat()
        spark.append({"date": d, "units": by_day.get(d, 0)})

    quota_block = {
        "used_today": used_today,
        "limit": settings.YT_DAILY_QUOTA,
        "safety_buffer": settings.YT_QUOTA_SAFETY_BUFFER,
        "remaining": settings.YT_DAILY_QUOTA - settings.YT_QUOTA_SAFETY_BUFFER - used_today,
        "reset_in_seconds": quota_reset_in_seconds,
        "sparkline": spark,
    }

    return {
        "channels": enriched,
        "kpis": kpis,
        "quota": quota_block,
        "health": health,
        "pipeline": pipeline,
        "activity": activity_feed,
    }
