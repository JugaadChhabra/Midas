"""Aggregate stats for the home / index dashboard.

Adds endpoints used by index.html. Existing endpoints (e.g. /auth/channels) are
left untouched so other pages keep working.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter

from app.config import settings
from app.db import supabase
from app import quota as quota_mod

log = logging.getLogger("midas.dashboard")
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


# Short TTL cache for /dashboard. The endpoint scans the entire videos + audits
# tables to compute global counts; index.html polls it every 30s and each open
# tab used to trigger its own full scan — the dominant Supabase-egress source
# after the shorts poll. The payload is global (no per-request args) and the
# underlying data changes slowly (audits apply on a schedule), so every poll
# within the TTL is served from one computed result.
_DASHBOARD_TTL_SECONDS = 30.0
_dashboard_lock = threading.Lock()
_dashboard_cache: dict = {"at": 0.0, "payload": None}


@router.get("/dashboard")
def dashboard():
    """Cached wrapper around _compute_dashboard(). Double-checked locking so a
    burst of concurrent polls arriving after expiry recomputes exactly once —
    not once per request — then shares the result."""
    now = time.monotonic()
    if _dashboard_cache["payload"] is not None and now - _dashboard_cache["at"] < _DASHBOARD_TTL_SECONDS:
        return _dashboard_cache["payload"]
    with _dashboard_lock:
        now = time.monotonic()
        if _dashboard_cache["payload"] is not None and now - _dashboard_cache["at"] < _DASHBOARD_TTL_SECONDS:
            return _dashboard_cache["payload"]
        payload = _compute_dashboard()
        _dashboard_cache["payload"] = payload
        _dashboard_cache["at"] = time.monotonic()
        return payload


# ── Per-channel aggregates ────────────────────────────────────────────────
# Both aggregators (_aggregate_rpc, _aggregate_legacy) return the SAME shape:
#   (stats_by_channel: {channel_id -> dict of _STAT_KEYS}, cut_total, uploaded_total)
# so _compute_dashboard's enrichment/KPI/pipeline code is path-agnostic.
_STAT_KEYS = (
    "video_count", "regular_count", "shorts_count",
    "audited_regular", "audited_shorts", "pending_count",
    "applied_latest", "applied_today", "applied_7d", "applied_total",
    "delta_views_7d",
)


def _empty_stat() -> dict:
    return {k: 0 for k in _STAT_KEYS}


def _aggregate_rpc() -> tuple[dict, int, int]:
    """Per-channel aggregates via the dashboard_summary() Postgres function.
    Returns a few KB of JSON instead of egressing the whole videos/audits/
    shorts_clips tables — the ~100x egress cut over _aggregate_legacy."""
    summary = supabase().rpc("dashboard_summary").execute().data or {}
    stats: dict[str, dict] = {}
    for row in summary.get("channels") or []:
        cid = row.get("channel_id")
        if cid is None:
            continue
        stats[cid] = {k: (row.get(k) or 0) for k in _STAT_KEYS}
    shorts = summary.get("shorts") or {}
    return stats, int(shorts.get("cut_total") or 0), int(shorts.get("uploaded_total") or 0)


def _aggregate_legacy() -> tuple[dict, int, int]:
    """Per-channel aggregates computed in-app by pulling the whole videos, audits
    and shorts_clips tables (~2 MB egress).

    NOT a maintained twin of the SQL — do not hand-sync counting-rule changes here.
    It is kept ONLY as (a) the automatic fallback when the RPC errors and (b) the
    correctness oracle that tests/test_dashboard_parity_live.py checks the RPC
    against on live data. Once the RPC is validated against non-zero time-window
    data (applied_today/7d/delta_views_7d), this can be deleted; until then the
    parity test guards against drift."""
    now = _now()
    today_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
    seven_d_ago = now - timedelta(days=7)

    # Pull all videos — the table can exceed Supabase's 1000-row page cap
    # (~20 pages here). Fetch the first page together with an exact row count,
    # then fetch the remaining pages CONCURRENTLY: Supabase clients are
    # per-thread (see app/db.py), so each worker gets its own hardened client.
    VIDEO_COLS = "id,channel_id,view_count,privacy_status,is_short"
    first_page = (
        supabase().table("videos").select(VIDEO_COLS, count="exact")
        .range(0, 999).execute()
    )
    videos: list[dict] = list(first_page.data or [])
    total_video_rows = first_page.count if first_page.count is not None else len(videos)
    if total_video_rows > 1000:
        offsets = list(range(1000, total_video_rows, 1000))

        def _fetch_video_page(off: int) -> list[dict]:
            return (
                supabase().table("videos").select(VIDEO_COLS)
                .range(off, off + 999).execute()
            ).data or []

        with ThreadPoolExecutor(max_workers=min(5, len(offsets))) as ex:
            for page in ex.map(_fetch_video_page, offsets):
                videos.extend(page)

    video_to_channel: dict[str, str] = {v["id"]: v["channel_id"] for v in videos}
    # Only public (or legacy null privacy_status) videos are auditable.
    public_video_ids: set[str] = {
        v["id"] for v in videos
        if v.get("privacy_status") is None or v.get("privacy_status") == "public"
    }
    shorts_video_ids: set[str] = {
        v["id"] for v in videos
        if v["id"] in public_video_ids and v.get("is_short")
    }

    stats: dict[str, dict] = {}

    def _s(cid: str) -> dict:
        return stats.setdefault(cid, _empty_stat())

    for v in videos:
        if v["id"] not in public_video_ids:
            continue
        s = _s(v["channel_id"])
        s["video_count"] += 1
        if v.get("is_short"):
            s["shorts_count"] += 1
        else:
            s["regular_count"] += 1

    # ALL audit records, newest first, paginated over the whole (small) table;
    # latest-per-video is derived in Python.
    audits_state: list[dict] = []
    ROW_PAGE = 1000
    aud_offset = 0
    while True:
        page = (
            supabase().table("audits")
            .select("id,video_id,status,applied_at,created_at,view_count_at_apply")
            .order("created_at", desc=True)
            .range(aud_offset, aud_offset + ROW_PAGE - 1)
            .execute()
        ).data or []
        audits_state.extend(page)
        if len(page) < ROW_PAGE:
            break
        aud_offset += ROW_PAGE

    latest_per_video: dict[str, dict] = {}
    for a in audits_state:
        latest_per_video.setdefault(a["video_id"], a)

    # audited / pending / applied_latest — PUBLIC videos, by their LATEST audit.
    for vid, a in latest_per_video.items():
        if vid not in public_video_ids:
            continue
        ch = video_to_channel.get(vid)
        if not ch:
            continue
        s = _s(ch)
        if vid in shorts_video_ids:
            s["audited_shorts"] += 1
        else:
            s["audited_regular"] += 1
        if a["status"] == "pending":
            s["pending_count"] += 1
        elif a["status"] == "applied":
            s["applied_latest"] += 1

    # applied_today/7d/total + delta_views_7d — RAW applied rows, ALL videos.
    cur_views = {v["id"]: (v.get("view_count") or 0) for v in videos}
    for a in audits_state:
        if a["status"] != "applied":
            continue
        ch = video_to_channel.get(a["video_id"])
        if not ch:
            continue
        s = _s(ch)
        s["applied_total"] += 1
        ap = _parse_iso(a.get("applied_at"))
        if ap and ap >= today_start:
            s["applied_today"] += 1
        if ap and ap >= seven_d_ago:
            s["applied_7d"] += 1
            base = a.get("view_count_at_apply") or 0
            s["delta_views_7d"] += cur_views.get(a["video_id"], 0) - base

    # Shorts totals (paginated; table can exceed the 1000-row cap).
    shorts_clips: list[dict] = []
    clip_offset = 0
    while True:
        page = (
            supabase().table("shorts_clips")
            .select("upload_status")
            .range(clip_offset, clip_offset + 999)
            .execute()
        ).data or []
        shorts_clips.extend(page)
        if len(page) < 1000:
            break
        clip_offset += 1000
    cut_total = len(shorts_clips)
    uploaded_total = sum(1 for c in shorts_clips if c.get("upload_status") == "UPLOADED")

    return stats, cut_total, uploaded_total


def _compute_dashboard():
    """One-shot payload for the home page.

    Per-channel aggregates come from the RPC path (DASHBOARD_USE_RPC) or the
    in-app legacy path; enrichment, KPIs, health, pipeline, activity feed and
    quota are shared and path-agnostic.

    Returns:
      channels: per-channel rows enriched with pending/applied/Δviews/autopilot pace
      kpis: global counts (channels, total pending, applied today, applied 7d, quota used)
      quota: today's used + safety + 7d sparkline (per-day usage)
    """
    now = _now()

    channels = (
        supabase().table("channels").select(
            "id,name,handle,last_synced_at,default_language,"
            "autopilot_enabled,autopilot_paused_reason,autopilot_daily_cap,autopilot_last_tick_at,"
            "analytics_authorized"
        ).execute()
    ).data or []

    if settings.DASHBOARD_USE_RPC:
        try:
            stats, shorts_cut_total, shorts_uploaded_total = _aggregate_rpc()
        except Exception:
            # RPC missing (unmigrated env) or errored — fall back to the in-app
            # path so the dashboard never breaks, just costs more egress.
            log.warning("dashboard RPC failed; falling back to legacy aggregation", exc_info=True)
            stats, shorts_cut_total, shorts_uploaded_total = _aggregate_legacy()
    else:
        stats, shorts_cut_total, shorts_uploaded_total = _aggregate_legacy()

    # ── Per-channel enrichment ────────────────────────────────────────────
    enriched = []
    for c in channels:
        cid = c["id"]
        s = stats.get(cid) or _empty_stat()
        last_sync = _parse_iso(c.get("last_synced_at"))
        hours_since_sync = None
        if last_sync:
            hours_since_sync = round((now - last_sync).total_seconds() / 3600.0, 2)
        enriched.append({
            **c,
            "video_count": s["video_count"],
            "regular_count": s["regular_count"],
            "shorts_count": s["shorts_count"],
            "audited_regular": s["audited_regular"],
            "audited_shorts": s["audited_shorts"],
            "pending_count": s["pending_count"],
            "applied_today": s["applied_today"],
            "applied_7d": s["applied_7d"],
            "applied_total": s["applied_total"],
            "delta_views_7d": s["delta_views_7d"],
            "hours_since_sync": hours_since_sync,
        })

    # ── System health ─────────────────────────────────────────────────────
    running_count = sum(1 for c in enriched if c.get("autopilot_enabled") and not c.get("autopilot_paused_reason"))
    paused_count = sum(1 for c in enriched if c.get("autopilot_paused_reason"))
    enabled_count = sum(1 for c in enriched if c.get("autopilot_enabled"))
    sync_hours = [c["hours_since_sync"] for c in enriched if c["hours_since_sync"] is not None]
    worst_sync_hours = round(max(sync_hours), 1) if sync_hours else None

    # ── Pipeline funnel ───────────────────────────────────────────────────
    # Globals are summed from the per-channel aggregates. audited/applied use the
    # latest-audit view (audited_regular+shorts / applied_latest) so numerator and
    # denominator stay consistent with the per-channel cards.
    total_videos_global = sum(s["video_count"] for s in stats.values())
    total_audited_global = sum(s["audited_regular"] + s["audited_shorts"] for s in stats.values())
    total_not_audited_global = max(0, total_videos_global - total_audited_global)
    total_applied_global = sum(s["applied_latest"] for s in stats.values())
    applied_7d_total = sum(s["applied_7d"] for s in stats.values())
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
        "pending_total": sum(s["pending_count"] for s in stats.values()),
        "applied_today_total": sum(s["applied_today"] for s in stats.values()),
        "applied_7d_total": applied_7d_total,
        "delta_views_7d_total": sum(s["delta_views_7d"] for s in stats.values()),
        "shorts_cut_total": shorts_cut_total,
        "shorts_uploaded_total": shorts_uploaded_total,
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
        "pending": sum(s["pending_count"] for s in stats.values()),
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
