"""Phase B · B1 — daily traffic-source ingestion (spec Part 3 B1, P6; #30, #31).

For every channel in TRAFFIC_INGEST_CHANNELS (eligibility.Job.TRAFFIC), two
feeds, one per Reporting API report type:

  * video:    `channel_traffic_source_a3` → `video_traffic_source_daily` (B1a)
  * playlist: `playlist_traffic_source_a2` → `playlist_traffic_daily` (B1b)

For each feed:

  1. Ensure the channel's reporting job exists (find-or-create; creation
     respects DRY_RUN — see reporting_client). Marathi's two jobs were created
     by hand on 2026-09-29 and are found, not duplicated.
  2. List the job's reports and ingest every one not already in the
     `reporting_reports_ingested` ledger, summed over country_code,
     subscribed_status and live_or_on_demand (reporting_client.parse_traffic_csv,
     parse_playlist_traffic_csv). source_type stays YouTube's numeric code;
     names come from reporting_client.TRAFFIC_SOURCE_TYPES.

Restatements: YouTube reissues some data-days (A1.1; seen on the playlist
report). A newer report for a day replaces that day's rows for the channel and
never adds to them — the reach ingester's latest-wins pieces
(reporting_poll.replace_data_day, record_ingested) do it here too. When a day
and its restatement are both listed, only the newest (by createTime) is
ingested; an older report is never landed over a newer one.

Independent of reporting_poll: it reads no reach data and writes no
video_metrics. Phase B makes no changes on YouTube; the only write is the
Reporting API job subscription above.

Failure model mirrors reporting_poll: a channel crash fails the run once every
channel has been polled; per-report errors are judged by
job_status.item_error_verdict, per feed; TokenExpiredError skips the channel.
The feeds are isolated from each other: one feed's crash (its job or listing
failing) is recorded and fails the channel, but the other feed still runs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, NamedTuple

from app import eligibility, job_status
from app.analytics_client import AnalyticsNotAuthorizedError
from app.reporting_client import (
    PLAYLIST_TRAFFIC_REPORT_TYPE_ID,
    TRAFFIC_REPORT_TYPE_ID,
    download_report_csv,
    ensure_playlist_traffic_job,
    ensure_traffic_job,
    list_reports,
    parse_playlist_traffic_csv,
    parse_traffic_csv,
    report_data_date,
    reporting_for_channel,
)
from app.reporting_poll import ingested_report_ids, record_ingested, replace_data_day
from app.youtube_client import TokenExpiredError

log = logging.getLogger("midas.traffic_poll")


class _Feed(NamedTuple):
    """One report type and the table it lands in."""
    key: str
    report_type: str
    ensure_job: Callable
    parse: Callable[[str], list[dict]]
    table: str
    on_conflict: str


_FEEDS = (
    _Feed("video", TRAFFIC_REPORT_TYPE_ID, ensure_traffic_job, parse_traffic_csv,
          "video_traffic_source_daily", "video_id,date,source_type,source_detail"),
    _Feed("playlist", PLAYLIST_TRAFFIC_REPORT_TYPE_ID, ensure_playlist_traffic_job,
          parse_playlist_traffic_csv, "playlist_traffic_daily",
          "playlist_id,video_id,date,source_type,source_detail"),
)


def _newest_per_day(reports: list[dict]) -> list[dict]:
    """The newest report (by createTime) for each data-day, oldest day first."""
    newest: dict = {}
    for r in reports:
        day = report_data_date(r)
        if day not in newest or (r.get("createTime") or "") > (newest[day].get("createTime") or ""):
            newest[day] = r
    return [newest[d] for d in sorted(newest)]


def _ingest_report(handle, channel_id: str, feed: _Feed, job_id: str, report: dict) -> int:
    """Download, aggregate and land one report. Returns rows written."""
    data_date = report_data_date(report).isoformat()
    rows = feed.parse(download_report_csv(handle, channel_id, report["downloadUrl"]))
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = [
        {
            **r,
            "channel_id": channel_id,
            "report_id": report["id"],
            # Explicit so a restatement refreshes the timestamp (the column
            # default only fires on insert).
            "ingested_at": now_iso,
        }
        for r in rows
    ]
    replace_data_day(feed.table, channel_id, data_date, report["id"],
                     payload, on_conflict=feed.on_conflict)
    record_ingested(report, job_id, channel_id, feed.report_type, data_date, len(payload))
    log.info("traffic_poll %s data-day %s: %d rows written to %s (report %s)",
             channel_id, data_date, len(payload), feed.table, report["id"])
    return len(payload)


def _poll_feed(handle, channel_id: str, feed: _Feed, seen: set[str]) -> dict:
    job_id = feed.ensure_job(handle, channel_id)
    if job_id is None:
        # DRY_RUN with no existing job — nothing to ingest yet.
        return {"job": None, "reports_new": 0, "rows_ingested": 0}

    reports = list_reports(handle, channel_id, job_id)
    new = [r for r in _newest_per_day(reports) if r["id"] not in seen]

    rows_ingested = 0
    reports_err = 0
    for report in new:
        try:
            rows_ingested += _ingest_report(handle, channel_id, feed, job_id, report)
        except TokenExpiredError:
            raise
        except Exception as e:
            reports_err += 1
            log.warning(
                "%s traffic report ingest failed for %s report %s: %s",
                feed.key, channel_id, report.get("id"), e,
            )

    return {
        "job": job_id,
        "reports_listed": len(reports),
        "reports_new": len(new),
        "reports_err": reports_err,
        "rows_ingested": rows_ingested,
    }


def _poll_channel(channel_id: str) -> dict:
    """Both feeds for one channel: {feed key: counts, or {"error": ...} if it crashed}."""
    handle = reporting_for_channel(channel_id)
    # Report ids are unique across report types, so one ledger read serves both.
    seen = ingested_report_ids(channel_id)
    out: dict[str, dict] = {}
    for feed in _FEEDS:
        try:
            out[feed.key] = _poll_feed(handle, channel_id, feed, seen)
        except TokenExpiredError:
            raise
        except Exception as e:
            # Isolated so the other feed still runs; poll_traffic fails the channel.
            log.exception("traffic_poll %s %s feed crashed: %s", channel_id, feed.key, e)
            out[feed.key] = {"error": job_status.describe(e)}
    return out


def poll_traffic() -> dict | None:
    """APScheduler entry point. One pass over the traffic-ingest channels."""
    channels = eligibility.channels_for(eligibility.Job.TRAFFIC)
    if not channels:
        log.info("traffic_poll: no channels to poll (TRAFFIC_INGEST_CHANNELS); nothing to do")
        return None

    crashed: dict[str, str] = {}
    partial_errors: dict[str, str] = {}
    for ch in channels:
        cid = ch["id"]
        try:
            c = _poll_channel(cid) or {}
            log.info("traffic_poll %s: %s", cid, c)
            failures = [f"{key}: {f['error']}" for key, f in c.items() if "error" in f]
            failure, partial = job_status.item_error_verdict({
                f"{key} reports": (f.get("reports_err", 0), f.get("reports_new", 0))
                for key, f in c.items()
            })
            if failure:
                log.error("traffic_poll %s: every new report failed to ingest: %s", cid, failure)
                failures.append(f"ItemsFailed: {failure}")
            if failures:
                crashed[cid] = "; ".join(failures)
            elif partial:
                partial_errors[cid] = partial
        except AnalyticsNotAuthorizedError:
            log.info("traffic_poll %s: analytics_authorized flipped to false; skipped", cid)
        except TokenExpiredError:
            log.warning("traffic_poll %s: OAuth token expired; skipping until re-consent", cid)
        except Exception as e:
            log.exception("traffic_poll %s crashed: %s", cid, e)
            crashed[cid] = job_status.describe(e)
    if crashed:
        raise job_status.JobRunFailed("traffic_poll", crashed)
    return {"partial_errors": partial_errors} if partial_errors else None
