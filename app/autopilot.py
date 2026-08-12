import logging
import math
import httpx
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter

from app.config import settings
from app.db import supabase
from app.channel_audits import audits_for_channel
from app import quota
from app.audits import audit_video, validate_audit, apply_audit_internal
from app.apply_outcome import ApplyError, ApplyOutcome
from app.sync import sync_channel, refresh_stats
from app.youtube_client import TokenExpiredError
from app.embeddings import embed_video
from app.metrics_poll import ACTIVE_MEASUREMENT_STATUSES
from app.status_vocab import (
    AUDIT_PICKER_SKIP_STATUSES,
    AUTO_EXPIRE_PAUSE_REASONS,
    AuditStatus,
    PausedReason,
)
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
        .eq("status", AuditStatus.APPLIED)
        .gte("applied_at", _today_start_iso())
        .execute()
    )
    return len(res.data or [])


def _next_video_for_channel(channel_id: str) -> dict | None:
    """Most-recently-published public video that has no audit yet (or whose latest audit was a transient failure).

    Walks newest → oldest so freshly uploaded videos are optimized first.
    """
    # Fast path: compute the pick in Postgres (next_audit_candidate) and get ONE
    # row back instead of the whole videos + audits lists. This was the dominant
    # Supabase egress source — hundreds of KB per tick on big channels. Falls back
    # to the in-app scan below if disabled or if the RPC errors.
    if settings.AUTOPILOT_PICKER_USE_RPC:
        try:
            rows = supabase().rpc("next_audit_candidate", {"p_channel_id": channel_id}).execute().data or []
            return rows[0] if rows else None
        except Exception:
            log.warning("next_audit_candidate RPC failed; falling back to in-app picker", exc_info=True)

    # In-app oracle / fallback. `videos` is a wide table (description/tags/snippet/…)
    # so we select only the 3 columns the picker filters on and the caller reads.
    # The id tie-break makes the pick deterministic and matches the RPC's ordering.
    candidates = (
        supabase().table("videos")
        .select("id,is_short,privacy_status")
        .eq("channel_id", channel_id)
        .order("published_at", desc=True)
        .order("id")
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
        .select("video_id,status,created_at,measurement_status")
        .in_("video_id", candidate_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    # Latest audit per video (keep the whole row — we filter on two columns).
    latest: dict[str, dict] = {}
    for a in audits:
        if a["video_id"] not in latest:
            latest[a["video_id"]] = a

    # Retry only if last audit was 'failed' or video was never audited.
    skip_statuses = AUDIT_PICKER_SKIP_STATUSES
    # Also exclude videos mid-measurement (CIL §1.7): re-auditing would change
    # the packaging under an in-flight CTR experiment and confound the verdict.
    blocked_ids = {
        vid for vid, a in latest.items()
        if a["status"] in skip_statuses
        or a.get("measurement_status") in ACTIVE_MEASUREMENT_STATUSES
    }

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
    supabase().table("channels").update({
        "autopilot_paused_reason": reason,
        "autopilot_paused_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", channel_id).execute()


# Only 'repeated_failures' auto-expires after the cooldown — it reflects a
# transient burst that may have cleared. token_expired / unsafe_model need
# explicit human action (reconnect Google / fix the model config), so they stay
# latched until an operator resumes.
_AUTO_EXPIRE_REASONS = AUTO_EXPIRE_PAUSE_REASONS


def _clear_expired_pauses() -> None:
    """Auto-unpause channels whose transient pause has outlived the cooldown.

    Called at the top of the channel picker. A cleared channel gets a fresh
    failure budget; if it fails 3 more times it simply re-pauses — cooldown-based
    backoff instead of a permanent latch that needs a human."""
    cooldown = settings.AUTOPILOT_PAUSE_COOLDOWN_MINUTES
    if cooldown <= 0:
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown)).isoformat()
    for reason in _AUTO_EXPIRE_REASONS:
        cleared = (supabase().table("channels")
                   .update({"autopilot_paused_reason": None, "autopilot_paused_at": None})
                   .eq("autopilot_paused_reason", reason)
                   .lt("autopilot_paused_at", cutoff)
                   .execute().data) or []
        for c in cleared:
            _failure_counts[c["id"]] = 0
            log.info("Auto-unpaused %s: '%s' cooldown (%dm) elapsed", c["id"], reason, cooldown)


def _touch_tick(channel_id: str):
    supabase().table("channels").update({
        "autopilot_last_tick_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", channel_id).execute()


def _record_failure(channel_id: str) -> None:
    """Bump the channel's consecutive-failure counter and pause it once it hits the
    limit. The pause-on-repeated-failures rule, in one place (was inline ×4)."""
    _failure_counts[channel_id] += 1
    if _failure_counts[channel_id] >= 3:
        _pause(channel_id, PausedReason.REPEATED_FAILURES)


def _quota_dormant() -> bool:
    """True while YouTube's daily quota is known-exhausted (autopilot idles). Clears
    the window and returns False once it has passed."""
    global _yt_quota_exhausted_until
    if _yt_quota_exhausted_until is None:
        return False
    if datetime.now(timezone.utc) < _yt_quota_exhausted_until:
        log.info(
            "Autopilot dormant: YouTube quota exhausted until %s",
            _yt_quota_exhausted_until.strftime("%Y-%m-%d %H:%M UTC"),
        )
        return True
    _yt_quota_exhausted_until = None
    log.info("YouTube quota window reset; resuming autopilot")
    return False


def _channel_has_work(c: dict) -> bool:
    """True if the channel can run at least one path this tick. The pause is
    path-specific: it gates the metadata-audit path only. Shorts (NAS cutting)
    are decoupled — they run whenever autopilot_shorts_enabled, regardless of an
    audit-side pause, so an audit blip never silences a full NAS folder."""
    audit_ok = c.get("autopilot_enabled") and not c.get("autopilot_paused_reason")
    shorts_ok = c.get("autopilot_shorts_enabled")
    return bool(audit_ok or shorts_ok)


def _pick_next_channel() -> dict | None:
    """The eligible channel that has waited longest since its last tick
    (round-robin; never-ticked first). None if none are eligible.

    Auto-clears expired transient pauses first so a recovered channel rejoins
    the rotation without a manual Resume."""
    _clear_expired_pauses()
    channels = (
        supabase().table("channels")
        .select("*")
        .or_("autopilot_enabled.eq.true,autopilot_shorts_enabled.eq.true")
        .execute()
    ).data or []
    eligible = [c for c in channels if _channel_has_work(c)]
    if not eligible:
        return None
    # null last_tick_at first (never ticked → highest priority), then oldest tick
    eligible.sort(key=lambda c: (c.get("autopilot_last_tick_at") or ""))
    return eligible[0]


def _resync_if_stale(ch: dict) -> bool:
    """Resync the channel if its data is stale (>6h). Returns True if the tick should
    proceed, False if it should stop (token expired, or sync failed)."""
    channel_id = ch["id"]
    last_synced = ch.get("last_synced_at")
    needs_sync = True
    if last_synced:
        try:
            dt = datetime.fromisoformat(last_synced.replace("Z", "+00:00"))
            needs_sync = (datetime.now(timezone.utc) - dt) > timedelta(hours=6)
        except ValueError:
            pass
    if not needs_sync:
        return True
    try:
        if _needs_full_sync(ch):
            # Full pass every FULL_SYNC_INTERVAL: rebuilds every snippet so edits to
            # old titles/tags/privacy are picked up, and refreshes stats in the same
            # call (no separate refresh_stats needed).
            sync_channel(channel_id, full=True)
        else:
            # Incremental: only discovers genuinely new uploads (cheap). It no longer
            # re-lists stored videos, so refresh their counts + privacy_status here to
            # catch view drift and privacy flips between full passes.
            sync_channel(channel_id)
            refresh_stats(channel_id)
        return True
    except TokenExpiredError:
        log.warning("OAuth token expired or revoked for %s during sync; pausing", channel_id)
        _pause(channel_id, PausedReason.TOKEN_EXPIRED)
        return False
    except Exception as e:
        log.exception("Sync failed for %s: %s", channel_id, e)
        _record_failure(channel_id)
        _touch_tick(channel_id)
        return False


def _apply_audit_and_handle(audit_row: dict, video: dict, channel_id: str) -> None:
    """Apply an audit and react to the typed ApplyError.outcome: idle on quota
    exhaustion, pause on token expiry, record a failure otherwise. Replaces a switch
    over the HTTPException detail STRING that YouTube's error text leaked into."""
    global _yt_quota_exhausted_until
    try:
        apply_audit_internal(audit_row["id"])
        _failure_counts[channel_id] = 0
        log.info("Autopilot applied audit %s for video %s", audit_row["id"], video["id"])
        if not video.get("is_short"):
            try:
                # force=True: the apply above just rewrote the title, so the
                # stored vector is stale by construction.
                embed_video(video["id"], force=True)
                # Playlist allocation skipped — workflow under review
                # join_pass(channel_id, video["id"])
            except Exception as e:
                log.warning("Embed failed for %s: %s", video["id"], e)
    except ApplyError as e:
        if e.outcome is ApplyOutcome.TEST_AND_COMPARE:
            log.info("Skipping video %s: active Test & Compare experiment on YouTube", video["id"])
        elif e.outcome is ApplyOutcome.QUOTA_EXCEEDED:
            _yt_quota_exhausted_until = _next_yt_quota_reset()
            log.warning(
                "YouTube quota exhausted; autopilot dormant until %s",
                _yt_quota_exhausted_until.strftime("%Y-%m-%d %H:%M UTC"),
            )
        elif e.outcome is ApplyOutcome.TOKEN_EXPIRED:
            log.warning("OAuth token expired or revoked for %s; pausing autopilot", channel_id)
            _pause(channel_id, PausedReason.TOKEN_EXPIRED)
        else:  # ApplyOutcome.FAILED
            _record_failure(channel_id)
    except Exception as e:
        log.exception("Apply failed for %s: %s", audit_row["id"], e)
        _record_failure(channel_id)


def tick():
    """One pass of the autopilot loop. Processes at most one video and returns.

    Thin orchestrator: quota gate → pick channel → shorts → (audit path: pause
    gate → resync → cap → pick video → audit → validate → apply). The steps live
    in helpers above and below; the failure-accounting rule is _record_failure()."""
    try:
        if _quota_dormant():
            return

        ch = _pick_next_channel()
        if not ch:
            return
        channel_id = ch["id"]

        # Shorts autopilot — fully decoupled from the metadata-audit path. It runs
        # before (and regardless of) the audit pause/resync gating: NAS cutting
        # needs no YouTube token or freshly-synced video stats, so an audit-side
        # pause or a stale-sync must never silence it. Enqueues at most one cut per
        # tick, gated by active_job_count vs the concurrency cap.
        if ch.get("autopilot_shorts_enabled"):
            try:
                _run_shorts_action(ch)
            except Exception as e:
                log.exception("Shorts autopilot failed for %s: %s", channel_id, e)

        # The metadata-audit path runs only for channels with metadata autopilot
        # enabled AND not audit-paused. (A channel can be picked purely for shorts
        # while audit-paused, so the pause is re-checked here, not just at pick.)
        if not ch.get("autopilot_enabled") or ch.get("autopilot_paused_reason"):
            _touch_tick(channel_id)
            return

        if not _resync_if_stale(ch):
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
            _pause(channel_id, PausedReason.UNSAFE_MODEL)
            return

        # 7. Run audit
        try:
            audit_row = audit_video(video["id"])
        except TokenExpiredError:
            log.warning("OAuth token expired or revoked for %s during audit; pausing", channel_id)
            _pause(channel_id, PausedReason.TOKEN_EXPIRED)
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
                        "status": AuditStatus.FAILED,
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
            _record_failure(channel_id)
            _touch_tick(channel_id)
            return

        # (Prompt-version attribution is stamped by audit_video at the insert.)

        # 8. Validate
        ok, reason = validate_audit(audit_row)
        if not ok:
            log.warning("Quarantining audit %s: %s", audit_row.get("id"), reason)
            supabase().table("audits").update({
                "status": AuditStatus.QUARANTINED,
                "ai_reasoning": (audit_row.get("ai_reasoning") or "") + f"\n[autopilot] quarantined: {reason}",
            }).eq("id", audit_row["id"]).execute()
            _touch_tick(channel_id)
            return

        # 9. No pre-apply quota re-check: YouTube's own quotaExceeded is the
        # signal (see _quota_dormant / _next_yt_quota_reset above). To restore
        # one, gate on quota.can_afford(quota.cost_of(*quota.APPLY)) — the price
        # lives in app.quota now, not in a constant here.

        # 10. Apply and react to the typed outcome.
        _apply_audit_and_handle(audit_row, video, channel_id)
        _touch_tick(channel_id)

    except Exception as e:
        log.exception("Autopilot tick crashed: %s", e)


# ── HTTP endpoints ─────────────────────────────────────────────────────

@router.post("/channels/{channel_id}/autopilot/resume")
def resume_autopilot(channel_id: str):
    supabase().table("channels").update({
        "autopilot_paused_reason": None, "autopilot_paused_at": None,
    }).eq("id", channel_id).execute()
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
