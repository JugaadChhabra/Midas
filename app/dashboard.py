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
            "autopilot_enabled,autopilot_paused_reason,autopilot_daily_cap,autopilot_last_tick_at,"
            "analytics_authorized"
        ).execute()
    ).data or []

    # Pull all videos — paginated because the table can exceed Supabase's 1000-row default cap.
    videos: list[dict] = []
    vid_offset = 0
    while True:
        page = (
            supabase().table("videos")
            .select("id,channel_id,view_count,privacy_status,is_short")
            .range(vid_offset, vid_offset + 999)
            .execute()
        ).data or []
        videos.extend(page)
        if len(page) < 1000:
            break
        vid_offset += 1000
    video_to_channel: dict[str, str] = {v["id"]: v["channel_id"] for v in videos}
    # Only public (or legacy null privacy_status) videos are auditable
    public_video_ids: set[str] = {
        v["id"] for v in videos
        if v.get("privacy_status") is None or v.get("privacy_status") == "public"
    }
    channel_video_counts: dict[str, int] = {}
    channel_shorts_counts: dict[str, int] = {}
    channel_regular_counts: dict[str, int] = {}
    shorts_video_ids: set[str] = set()
    for v in videos:
        if v["id"] not in public_video_ids:
            continue
        ch = v["channel_id"]
        channel_video_counts[ch] = channel_video_counts.get(ch, 0) + 1
        if v.get("is_short"):
            channel_shorts_counts[ch] = channel_shorts_counts.get(ch, 0) + 1
            shorts_video_ids.add(v["id"])
        else:
            channel_regular_counts[ch] = channel_regular_counts.get(ch, 0) + 1

    # Fetch all audit records for known videos.
    # Two levels of pagination:
    #   outer — 200 video IDs per batch (keeps record counts manageable)
    #   inner — range() pages within each batch for channels with heavy re-audits
    # Both levels are needed because Supabase caps every .execute() at 1000 rows.
    all_video_ids = list(video_to_channel.keys())
    audits_state: list[dict] = []
    VID_BATCH = 200
    ROW_PAGE = 1000
    for i in range(0, len(all_video_ids), VID_BATCH):
        batch_ids = all_video_ids[i:i + VID_BATCH]
        inner_offset = 0
        while True:
            page = (
                supabase().table("audits")
                .select("id,video_id,status,applied_at,created_at,view_count_at_apply")
                .in_("video_id", batch_ids)
                .order("created_at", desc=True)
                .range(inner_offset, inner_offset + ROW_PAGE - 1)
                .execute()
            ).data or []
            audits_state.extend(page)
            if len(page) < ROW_PAGE:
                break
            inner_offset += ROW_PAGE
    latest_per_video: dict[str, dict] = {}
    for a in audits_state:
        latest_per_video.setdefault(a["video_id"], a)

    # Per-channel aggregates
    pending_by_channel: dict[str, int] = {}
    applied_today_by_channel: dict[str, int] = {}
    applied_7d_by_channel: dict[str, int] = {}
    delta_views_7d_by_channel: dict[str, int] = {}
    total_applied_by_channel: dict[str, int] = {}
    channel_audited_shorts: dict[str, int] = {}
    channel_audited_regular: dict[str, int] = {}

    for vid in latest_per_video:
        if vid not in public_video_ids:
            continue
        ch = video_to_channel.get(vid)
        if not ch:
            continue
        if vid in shorts_video_ids:
            channel_audited_shorts[ch] = channel_audited_shorts.get(ch, 0) + 1
        else:
            channel_audited_regular[ch] = channel_audited_regular.get(ch, 0) + 1

    # current view counts for delta calc
    cur_views_by_video: dict[str, int] = {v["id"]: (v.get("view_count") or 0) for v in videos}

    # pending: unique public videos whose current audit state is pending
    for vid, a in latest_per_video.items():
        if vid not in public_video_ids:
            continue
        ch = video_to_channel.get(vid)
        if ch and a["status"] == "pending":
            pending_by_channel[ch] = pending_by_channel.get(ch, 0) + 1

    # applied counts: scan ALL applied records so total matches the raw DB count
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
            "regular_count": channel_regular_counts.get(cid, 0),
            "shorts_count": channel_shorts_counts.get(cid, 0),
            "audited_regular": channel_audited_regular.get(cid, 0),
            "audited_shorts": channel_audited_shorts.get(cid, 0),
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
    # Only count public videos as audited/applied — keeps numerator and denominator consistent
    audited_video_ids = {vid for vid in latest_per_video if vid in public_video_ids}
    total_audited_global = len(audited_video_ids)
    total_not_audited_global = max(0, total_videos_global - total_audited_global)
    total_applied_global = sum(
        1 for vid, a in latest_per_video.items()
        if vid in public_video_ids and a["status"] == "applied"
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
    # `units > 0` filter (PHASE_0_GAPS.md Gap 8): Loop 0's metrics_poll and
    # Step B's traffic-source poll write a `units=0` telemetry row per
    # Analytics call. Including those zeros would flood the sparkline window
    # and push real Data API rows past the 1000-row cap. Filtering them out
    # is a safe approximation — the chart is meant to surface real quota
    # consumption, not call-volume telemetry.
    used_today = quota_mod.units_used_today()
    quota_log = (
        supabase().table("quota_log")
        .select("units,occurred_at")
        .gte("occurred_at", _iso(now - timedelta(days=7)))
        .gt("units", 0)
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
