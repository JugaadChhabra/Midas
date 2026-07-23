import logging
import math
import httpx
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db import supabase
from app.channel_audits import audits_for_channel
from app import quota
from app.audits import audit_video, validate_audit, apply_audit_internal
from app.sync import sync_channel, refresh_stats
from app.youtube_client import TokenExpiredError
from app.embeddings import embed_video
from app.shorts.runner import active_job_count

log = logging.getLogger("midas.autopilot")
router = APIRouter(tags=["autopilot"])

# In-memory consecutive-failure counter per channel. Reset on successful apply.
_failure_counts: dict[str, int] = defaultdict(int)

# Consecutive timeout counter per video. After 2 timeouts we insert a failed
# audit row so the video is deprioritized and the next video can be tried.
_video_timeout_counts: dict[str, int] = defaultdict(int)

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

# How often to run a full (snippet-rebuilding) sync instead of an incremental
# one. Incremental syncs miss edits to old titles/tags, so we do a full pass
# this often to repair them.
FULL_SYNC_INTERVAL = timedelta(days=3)


def _needs_full_sync(channel: dict) -> bool:
    """True if this channel has never had a full sync or the last one is older
    than FULL_SYNC_INTERVAL."""
    last = channel.get("last_full_synced_at")
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return True
    return (datetime.now(timezone.utc) - dt) > FULL_SYNC_INTERVAL


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
    # Applied audits today for this channel. Uses the channel-scoped accessor
    # (join to videos) so the daily-cap gate is never undercounted by the old
    # all-video-ids form's 1000-row truncation.
    res = (
        audits_for_channel(channel_id, "id")
        .eq("status", "applied")
        .gte("applied_at", _today_start_iso())
        .execute()
    )
    return len(res.data or [])


def _next_video_for_channel(channel_id: str) -> dict | None:
    """Most-recently-published public video that has no audit yet (or whose latest audit was a transient failure).

    Walks newest → oldest so freshly uploaded videos are optimized first.
    """
    # Only the columns the picker filters on and the caller reads (id for the
    # audit call, is_short for the post-apply embed gate, privacy_status for the
    # eligibility filter). `videos` is a wide table (description/tags/snippet/…)
    # and this runs every autopilot tick, so select("*") here egressed KBs per row
    # for nothing — audit_video() re-fetches the full row by id when it needs it.
    candidates = (
        supabase().table("videos")
        .select("id,is_short,privacy_status")
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


# Upper bound (seconds) on source-video length for autopilot shorts, from
# settings (env SHORTS_MAX_SOURCE_SECONDS, default 3600). Videos at or above it
# are never auto-cut. Set to 0 to disable the length cap entirely. Either way,
# only videos with a known, non-NULL duration_seconds are eligible — never cut a
# video whose length we don't know. The manual "Make shorts" button is NOT bound
# by this.
MAX_SHORTS_SOURCE_SECONDS = settings.SHORTS_MAX_SOURCE_SECONDS

# A source whose ONLY shorts_jobs are FAILED is retried on later ticks — early
# failures are often transient (e.g. a PO-token download error that "This video
# is not available" masks). But a video that has failed this many times is left
# alone, so a permanently-broken source can never wedge the queue (the picker
# returns the newest eligible video each tick and would otherwise retry the same
# poison video forever, starving every older one).
MAX_SHORTS_RETRY_ATTEMPTS = 3


def _next_uncut_video_for_channel(channel_id: str) -> dict | None:
    """Newest-published public long-form video under MAX_SHORTS_SOURCE_SECONDS
    that is eligible for an autopilot cut.

    Long-form only (is_short=False) and under the duration cap (excludes
    compilations); shorts are never re-cut into shorts. A video with a
    non-FAILED shorts_jobs row (done or in-flight) is skipped — re-cutting a
    successful cut is a manual action. A video whose only jobs are FAILED is
    retried until it hits MAX_SHORTS_RETRY_ATTEMPTS.
    """
    # is_short / duration_seconds are server-side WHERE filters (not read back);
    # the caller only uses video["id"]. privacy_status is read by the loop below.
    # Narrowed from select("*") — this runs every tick over a wide table.
    q = (
        supabase().table("videos")
        .select("id,privacy_status")
        .eq("channel_id", channel_id)
        .eq("is_short", False)
    )
    if MAX_SHORTS_SOURCE_SECONDS > 0:
        # `.lt` also drops NULL durations (PostgREST excludes them) — the safe
        # default: never cut a video whose length we don't know.
        q = q.lt("duration_seconds", MAX_SHORTS_SOURCE_SECONDS)
    else:
        # No length cap, but still require a known duration.
        q = q.not_.is_("duration_seconds", "null")
    candidates = q.order("published_at", desc=True).execute().data or []
    if not candidates:
        return None
    candidate_ids = [v["id"] for v in candidates]
    jobs = (
        supabase().table("shorts_jobs")
        .select("source_video_id,status")
        .eq("channel_id", channel_id)
        .in_("source_video_id", candidate_ids)
        .execute()
    ).data or []
    settled: set[str] = set()          # has a non-FAILED job (done or in-flight): never re-cut
    failed_counts: dict[str, int] = defaultdict(int)
    for j in jobs:
        sid = j.get("source_video_id")
        if not sid:
            continue
        if (j.get("status") or "").upper() == "FAILED":
            failed_counts[sid] += 1
        else:
            settled.add(sid)
    for v in candidates:
        vid = v["id"]
        if vid in settled:
            continue
        if failed_counts[vid] >= MAX_SHORTS_RETRY_ATTEMPTS:
            continue
        privacy = v.get("privacy_status")
        if privacy is not None and privacy != "public":
            continue
        return v
    return None


def _shorts_made_today(channel_id: str) -> int:
    res = (
        supabase().table("shorts_jobs")
        .select("id")
        .eq("channel_id", channel_id)
        .eq("autopilot_generated", True)
        .gte("created_at", _today_start_iso())
        .execute()
    )
    return len(res.data or [])


def _run_shorts_action(ch: dict) -> None:
    """Enqueue NAS shorts cuts for this channel's language folder.

    No-op unless the channel has a nas_folder set. The shorts dispatcher
    (throttled by SHORTS_MAX_CONCURRENT_JOBS) drains the queue; enqueue's own
    in-flight dedup makes re-ticks idempotent, so we enqueue every uncut file
    and let the cap pace the actual cutting.
    """
    folder = ch.get("nas_folder")
    if not folder:
        return
    if active_job_count() >= settings.SHORTS_MAX_CONCURRENT_JOBS:
        return  # queue already full; a later tick tops it up
    # Lazy import: keeps the NAS/cutter dependency out of module import time.
    from app.shorts.nas_source import enqueue_language_jobs
    try:
        n = enqueue_language_jobs(
            folder, channel_id=ch["id"], autopilot=True,
            cut_mode=ch.get("shorts_cut_mode") or "highlights",
            camera_motion=ch.get("shorts_camera_motion") or "calm",
        )
    except ValueError:
        log.warning("Autopilot shorts: channel %s has unknown nas_folder %r",
                    ch["id"], folder)
        return
    if n:
        log.info("Autopilot shorts: enqueued %d NAS job(s) for %s (folder %s)",
                 n, ch["id"], folder)


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
        # 1. Quota gate — internal estimate (disabled: letting YouTube's quotaExceeded be the signal)
        # if not quota.can_afford(APPLY_COST):
        #     log.info("Autopilot deferred: quota remaining %d < %d", quota.units_remaining(), APPLY_COST)
        #     return

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
            .or_("autopilot_enabled.eq.true,autopilot_shorts_enabled.eq.true")
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
            # known_count = (
            #     supabase().table("videos").select("id", count="exact").eq("channel_id", channel_id).execute()
            # ).count or 0
            # estimated = 1 + 2 * max(1, math.ceil((known_count or 50) / 50))
            # if not quota.can_afford(estimated + APPLY_COST):
            #     log.info("Autopilot skipping sync for %s: would not leave room for an apply", channel_id)
            #     _touch_tick(channel_id)
            #     return
            try:
                if _needs_full_sync(ch):
                    # Full pass every FULL_SYNC_INTERVAL: rebuilds every snippet so
                    # edits to old titles/tags/privacy are picked up, and refreshes
                    # stats in the same call (no separate refresh_stats needed).
                    sync_channel(channel_id, full=True)
                else:
                    # Incremental: only discovers genuinely new uploads (cheap).
                    sync_channel(channel_id)
                    # Incremental sync no longer re-lists already-stored videos, so
                    # refresh their counts + privacy_status here (statistics+status,
                    # 1 unit per 50). Catches view drift and privacy flips between
                    # full passes.
                    refresh_stats(channel_id)
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

        # Shorts autopilot — independent of the metadata-audit path. Enqueues at
        # most one cut per tick, gated by active_job_count vs the concurrency cap.
        if ch.get("autopilot_shorts_enabled"):
            try:
                _run_shorts_action(ch)
            except Exception as e:
                log.exception("Shorts autopilot failed for %s: %s", channel_id, e)

        # The metadata-audit path (daily cap → pick → audit → apply) runs only for
        # channels with metadata autopilot enabled. Shorts-only channels stop here.
        if not ch.get("autopilot_enabled"):
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
        except httpx.TimeoutException as e:
            vid = video["id"]
            _video_timeout_counts[vid] += 1
            if _video_timeout_counts[vid] >= 2:
                log.warning(
                    "Audit timed out for %s %d times; marking failed to skip",
                    vid, _video_timeout_counts[vid],
                )
                _video_timeout_counts[vid] = 0
                try:
                    supabase().table("audits").insert({
                        "video_id": vid,
                        "status": "failed",
                        "ai_reasoning": f"[autopilot] repeated read timeouts from OpenRouter",
                    }).execute()
                except Exception:
                    pass
            else:
                log.warning("Audit timed out for %s (%s); skipping without penalty", vid, e)
            _touch_tick(channel_id)
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

        # 9. Re-check quota right before apply (disabled: letting YouTube's quotaExceeded be the signal)
        # if not quota.can_afford(APPLY_COST):
        #     log.info("Quota dipped during audit; deferring apply of %s", audit_row.get("id"))
        #     _touch_tick(channel_id)
        #     return

        # 10. Apply
        try:
            apply_audit_internal(audit_row["id"])
            _failure_counts[channel_id] = 0
            log.info("Autopilot applied audit %s for video %s", audit_row["id"], video["id"])
            if not video.get("is_short"):
                try:
                    embed_video(video["id"])
                    # Playlist allocation skipped — workflow under review
                    # join_pass(channel_id, video["id"])
                except Exception as e:
                    log.warning("Embed failed for %s: %s", video["id"], e)
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
    # The 50 latest audits for THIS channel, with the video title, in one query
    # via the channel-scoped accessor. Replaces an older form that pulled every
    # one of the channel's videos on each 30s poll (heavy egress) and truncated
    # at Supabase's 1000-row cap (large channels' newer audits never showed).
    audits = (
        audits_for_channel(
            channel_id,
            "id,video_id,status,applied_at,created_at,ai_reasoning",
            video_columns="channel_id,title",
        )
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
                "video_title": (a.get("videos") or {}).get("title"),
                "status": a["status"],
                "applied_at": a.get("applied_at"),
                "created_at": a.get("created_at"),
                "note": a.get("ai_reasoning"),
            } for a in audits
        ],
    }
