"""YouTube Analytics API client (Loop 0 sensor).

Thin wrapper around `youtubeAnalytics.v2.reports.query`, mirroring the shape of
`app/youtube_client.py`. Quota for the Analytics API is a separate pool from
the Data API 10k/day budget, so calls here are logged with `units=0` for
visibility but never gate against `quota.can_afford`.

Shape verified against the live API on 2026-06-10 (see scripts/probe_analytics.py
output committed in the same Phase 0 work). Two reports supported on-demand:

  * video_report(...)    — dimensions=video, filters=video==<id>
                            metrics: views, estimatedMinutesWatched,
                            averageViewDuration, averageViewPercentage
                            (NO videoThumbnailImpressions / …ClickRate — those
                            are bulk-only via the YouTube Reporting API.)

  * playlist_report(...)  — dimensions=playlist, filters=playlist==<id>
                            metrics: playlistStarts, viewsPerPlaylistStart,
                            averageTimeInPlaylist (seconds, INTEGER),
                            playlistViews, playlistEstimatedMinutesWatched
                            (NO isCurated filter — fully deprecated.)

Return shape: a dict keyed by metric name, or `None` if the report has no row
(e.g. the video/playlist had no traffic in the window). Callers should treat
`None` as "no signal yet" — never as failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build

from app.config import settings
from app.db import supabase
from app.youtube_client import TokenExpiredError, _client_secrets


class AnalyticsNotAuthorizedError(Exception):
    """Channel has not re-consented to yt-analytics.readonly.

    Distinct from ValueError("channel not found") so the poll loop can skip
    consent gaps silently while still surfacing genuinely missing channels.
    """


# Analytics data lags ~2 days. Callers pass already-lag-adjusted window dates;
# this constant lives here so the poll job can reuse it.
ANALYTICS_DATA_LAG_DAYS = 2

_VIDEO_METRICS = ",".join([
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
])

_PLAYLIST_METRICS = ",".join([
    "playlistStarts",
    "viewsPerPlaylistStart",
    "averageTimeInPlaylist",
    "playlistViews",
    "playlistEstimatedMinutesWatched",
])


# ── Auth ──────────────────────────────────────────────────────────────────

def analytics_for_channel(channel_id: str):
    """Build a youtubeAnalytics v2 client for a channel's stored creds.

    Mirrors `youtube_client.youtube_for_channel` exactly — same row read, same
    refresh dance, same TokenExpiredError contract. Refuses to build a client
    if the channel hasn't re-consented to the analytics scope; callers should
    treat that as "skip silently" (CIL §0.1 graceful-degradation rule).
    """
    row = supabase().table("channels").select("*").eq("id", channel_id).single().execute().data
    if not row:
        raise ValueError(f"Channel {channel_id} not found")
    if not row.get("analytics_authorized"):
        raise AnalyticsNotAuthorizedError(channel_id)

    secrets = _client_secrets()
    creds = Credentials(
        token=row.get("access_token"),
        refresh_token=row["refresh_token"],
        token_uri=secrets["token_uri"],
        client_id=secrets["client_id"],
        client_secret=secrets["client_secret"],
        scopes=settings.SCOPES,
    )

    if not creds.valid:
        try:
            creds.refresh(GoogleRequest())
        except RefreshError as e:
            if "invalid_grant" in str(e):
                raise TokenExpiredError(channel_id) from e
            raise
        supabase().table("channels").update({
            "access_token": creds.token,
            "token_expiry": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
        }).eq("id", channel_id).execute()

    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


# ── Internal helpers ──────────────────────────────────────────────────────

def _log_quota(channel_id: str | None, operation: str, success: bool):
    """Telemetry-only log; Analytics API quota is a separate pool from Data API.

    units=0 so dashboards/aggregations don't double-count against the 10k budget
    while still surfacing call volume in quota_log.
    """
    try:
        supabase().table("quota_log").insert({
            "channel_id": channel_id,
            "operation": operation,
            "units": 0,
            "success": success,
        }).execute()
    except Exception:
        pass


def _guard_token(e: Exception, channel_id: str | None) -> None:
    if "invalid_grant" in str(e):
        raise TokenExpiredError(channel_id) from e


def _row_to_dict(resp: dict, *, label: str = "") -> dict | None:
    """Zip columnHeaders with the first row. Returns None on empty rows.

    All Phase 0 callers use a single-id filter (video==<id> / playlist==<id>)
    paired with a single-id dimension, so the API should only ever return one
    row. A >1-row response signals that an upstream caller broadened the
    filter without revisiting parse logic — log it loudly rather than
    silently dropping rows.
    """
    headers = resp.get("columnHeaders") or []
    rows = resp.get("rows") or []
    if not rows:
        return None
    if len(rows) > 1:
        import logging
        logging.getLogger("midas.analytics_client").warning(
            "analytics report returned %d rows (expected 1); using first only [%s]",
            len(rows), label or "unlabeled",
        )
    return {h["name"]: v for h, v in zip(headers, rows[0])}


# ── Reports ───────────────────────────────────────────────────────────────

def yt_analytics_video_report(
    analytics, channel_id: str | None, video_id: str, start: str, end: str
) -> dict | None:
    """Per-video reach + retention for [start, end] (YYYY-MM-DD, inclusive).

    Returns a dict with keys: video, views, estimatedMinutesWatched,
    averageViewDuration (seconds), averageViewPercentage. None if the video had
    no rows in the window. Quota: Analytics pool (free against Data API).
    """
    success = False
    try:
        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics=_VIDEO_METRICS,
            dimensions="video",
            filters=f"video=={video_id}",
        ).execute()
        success = True
        return _row_to_dict(resp, label=f"video={video_id}")
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "youtubeAnalytics.reports.query.video", success)


def yt_analytics_playlist_report(
    analytics, channel_id: str | None, playlist_id: str, start: str, end: str
) -> dict | None:
    """Per-playlist session metrics for [start, end] (YYYY-MM-DD, inclusive).

    Returns a dict with keys: playlist, playlistStarts, viewsPerPlaylistStart,
    averageTimeInPlaylist (seconds — INTEGER per live API), playlistViews,
    playlistEstimatedMinutesWatched. None if the playlist had no rows.

    Web-only counts (PO §Sensor): mobile/TV playlist views are not included.
    Treat absolute totals as undercounted; only trends/relative comparisons
    are meaningful.
    """
    success = False
    try:
        resp = analytics.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics=_PLAYLIST_METRICS,
            dimensions="playlist",
            filters=f"playlist=={playlist_id}",
        ).execute()
        success = True
        return _row_to_dict(resp, label=f"playlist={playlist_id}")
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "youtubeAnalytics.reports.query.playlist", success)
