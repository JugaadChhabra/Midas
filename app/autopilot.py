import logging
import math
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db import supabase
from app import quota
from app.audits import audit_video, validate_audit, apply_audit_internal
from app.sync import sync_channel
from app.youtube_client import TokenExpiredError
from app.embeddings import embed_video
from app.playlists import join_pass

log = logging.getLogger("midas.autopilot")
router = APIRouter(tags=["autopilot"])

# In-memory consecutive-failure counter per channel. Reset on successful apply.
_failure_counts: dict[str, int] = defaultdict(int)

# Set when YouTube returns quotaExceeded; cleared after quota resets.
_yt_quota_exhausted_until: datetime | None = None

_PACIFIC = ZoneInfo("America/Los_Angeles")


def _next_yt_quota_reset() -> datetime:
    """Next midnight Pacific Time (when YouTube daily quota resets)."""
    now_pacific = datetime.now(_PACIFIC)
    next_midnight = (now_pacific + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return next_midnight.astimezone(timezone.utc)


# Per-tick cost gates
COST_STATS_FETCH = 1
COST_VIDEO_UPDATE = 50
APPLY_COST = COST_STATS_FETCH + COST_VIDEO_UPDATE  # 51


UNSAFE_MODELS = {
    # "google/gemini-2.0-flash-001",
    # Any model id ending with ":free" is also rejected (checked separately)
}


def _is_unsafe_model(model_id: str) -> bool:
    return model_id in UNSAFE_MODELS or model_id.endswith(":free")


def _today_start_iso() -> str:
    today = datetime.now(timezone.utc).date()
    return datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).isoformat()


def _applies_today(channel_id: str) -> int:
    video_ids = [
        v["id"] for v in (
            supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
        )
    ]
    if not video_ids:
        return 0
    res = (
        supabase().table("audits")
        .select("id")
        .eq("status", "applied")
        .gte("applied_at", _today_start_iso())
        .in_("video_id", video_ids)
        .execute()
    )
    return len(res.data or [])


def _next_video_for_channel(channel_id: str) -> dict | None:
    """Most-recently-published public video that has no audit yet (or whose latest audit was a transient failure).

    Walks newest → oldest so freshly uploaded videos are optimized first.
    """
    candidates = (
        supabase().table("videos")
        .select("*")
        .eq("channel_id", channel_id)
        .order("published_at", desc=True)
        .execute()
    ).data or []

    if not candidates:
        return None

    # Only fetch audits for this channel's videos — avoids cross-channel noise
    # and prevents Supabase's 1000-row default cap from silently truncating results
    # when the audits table is large.
    candidate_ids = [v["id"] for v in candidates]
    audits = (
        supabase().table("audits")
        .select("video_id,status,created_at")
        .in_("video_id", candidate_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    # Latest audit per video
    latest: dict[str, str] = {}
    for a in audits:
        if a["video_id"] not in latest:
            latest[a["video_id"]] = a["status"]

    # Retry only if last audit was 'failed' or video was never audited.
    skip_statuses = {"applied", "pending", "quarantined", "blocked_test_and_compare", "shadow_pending"}
    blocked_ids = {vid for vid, st in latest.items() if st in skip_statuses}

    for v in candidates:
        if v["id"] in blocked_ids:
            continue
        # Only public videos qualify for audit. Older rows synced before
        # privacy_status existed are treated as public to avoid stalling.
        privacy = v.get("privacy_status")
        if privacy is not None and privacy != "public":
            continue
        return v
    return None


def _pause(channel_id: str, reason: str):
    log.warning("Pausing autopilot for %s: %s", channel_id, reason)
    supabase().table("channels").update({"autopilot_paused_reason": reason}).eq("id", channel_id).execute()


def _touch_tick(channel_id: str):
    supabase().table("channels").update({
        "autopilot_last_tick_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", channel_id).execute()


def tick():
    """One pass of the autopilot loop. Processes at most one video and returns."""
    global _yt_quota_exhausted_until
    try:
        # 1. Quota gate — internal estimate
        if not quota.can_afford(APPLY_COST):
            log.info("Autopilot deferred: quota remaining %d < %d", quota.units_remaining(), APPLY_COST)
            return

        # 1b. YouTube-confirmed quota exhaustion gate
        if _yt_quota_exhausted_until is not None:
            now = datetime.now(timezone.utc)
            if now < _yt_quota_exhausted_until:
                log.info(
                    "Autopilot dormant: YouTube quota exhausted until %s",
                    _yt_quota_exhausted_until.strftime("%Y-%m-%d %H:%M UTC"),
                )
                return
            _yt_quota_exhausted_until = None
            log.info("YouTube quota window reset; resuming autopilot")

        # 2. Pick next channel (round-robin by last_tick_at; null treated as oldest)
        channels = (
            supabase().table("channels")
            .select("*")
            .eq("autopilot_enabled", True)
            .is_("autopilot_paused_reason", "null")
            .execute()
        ).data or []
        if not channels:
            return
        # Sort: null last_tick_at first (never ticked → highest priority), then oldest tick
        channels.sort(key=lambda c: (c.get("autopilot_last_tick_at") or ""))
        ch = channels[0]
        channel_id = ch["id"]

        # 3. Resync if stale (>6h)
        last_synced = ch.get("last_synced_at")
        needs_sync = True
        if last_synced:
            try:
                dt = datetime.fromisoformat(last_synced.replace("Z", "+00:00"))
                needs_sync = (datetime.now(timezone.utc) - dt) > timedelta(hours=6)
            except ValueError:
                pass

        if needs_sync:
            # Estimate sync cost: 1 (channels.list) + ceil(known/50) for playlist pages + ceil(known/50) for video.list
            known_count = (
                supabase().table("videos").select("id", count="exact").eq("channel_id", channel_id).execute()
            ).count or 0
            estimated = 1 + 2 * max(1, math.ceil((known_count or 50) / 50))
            if not quota.can_afford(estimated + APPLY_COST):
                log.info("Autopilot skipping sync for %s: would not leave room for an apply", channel_id)
                _touch_tick(channel_id)
                return
            try:
                sync_channel(channel_id)
            except TokenExpiredError:
                log.warning("OAuth token expired or revoked for %s during sync; pausing", channel_id)
                _pause(channel_id, "token_expired")
                return
            except Exception as e:
                log.exception("Sync failed for %s: %s", channel_id, e)
                _failure_counts[channel_id] += 1
                if _failure_counts[channel_id] >= 3:
                    _pause(channel_id, "repeated_failures")
                _touch_tick(channel_id)
                return

        # 4. Daily cap check
        cap = ch.get("autopilot_daily_cap") or 10
        applies = _applies_today(channel_id)
        if applies >= cap:
            log.info("Channel %s at daily cap (%d/%d)", channel_id, applies, cap)
            _touch_tick(channel_id)
            return

        # 5. Pick next video
        video = _next_video_for_channel(channel_id)
        if not video:
            log.info("Channel %s has no remaining unaudited videos", channel_id)
            _touch_tick(channel_id)
            return

        # 6. Model safety gate
        if _is_unsafe_model(settings.AUDIT_MODEL):
            _pause(channel_id, "unsafe_model")
            return

        # 7. Run audit
        try:
            audit_row = audit_video(video["id"])
        except TokenExpiredError:
            log.warning("OAuth token expired or revoked for %s during audit; pausing", channel_id)
            _pause(channel_id, "token_expired")
            return
        except Exception as e:
            log.exception("Audit failed for %s: %s", video["id"], e)
            _failure_counts[channel_id] += 1
            if _failure_counts[channel_id] >= 3:
                _pause(channel_id, "repeated_failures")
            _touch_tick(channel_id)
            return

        # Stamp which prompt version generated this audit
        try:
            live_ver = (
                supabase().table("prompt_versions")
                .select("id")
                .eq("channel_id", channel_id)
                .eq("status", "live")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            ).data
            if live_ver and audit_row.get("id"):
                supabase().table("audits").update(
                    {"prompt_version_id": live_ver[0]["id"]}
                ).eq("id", audit_row["id"]).execute()
        except Exception as e:
            log.warning("Failed to stamp prompt_version_id for audit %s: %s", audit_row.get("id"), e)

        # 8. Validate
        ok, reason = validate_audit(audit_row)
        if not ok:
            log.warning("Quarantining audit %s: %s", audit_row.get("id"), reason)
            supabase().table("audits").update({
                "status": "quarantined",
                "ai_reasoning": (audit_row.get("ai_reasoning") or "") + f"\n[autopilot] quarantined: {reason}",
            }).eq("id", audit_row["id"]).execute()
            _touch_tick(channel_id)
            return

        # 9. Re-check quota right before apply
        if not quota.can_afford(APPLY_COST):
            log.info("Quota dipped during audit; deferring apply of %s", audit_row.get("id"))
            _touch_tick(channel_id)
            return

        # 10. Apply
        try:
            apply_audit_internal(audit_row["id"])
            _failure_counts[channel_id] = 0
            log.info("Autopilot applied audit %s for video %s", audit_row["id"], video["id"])
            if not video.get("is_short"):
                try:
                    if embed_video(video["id"]):
                        join_pass(channel_id, video["id"])
                except Exception as e:
                    log.warning("Embed/playlist pass failed for %s: %s", video["id"], e)
        except HTTPException as e:
            log.warning("Apply HTTPException for %s: %s", audit_row["id"], e.detail)
            if e.detail == "blocked_test_and_compare":
                log.info("Skipping video %s: active Test & Compare experiment on YouTube", video["id"])
            elif e.detail == "youtube_quota_exceeded":
                _yt_quota_exhausted_until = _next_yt_quota_reset()
                log.warning(
                    "YouTube quota exhausted; autopilot dormant until %s",
                    _yt_quota_exhausted_until.strftime("%Y-%m-%d %H:%M UTC"),
                )
            elif e.detail == "token_expired":
                log.warning("OAuth token expired or revoked for %s; pausing autopilot", channel_id)
                _pause(channel_id, "token_expired")
            else:
                _failure_counts[channel_id] += 1
                if _failure_counts[channel_id] >= 3:
                    _pause(channel_id, "repeated_failures")
        except Exception as e:
            log.exception("Apply failed for %s: %s", audit_row["id"], e)
            _failure_counts[channel_id] += 1
            if _failure_counts[channel_id] >= 3:
                _pause(channel_id, "repeated_failures")

        _touch_tick(channel_id)

    except Exception as e:
        log.exception("Autopilot tick crashed: %s", e)


# ── HTTP endpoints ─────────────────────────────────────────────────────

@router.post("/channels/{channel_id}/autopilot/resume")
def resume_autopilot(channel_id: str):
    supabase().table("channels").update({"autopilot_paused_reason": None}).eq("id", channel_id).execute()
    _failure_counts[channel_id] = 0
    return {"ok": True}


@router.get("/channels/{channel_id}/autopilot/log")
def autopilot_log(channel_id: str):
    videos = (
        supabase().table("videos").select("id,title").eq("channel_id", channel_id).execute().data or []
    )
    title_by_id = {v["id"]: v["title"] for v in videos}
    video_ids = list(title_by_id.keys())
    audits = []
    if video_ids:
        audits = (
            supabase().table("audits")
            .select("id,video_id,status,applied_at,created_at,ai_reasoning")
            .in_("video_id", video_ids)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        ).data or []
    applies = _applies_today(channel_id)
    ch = supabase().table("channels").select("autopilot_daily_cap,autopilot_paused_reason,autopilot_enabled").eq("id", channel_id).single().execute().data or {}
    return {
        "applies_today": applies,
        "daily_cap": ch.get("autopilot_daily_cap"),
        "paused_reason": ch.get("autopilot_paused_reason"),
        "enabled": ch.get("autopilot_enabled"),
        "items": [
            {
                "audit_id": a["id"],
                "video_id": a["video_id"],
                "video_title": title_by_id.get(a["video_id"]),
                "status": a["status"],
                "applied_at": a.get("applied_at"),
                "created_at": a.get("created_at"),
                "note": a.get("ai_reasoning"),
            } for a in audits
        ],
    }
