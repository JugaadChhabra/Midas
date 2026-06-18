"""Loop 0 sensor — daily metrics poll (CIL §0.4 / PO §Sensor).

For every channel with `analytics_authorized=true`, pull a trailing 7-day window
of video + playlist metrics, ending 2 days before today (Analytics data lag).
Upsert into `video_metrics` / `playlist_metrics` on the UNIQUE (id, window) key.

Scope:
  * v0 polls EVERY public synced video on the channel. Loop 1 will later narrow
    this to videos currently under measurement; until that exists, we cast a
    wide net so the sensor accrues history.
  * Playlists come from the existing `playlists` table inventory (synced by
    the playlist allocator). No discovery happens here.

Failure model: per-item exceptions are logged and swallowed so one bad video
doesn't kill the whole channel. TokenExpiredError on a channel skips that
channel for this run (next day it retries; autopilot will catch the token
issue separately and surface a re-consent prompt).

Quota: Analytics API is a separate pool from the Data API 10k/day budget.
No `quota.can_afford` gate here. Each call still writes a `units=0` quota_log
row via the client for visibility.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.analytics_client import (
    ANALYTICS_DATA_LAG_DAYS,
    AnalyticsNotAuthorizedError,
    analytics_for_channel,
    yt_analytics_playlist_report,
    yt_analytics_video_report,
    yt_analytics_video_traffic_source_playlist,
)
from app.db import supabase
from app.youtube_client import TokenExpiredError

log = logging.getLogger("midas.metrics_poll")

# Weekly trailing window (CIL §0.3: "v1 cadence: weekly windows").
WINDOW_DAYS = 7


def _window_dates() -> tuple[str, str]:
    """Inclusive (start, end) for the trailing window ending T-LAG.

    Anchored to UTC explicitly (not process-local time) so the 2-day lag
    against YouTube's ~48h Analytics freshness is deterministic regardless
    of where the cron fires.
    """
    end = datetime.now(timezone.utc).date() - timedelta(days=ANALYTICS_DATA_LAG_DAYS)
    start = end - timedelta(days=WINDOW_DAYS - 1)
    return start.isoformat(), end.isoformat()


def _upsert_video_metrics(
    *, video_id: str, channel_id: str, start: str, end: str, row: dict | None
) -> bool:
    """Write one window's row to video_metrics. Returns True if a row was
    written. A None report (Analytics returned `rows: []`) is treated as
    'no observation' and skipped — storing zeros would create a false
    baseline for Loop 1's CTR-window comparison."""
    if row is None:
        return False
    payload = {
        "video_id": video_id,
        "channel_id": channel_id,
        "window_start": start,
        "window_end": end,
        "views": int(row.get("views") or 0),
        "est_minutes_watched": int(row.get("estimatedMinutesWatched") or 0),
        "avg_view_duration_sec": int(row.get("averageViewDuration") or 0),
        "avg_view_pct": float(row.get("averageViewPercentage") or 0.0),
        # impressions/ctr stay NULL — Reporting API backfill territory.
    }
    supabase().table("video_metrics").upsert(
        payload, on_conflict="video_id,window_start,window_end"
    ).execute()
    return True


def _upsert_playlist_metrics(
    *, playlist_id: str, channel_id: str, start: str, end: str, row: dict | None
) -> bool:
    """Same skip-on-None semantics as the video path."""
    if row is None:
        return False
    payload = {
        "playlist_id": playlist_id,
        "channel_id": channel_id,
        "window_start": start,
        "window_end": end,
        "playlist_starts": int(row.get("playlistStarts") or 0),
        "views_per_playlist_start": float(row.get("viewsPerPlaylistStart") or 0.0),
        "avg_time_in_playlist_sec": int(row.get("averageTimeInPlaylist") or 0),
        "playlist_views": int(row.get("playlistViews") or 0),
        "playlist_est_minutes_watched": int(row.get("playlistEstimatedMinutesWatched") or 0),
    }
    supabase().table("playlist_metrics").upsert(
        payload, on_conflict="playlist_id,window_start,window_end"
    ).execute()
    return True


def _upsert_traffic_source_rows(
    *, video_id: str, channel_id: str, start: str, end: str, rows: list[dict]
) -> int:
    """Write one window's traffic-source breakdown for a single video.

    Each Analytics row contains (source_playlist_id, views) for a single
    member video; we land them keyed by (video_id, playlist_id, window) so
    the UNIQUE constraint dedupes a same-day re-run. Returns the number of
    rows upserted (zero when the video had no playlist-driven traffic in
    the window — Analytics returned `rows: []`).
    """
    if not rows:
        return 0
    payload = [
        {
            "video_id": video_id,
            "channel_id": channel_id,
            "playlist_id": r.get("insightTrafficSourceDetail") or "",
            "window_start": start,
            "window_end": end,
            "views": int(r.get("views") or 0),
        }
        for r in rows
        if r.get("insightTrafficSourceDetail")  # defensive: skip rows missing the dimension
    ]
    if not payload:
        return 0
    supabase().table("video_traffic_source_playlist").upsert(
        payload, on_conflict="video_id,playlist_id,window_start,window_end"
    ).execute()
    return len(payload)


def _poll_channel(channel_id: str, start: str, end: str, *, tier_2: bool) -> dict:
    """Pull one channel's video + playlist windows. Returns counts for logging.

    `tier_2`: if True, also pulls the playlist-source breakdown per video
    (Phase 1B Step B — only useful when health scoring consumes it). Caller
    should set this from `channels.playlist_health_enabled` so disabled
    channels skip the extra API calls entirely.
    """
    analytics = analytics_for_channel(channel_id)

    # Page past Supabase's 1000-row default cap so channels with >1000 synced
    # videos don't silently miss the tail (same pattern as dashboard.py).
    videos: list[dict] = []
    offset = 0
    PAGE = 1000
    while True:
        page = (
            supabase().table("videos")
            .select("id,privacy_status")
            .eq("channel_id", channel_id)
            .range(offset, offset + PAGE - 1)
            .execute()
            .data or []
        )
        videos.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    # Loop 1 only judges public videos (consistent with audits.py); skip the rest.
    public_video_ids = [
        v["id"] for v in videos
        if (v.get("privacy_status") is None) or (v.get("privacy_status") == "public")
    ]

    # Same pagination pattern as videos for consistency, even though >1000
    # playlists per channel is theoretical today.
    playlists: list[dict] = []
    offset = 0
    while True:
        page = (
            supabase().table("playlists")
            .select("id")
            .eq("channel_id", channel_id)
            .range(offset, offset + PAGE - 1)
            .execute()
            .data or []
        )
        playlists.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE

    log.info(
        "metrics_poll %s: %d public videos, %d playlists",
        channel_id, len(public_video_ids), len(playlists),
    )

    videos_written = 0
    videos_no_data = 0
    videos_err = 0
    tier2_rows_written = 0
    tier2_videos_no_data = 0
    tier2_err = 0
    for vid in public_video_ids:
        try:
            row = yt_analytics_video_report(analytics, channel_id, vid, start, end)
            wrote = _upsert_video_metrics(
                video_id=vid, channel_id=channel_id,
                start=start, end=end, row=row,
            )
            if wrote:
                videos_written += 1
            else:
                videos_no_data += 1
        except TokenExpiredError:
            raise  # bubble up — handled at the channel level
        except Exception as e:
            videos_err += 1
            log.warning("video metric pull failed for %s/%s: %s", channel_id, vid, e)

        # Tier-2 traffic-source breakdown (PHASE_1B_PLAN.md §9, Gap 6).
        # Gated per-channel so disabled channels skip the API call. Wrapped
        # in its own try/except so a tier-2 failure never poisons the tier-1
        # row we may have just written above.
        #
        # Note: tier-2 is intentionally attempted even when the tier-1 call
        # raised. Gap 10's transient-DNS failures can hit one call but not
        # the next, so a tier-1 fail does not predict a tier-2 fail. For
        # genuinely bad videos (deleted / privacy-flipped) both calls will
        # fail and inflate the err counters — accepted noise.
        if tier_2:
            try:
                ts_rows = yt_analytics_video_traffic_source_playlist(
                    analytics, channel_id, vid, start, end
                )
                n_written = _upsert_traffic_source_rows(
                    video_id=vid, channel_id=channel_id,
                    start=start, end=end, rows=ts_rows,
                )
                if n_written:
                    tier2_rows_written += n_written
                else:
                    tier2_videos_no_data += 1
            except TokenExpiredError:
                raise
            except Exception as e:
                tier2_err += 1
                log.warning(
                    "video traffic-source pull failed for %s/%s: %s",
                    channel_id, vid, e,
                )

    playlists_written = 0
    playlists_no_data = 0
    playlists_err = 0
    for pl in playlists:
        try:
            row = yt_analytics_playlist_report(
                analytics, channel_id, pl["id"], start, end
            )
            wrote = _upsert_playlist_metrics(
                playlist_id=pl["id"], channel_id=channel_id,
                start=start, end=end, row=row,
            )
            if wrote:
                playlists_written += 1
            else:
                playlists_no_data += 1
        except TokenExpiredError:
            raise
        except Exception as e:
            playlists_err += 1
            log.warning("playlist metric pull failed for %s/%s: %s", channel_id, pl["id"], e)

    return {
        "videos_written": videos_written,
        "videos_no_data": videos_no_data,
        "videos_err": videos_err,
        "playlists_written": playlists_written,
        "playlists_no_data": playlists_no_data,
        "playlists_err": playlists_err,
        "tier2_enabled": tier_2,
        "tier2_rows_written": tier2_rows_written,
        "tier2_videos_no_data": tier2_videos_no_data,
        "tier2_err": tier2_err,
    }


def poll_metrics() -> None:
    """APScheduler entry point. One pass over all re-consented channels."""
    start, end = _window_dates()
    log.info("metrics_poll start — window %s → %s", start, end)

    channels = (
        supabase().table("channels")
        .select("id,analytics_authorized,playlist_health_enabled")
        .eq("analytics_authorized", True)
        .execute()
        .data or []
    )
    if not channels:
        log.info("metrics_poll: no channels with analytics_authorized=true; nothing to do")
        return

    for ch in channels:
        cid = ch["id"]
        try:
            counts = _poll_channel(
                cid, start, end,
                tier_2=bool(ch.get("playlist_health_enabled")),
            )
            log.info("metrics_poll %s: %s", cid, counts)
        except AnalyticsNotAuthorizedError:
            # Race: row was true at query time, false now. Skip silently.
            log.info("metrics_poll %s: analytics_authorized flipped to false; skipped", cid)
        except TokenExpiredError:
            log.warning("metrics_poll %s: OAuth token expired; skipping until re-consent", cid)
        except Exception as e:
            log.exception("metrics_poll %s crashed: %s", cid, e)
