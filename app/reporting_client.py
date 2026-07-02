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

def _log_quota(channel_id: str | None, operation: str, success: bool):
    """Telemetry-only; Reporting API quota is a separate pool from Data API."""
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


# ── Jobs ──────────────────────────────────────────────────────────────────

def list_jobs(handle: ReportingHandle, channel_id: str) -> list[dict]:
    """All non-system-managed reporting jobs for the channel, across pages.

    Paginated even though 1-2 jobs is the realistic count: a job missed on
    a hypothetical page 2 would make ensure_reach_job CREATE A DUPLICATE —
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


def ensure_reach_job(handle: ReportingHandle, channel_id: str) -> str | None:
    """Find (or create) this channel's reach reporting job. Returns job id.

    Creation is a write to the channel's Reporting API config, so it respects
    DRY_RUN like every other write path: in DRY_RUN mode a missing job is
    logged loudly and None is returned — the caller skips the channel until
    an operator creates the job (or DRY_RUN is lifted). Job creation is
    idempotent-by-check, not blind: we always list first.
    """
    for j in list_jobs(handle, channel_id):
        if j.get("reportTypeId") == REACH_REPORT_TYPE_ID:
            return j["id"]

    if settings.DRY_RUN:
        log.warning(
            "[DRY_RUN] channel %s has no %s reporting job; would create one. "
            "Reports only accrue after the job exists — create it soon "
            "(scripts/create_reporting_job.py or lift DRY_RUN).",
            channel_id, REACH_REPORT_TYPE_ID,
        )
        return None

    success = False
    try:
        created = handle.service.jobs().create(body={
            "reportTypeId": REACH_REPORT_TYPE_ID,
            "name": REACH_JOB_NAME,
        }).execute()
        success = True
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "youtubeReporting.jobs.create", success)

    log.info("created reach reporting job %s for channel %s", created.get("id"), channel_id)
    return created["id"]


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
