"""Phase 0 live probe (CIL §0.2 / PO §Sensor).

Runs one real youtubeAnalytics.reports.query against a re-consented channel to
verify the metric names and report shape BEFORE we write the analytics_client
abstraction.

Three queries:
  1. Video reach + retention   — dimensions=video, filters=video==<id>
  2. Playlist report (no flag) — dimensions=playlist
  3. Playlist report (curated) — dimensions=playlist, filters=isCurated==1

The third is the deprecation-status check: if Google has finalized the
`isCurated` deprecation, query 3 will error or return identically to query 2.

Output is the raw JSON for each query, plus a brief one-line summary. Nothing
is written back to Supabase — this is read-only.

Usage:
    python scripts/probe_analytics.py <channel_id> [--video-id VID] [--playlist-id PID]

If --video-id is omitted, the most-recently-published public video on the
channel is used. Same for --playlist-id (first playlist).

Requires:
  - channel re-consented with yt-analytics.readonly (analytics_authorized=true)
  - SUPABASE_URL, SUPABASE_SERVICE_KEY, CLIENT_SECRETS_FILE env set the same
    way the FastAPI app loads them
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

# Reuse exactly the same cred-loading and client-secrets path as the app.
from app.analytics_client import ANALYTICS_DATA_LAG_DAYS
from app.config import settings
from app.db import supabase
from app.youtube_client import _client_secrets


LAG_DAYS = ANALYTICS_DATA_LAG_DAYS
WINDOW_DAYS = 7

VIDEO_METRICS = ",".join([
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "videoThumbnailImpressions",
    "videoThumbnailImpressionsClickRate",
])

PLAYLIST_METRICS = ",".join([
    "playlistStarts",
    "viewsPerPlaylistStart",
    "averageTimeInPlaylist",
    "playlistViews",
    "playlistEstimatedMinutesWatched",
])


def _load_creds(channel_id: str) -> Credentials:
    row = (
        supabase().table("channels")
        .select("refresh_token,access_token,analytics_authorized")
        .eq("id", channel_id)
        .single()
        .execute()
        .data
    )
    if not row:
        sys.exit(f"channel {channel_id} not found in supabase")
    if not row.get("analytics_authorized"):
        sys.exit(
            f"channel {channel_id} has analytics_authorized=false — "
            f"reconnect via /auth/login before running the probe"
        )
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
        creds.refresh(GoogleRequest())
    return creds


def _pick_video(youtube, channel_id: str) -> str:
    """Most-recent public video on the channel — falls back to any synced video."""
    rows = (
        supabase().table("videos")
        .select("id")
        .eq("channel_id", channel_id)
        .order("published_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if rows:
        return rows[0]["id"]
    # Fallback: ask YouTube directly.
    ch = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = youtube.playlistItems().list(
        part="contentDetails", playlistId=uploads, maxResults=1
    ).execute()
    return items["items"][0]["contentDetails"]["videoId"]


def _pick_playlist(youtube, channel_id: str) -> str | None:
    pls = youtube.playlists().list(
        part="id", channelId=channel_id, maxResults=1
    ).execute()
    items = pls.get("items") or []
    return items[0]["id"] if items else None


def _run_query(analytics, *, label: str, **kwargs) -> dict | None:
    print(f"\n── {label} ────────────────────────────────────────────")
    print(f"params: {json.dumps(kwargs, indent=2)}")
    try:
        resp = analytics.reports().query(**kwargs).execute()
    except HttpError as e:
        print(f"HttpError {e.resp.status}: {e.content!r}")
        return None
    print("response:")
    print(json.dumps(resp, indent=2))
    return resp


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("channel_id")
    p.add_argument("--video-id", help="override; defaults to newest public video")
    p.add_argument("--playlist-id", help="override; defaults to first playlist")
    args = p.parse_args()

    end_date = date.today() - timedelta(days=LAG_DAYS)
    start_date = end_date - timedelta(days=WINDOW_DAYS - 1)
    print(f"window: {start_date} → {end_date} (UTC, {WINDOW_DAYS}d ending T-{LAG_DAYS})")

    creds = _load_creds(args.channel_id)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    video_id = args.video_id or _pick_video(youtube, args.channel_id)
    playlist_id = args.playlist_id or _pick_playlist(youtube, args.channel_id)
    print(f"video_id:    {video_id}")
    print(f"playlist_id: {playlist_id or '(no playlists on this channel)'}")

    _run_query(
        analytics,
        label="1a. VIDEO baseline (no impressions/CTR)",
        ids="channel==MINE",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
        dimensions="video",
        filters=f"video=={video_id}",
    )
    _run_query(
        analytics,
        label="1b. VIDEO + spec names (videoThumbnailImpressions / ...ClickRate)",
        ids="channel==MINE",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics=VIDEO_METRICS,
        dimensions="video",
        filters=f"video=={video_id}",
    )
    _run_query(
        analytics,
        label="1c. VIDEO + official-doc names (impressions / impressionsClickThroughRate)",
        ids="channel==MINE",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,impressions,impressionsClickThroughRate",
        dimensions="video",
        filters=f"video=={video_id}",
    )
    _run_query(
        analytics,
        label="1d. CHANNEL-LEVEL (no dimension) + official-doc names",
        ids="channel==MINE",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics="views,impressions,impressionsClickThroughRate",
    )
    # ── thumbnail-impression shape bisect ─────────────────────────────────
    _run_query(
        analytics,
        label="1e. THUMB metrics, dimensions=day, channel-level",
        ids="channel==MINE",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics="videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
        dimensions="day",
    )
    _run_query(
        analytics,
        label="1f. THUMB metrics, no dimensions, channel-level",
        ids="channel==MINE",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics="videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
    )
    _run_query(
        analytics,
        label="1g. THUMB metrics, dimensions=video, no filters",
        ids="channel==MINE",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics="videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
        dimensions="video",
        sort="-videoThumbnailImpressions",
        maxResults=5,
    )
    _run_query(
        analytics,
        label="1h. THUMB metrics, dimensions=day, filters=video==X",
        ids="channel==MINE",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics="videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
        dimensions="day",
        filters=f"video=={video_id}",
    )

    if playlist_id:
        _run_query(
            analytics,
            label="2. PLAYLIST report (no isCurated filter)",
            ids="channel==MINE",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics=PLAYLIST_METRICS,
            dimensions="playlist",
            filters=f"playlist=={playlist_id}",
        )
        _run_query(
            analytics,
            label="3. PLAYLIST report (filters=isCurated==1) — deprecation check",
            ids="channel==MINE",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics=PLAYLIST_METRICS,
            dimensions="playlist",
            filters=f"playlist=={playlist_id};isCurated==1",
        )
    else:
        print("\nskipping playlist queries — no playlists on this channel")

    print("\n── done ─────────────────────────────────────────────────")
    print("Save this output and paste it back so the analytics_client.py")
    print("shape (column-header parsing, None-on-empty) is grounded in real data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
