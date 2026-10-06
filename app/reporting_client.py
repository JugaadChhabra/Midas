"""YouTube Reporting API client (Phase 0.5 — closes Gap 1: impressions/CTR).

The on-demand Analytics API does NOT expose videoThumbnailImpressions /
…ClickRate (verified by scripts/probe_analytics.py, 2026-06-10). Those metrics
ship only via the YouTube **Reporting API**: you subscribe a channel to a
system report type once (a "job"), YouTube then generates one CSV per data-day
server-side, and you list + download them.

Shape verified against the live API on 2026-07-02 (scripts/probe_reporting.py,
channel UC8KjoL0Z9mTHKqB6gFutkJw):

  * report type `channel_reach_basic_a1` carries per-video daily
    impressions + CTR. CSV columns (exact):
        date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr
    - `date` is YYYYMMDD (no dashes); ctr is a FRACTION (0.1538 = 15.38%).
    - one row per video that had >=1 impression that day; zero-impression
      videos are simply absent.
  * reports arrive erratically and out of order — the probe saw a report for
    data-day 2026-05-27 generated on 2026-06-28. Never assume ordering;
    dedupe by report id (see reporting_reports_ingested).
  * YouTube backfills ~60 days of history after job creation and retains
    generated reports for ~60 days.

Auth mirrors analytics_client.analytics_for_channel — same scope
(yt-analytics.readonly), same analytics_authorized gate, same
TokenExpiredError contract. One deviation: media downloads need the raw
bearer token (the CSV endpoint is not a discovery method), so
`reporting_for_channel` returns a (service, creds) handle instead of a bare
service object.

Quota: the Reporting API pool is separate from the Data API 10k/day budget.
Calls log units=0 rows for visibility (same convention as analytics_client).
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from typing import NamedTuple

import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

from app.config import settings
from app.db import supabase
from app.analytics_client import analytics_creds_for_channel
from app.youtube_client import TokenExpiredError

log = logging.getLogger("midas.reporting_client")

# The system report type carrying per-video daily impressions/CTR.
REACH_REPORT_TYPE_ID = "channel_reach_basic_a1"
# Name stamped on jobs we create, so ours are distinguishable in jobs.list.
REACH_JOB_NAME = "midas-reach"

# Exact CSV header verified by the 2026-07-02 probe. Parsing asserts against
# this so a silent upstream schema change fails loudly instead of mis-mapping.
_REACH_CSV_COLUMNS = [
    "date",
    "channel_id",
    "video_id",
    "video_thumbnail_impressions",
    "video_thumbnail_impressions_ctr",
]


# Phase B · B1 (#30): per-video daily views by traffic source. `_a2` was
# retired (404 on 2026-09-29, docs/PHASE_A_FINDINGS.md A1.1).
TRAFFIC_REPORT_TYPE_ID = "channel_traffic_source_a3"
# The name Marathi's job was created with on 2026-09-29 (A1.1).
TRAFFIC_JOB_NAME = "midas-traffic-source"

# Exact 15-column header recorded in A1.1 (2026-10-01). Asserted like the
# reach header.
_TRAFFIC_CSV_COLUMNS = [
    "date",
    "channel_id",
    "video_id",
    "live_or_on_demand",
    "subscribed_status",
    "country_code",
    "traffic_source_type",
    "traffic_source_detail",
    "views",
    "engaged_views",
    "watch_time_minutes",
    "average_view_duration_seconds",
    "average_view_duration_percentage",
    "red_views",
    "red_watch_time_minutes",
]

# Phase B · B1b (#31): per playlist × video daily views and playlist starts by
# traffic source. Marathi's job (381cf084…) was created by hand on 2026-09-29
# under this name (A1.1).
PLAYLIST_TRAFFIC_REPORT_TYPE_ID = "playlist_traffic_source_a2"
PLAYLIST_TRAFFIC_JOB_NAME = "midas-playlist-traffic-source"

# Exact 16-column header recorded in A1.1 (2026-10-01).
_PLAYLIST_TRAFFIC_CSV_COLUMNS = [
    "date",
    "channel_id",
    "playlist_id",
    "video_id",
    "live_or_on_demand",
    "subscribed_status",
    "country_code",
    "traffic_source_type",
    "traffic_source_detail",
    "views",
    "engaged_views",
    "watch_time_minutes",
    "average_view_duration_seconds",
    "playlist_starts",
    "playlist_saves_added",
    "playlist_saves_removed",
]

# traffic_source_type code → name. The report carries numeric codes only.
# Source: https://developers.google.com/youtube/reporting/v1/reports/dimensions
# (fetched 2026-10-01, copied from docs/PHASE_A_FINDINGS.md A1.1).
TRAFFIC_SOURCE_TYPES: dict[int, str] = {
    0: "Direct or unknown",
    1: "YouTube advertising",
    3: "Browse features",
    4: "YouTube channels",
    5: "YouTube search",
    7: "Suggested videos",
    8: "Other YouTube features",
    9: "External",
    11: "Video cards and annotations",
    14: "Playlists",
    17: "Notifications",
    18: "Playlist pages",
    19: "Programming from claimed content",
    20: "Interactive video endscreen",
    23: "Stories",
    24: "Shorts",
    25: "Product Pages",
    26: "Hashtag Pages",
    27: "Sound Pages",
    28: "Live redirect",
    29: "Podcasts",
    30: "Remixed video",
    31: "Vertical live feed",
    32: "Related video",
}


def traffic_source_name(code: int) -> str | None:
    """Name for a traffic_source_type code; None for a code the table lacks."""
    return TRAFFIC_SOURCE_TYPES.get(code)


class ReportingHandle(NamedTuple):
    """Service + creds pair; creds are needed for raw media downloads."""
    service: object
    creds: Credentials


# ── Auth ──────────────────────────────────────────────────────────────────

def reporting_for_channel(channel_id: str) -> ReportingHandle:
    """Build a youtubereporting v1 handle for a channel's stored creds.

    Auth is delegated to analytics_client.analytics_creds_for_channel — the
    Reporting API is authorized by the same yt-analytics.readonly scope, so
    the analytics_authorized gate, refresh dance, and
    AnalyticsNotAuthorizedError / TokenExpiredError contracts are identical
    and live in exactly one place.
    """
    creds = analytics_creds_for_channel(channel_id)
    service = build("youtubereporting", "v1", credentials=creds, cache_discovery=False)
    return ReportingHandle(service=service, creds=creds)


# ── Internal helpers ──────────────────────────────────────────────────────

def _log_quota(channel_id: str | None, operation: str, success: bool, units: int = 0):
    """Log a quota_log row for a metered call. NO-OP for units<=0.

    Reporting API quota is a separate pool from the Data API budget, so calls
    here are unmetered (units=0). Matching analytics_client._log_quota, we no
    longer persist zero-unit telemetry rows — every quota_log reader filters
    `units > 0`, so these rows only bloated the table. The `units` param stays
    for any future metered call.
    """
    if units <= 0:
        return  # unmetered telemetry — intentionally not persisted
    try:
        supabase().table("quota_log").insert({
            "channel_id": channel_id,
            "operation": operation,
            "units": units,
            "success": success,
        }).execute()
    except Exception:
        pass


def _guard_token(e: Exception, channel_id: str | None) -> None:
    if "invalid_grant" in str(e):
        raise TokenExpiredError(channel_id) from e


# ── Jobs ──────────────────────────────────────────────────────────────────

def list_jobs(handle: ReportingHandle, channel_id: str) -> list[dict]:
    """All non-system-managed reporting jobs for the channel, across pages.

    Paginated even though 1-2 jobs is the realistic count: a job missed on
    a hypothetical page 2 would make ensure_job CREATE A DUPLICATE —
    a write-side consequence, so the read is made airtight.
    """
    jobs: list[dict] = []
    page_token: str | None = None
    while True:
        success = False
        try:
            resp = handle.service.jobs().list(
                includeSystemManaged=False,
                **({"pageToken": page_token} if page_token else {}),
            ).execute()
            success = True
        except Exception as e:
            _guard_token(e, channel_id)
            raise
        finally:
            _log_quota(channel_id, "youtubeReporting.jobs.list", success)
        jobs.extend(resp.get("jobs") or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return jobs


def ensure_job(handle: ReportingHandle, channel_id: str, report_type: str,
               job_name: str) -> str | None:
    """Find (or create) this channel's reporting job for `report_type`. Returns job id.

    Creation is a write to the channel's Reporting API config, so it respects
    DRY_RUN like every other write path: in DRY_RUN mode a missing job is
    logged loudly and None is returned — the caller skips the channel until
    an operator creates the job (or DRY_RUN is lifted). Job creation is
    idempotent-by-check, not blind: we always list first.
    """
    for j in list_jobs(handle, channel_id):
        if j.get("reportTypeId") == report_type:
            return j["id"]

    if settings.DRY_RUN:
        log.warning(
            "[DRY_RUN] channel %s has no %s reporting job; would create one. "
            "Reports only accrue after the job exists — create it soon "
            "(scripts/create_reporting_job.py or lift DRY_RUN).",
            channel_id, report_type,
        )
        return None

    success = False
    try:
        created = handle.service.jobs().create(body={
            "reportTypeId": report_type,
            "name": job_name,
        }).execute()
        success = True
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "youtubeReporting.jobs.create", success)

    log.info("created %s reporting job %s for channel %s",
             report_type, created.get("id"), channel_id)
    return created["id"]


def ensure_reach_job(handle: ReportingHandle, channel_id: str) -> str | None:
    """`ensure_job` for the reach report type."""
    return ensure_job(handle, channel_id, REACH_REPORT_TYPE_ID, REACH_JOB_NAME)


def ensure_traffic_job(handle: ReportingHandle, channel_id: str) -> str | None:
    """`ensure_job` for the traffic-source report type."""
    return ensure_job(handle, channel_id, TRAFFIC_REPORT_TYPE_ID, TRAFFIC_JOB_NAME)


def ensure_playlist_traffic_job(handle: ReportingHandle, channel_id: str) -> str | None:
    """`ensure_job` for the playlist traffic-source report type."""
    return ensure_job(handle, channel_id, PLAYLIST_TRAFFIC_REPORT_TYPE_ID,
                      PLAYLIST_TRAFFIC_JOB_NAME)


# ── Reports ───────────────────────────────────────────────────────────────

def list_reports(handle: ReportingHandle, channel_id: str, job_id: str) -> list[dict]:
    """All report files for a job, across pages. Each item (verified shape):

        {"id": "...", "jobId": "...", "startTime": "2026-06-29T07:00:00Z",
         "endTime": "...", "createTime": "...", "downloadUrl": "https://..."}

    startTime's date part is the data-day the CSV covers. No ordering is
    guaranteed — the probe saw create order wildly out of data-day order.
    """
    reports: list[dict] = []
    page_token: str | None = None
    while True:
        success = False
        try:
            req = handle.service.jobs().reports().list(
                jobId=job_id, pageSize=50,
                **({"pageToken": page_token} if page_token else {}),
            )
            resp = req.execute()
            success = True
        except Exception as e:
            _guard_token(e, channel_id)
            raise
        finally:
            _log_quota(channel_id, "youtubeReporting.jobs.reports.list", success)
        reports.extend(resp.get("reports") or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return reports


def download_report_csv(handle: ReportingHandle, channel_id: str, download_url: str) -> str:
    """Fetch a report's CSV body (raw httpx + bearer token, per probe).

    Discovery-service calls auto-refresh through google-auth, but this raw
    download uses the bearer token directly — on a long backfill run the
    ~1h access token can lapse between list and download. A `creds.valid`
    pre-check is NOT sufficient: we construct Credentials without an expiry
    timestamp, so google-auth considers them valid forever. The reliable
    signal is the 401 itself — refresh and retry once (observed live on the
    2026-07-02 first backfill run: 10/49 downloads 401'd mid-run).
    """
    success = False
    try:
        for attempt in (1, 2):
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(
                    download_url,
                    headers={"Authorization": f"Bearer {handle.creds.token}"},
                )
            if resp.status_code == 401 and attempt == 1:
                handle.creds.refresh(GoogleRequest())
                continue
            break
        resp.raise_for_status()
        success = True
        return resp.text
    finally:
        _log_quota(channel_id, "youtubeReporting.media.download", success)


def report_data_date(report: dict) -> date:
    """Data-day a report covers: the date part of its startTime."""
    return datetime.fromisoformat(report["startTime"].replace("Z", "+00:00")).date()


def parse_reach_csv(text: str) -> list[dict]:
    """Parse a channel_reach_basic_a1 CSV into rows ready for upsert.

    Returns [{"video_id", "date" (ISO YYYY-MM-DD), "impressions" (int),
    "ctr" (float fraction)}]. Asserts the exact verified header so an
    upstream schema change fails loudly instead of silently mis-mapping.
    """
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    if header != _REACH_CSV_COLUMNS:
        raise ValueError(
            f"unexpected reach CSV header {header!r} — expected {_REACH_CSV_COLUMNS!r}. "
            "Re-probe with scripts/probe_reporting.py before trusting ingestion."
        )
    rows: list[dict] = []
    for raw in reader:
        if not raw or len(raw) != len(_REACH_CSV_COLUMNS):
            continue  # trailing blank line etc.
        d = raw[0]  # YYYYMMDD
        if len(d) != 8 or not d.isdigit():
            raise ValueError(f"unexpected reach CSV date {d!r} (want YYYYMMDD)")
        rows.append({
            "video_id": raw[2],
            "date": f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
            "impressions": int(raw[3]),
            "ctr": float(raw[4]),
        })
    return rows


def _aggregate_traffic_csv(text: str, report_type: str, columns: list[str], label: str,
                           id_columns: tuple[str, ...], metrics: dict[str, type]) -> list[dict]:
    """Parse a traffic-source CSV and sum `metrics` over every column not in the key.

    The key is `id_columns` + date + traffic_source_type + traffic_source_detail,
    stored as `date` (ISO), `source_type` (int code) and `source_detail` ('' when
    blank). Any bad header, short row or bad value raises, so a malformed report
    writes nothing.
    """
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    if header != columns:
        raise ValueError(
            f"unexpected {label} CSV header {header!r} — expected {columns!r}. "
            "Re-probe with scripts/probes/probe_traffic_source_report.py "
            f"--report-type {report_type} before trusting ingestion."
        )
    col = {c: i for i, c in enumerate(columns)}
    sums: dict[tuple, list] = {}
    for raw in reader:
        if not raw:
            continue  # trailing blank line
        # Unlike the reach parser, a short row fails the report: skipping it
        # would undercount the day with no error.
        if len(raw) != len(columns):
            raise ValueError(f"{label} CSV row has {len(raw)} columns, want {len(columns)}")
        d = raw[col["date"]]  # YYYYMMDD
        if len(d) != 8 or not d.isdigit():
            raise ValueError(f"unexpected {label} CSV date {d!r} (want YYYYMMDD)")
        key = (tuple(raw[col[c]] for c in id_columns), f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
               int(raw[col["traffic_source_type"]]), raw[col["traffic_source_detail"]])
        acc = sums.setdefault(key, [kind(0) for kind in metrics.values()])
        for i, (name, kind) in enumerate(metrics.items()):
            acc[i] += kind(raw[col[name]])
    return [
        {
            **dict(zip(id_columns, ids)),
            "date": day,
            "source_type": source_type,
            "source_detail": detail,
            **dict(zip(metrics, acc)),
        }
        for (ids, day, source_type, detail), acc in sums.items()
    ]


def parse_traffic_csv(text: str) -> list[dict]:
    """Parse a channel_traffic_source_a3 CSV into per-day rows ready for upsert.

    Sums views, engaged_views and watch_time_minutes over country_code,
    subscribed_status and live_or_on_demand, so there is one row per
    (video_id, date, source_type, source_detail). The average and red_*
    columns are dropped. Returns [{"video_id", "date" (ISO), "source_type"
    (int code), "source_detail" ('' when blank), "views", "engaged_views",
    "watch_time_minutes"}]. Any bad header or value raises, so a malformed
    report writes nothing.
    """
    return _aggregate_traffic_csv(
        text, TRAFFIC_REPORT_TYPE_ID, _TRAFFIC_CSV_COLUMNS, "traffic", ("video_id",),
        {"views": int, "engaged_views": int, "watch_time_minutes": float},
    )


def parse_playlist_traffic_csv(text: str) -> list[dict]:
    """Parse a playlist_traffic_source_a2 CSV into per-day rows ready for upsert.

    Aggregated like parse_traffic_csv, one row per (playlist_id, video_id, date,
    source_type, source_detail), keeping views, playlist_starts and
    watch_time_minutes (Part 2 §7). engaged_views, the average and the
    playlist_saves_* columns are dropped.
    """
    return _aggregate_traffic_csv(
        text, PLAYLIST_TRAFFIC_REPORT_TYPE_ID, _PLAYLIST_TRAFFIC_CSV_COLUMNS, "playlist traffic",
        ("playlist_id", "video_id"),
        {"views": int, "playlist_starts": int, "watch_time_minutes": float},
    )
