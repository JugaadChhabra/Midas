"""Phase B · B1 — daily traffic-source ingestion (spec Part 3 B1, P6; #30).

For every channel in TRAFFIC_INGEST_CHANNELS (eligibility.Job.TRAFFIC):

  1. Ensure the channel's `channel_traffic_source_a3` reporting job exists
     (find-or-create; creation respects DRY_RUN — see reporting_client).
     Marathi's job was created by hand on 2026-09-29 and is found, not
     duplicated.
  2. List the job's reports and ingest every one not already in the
     `reporting_reports_ingested` ledger into `video_traffic_source_daily`,
     summed over country_code, subscribed_status and live_or_on_demand
     (reporting_client.parse_traffic_csv). source_type stays YouTube's numeric
     code; names come from reporting_client.TRAFFIC_SOURCE_TYPES.

Restatements: YouTube reissues some data-days (A1.1). A newer report for a day
replaces that day's rows for the channel and never adds to them — the reach
ingester's latest-wins pieces (reporting_poll.replace_data_day,
record_ingested) do it here too. When a day and its restatement are both
listed, only the newest (by createTime) is ingested; an older report is never
landed over a newer one.

Independent of reporting_poll: it reads no reach data and writes no
video_metrics. Phase B makes no changes on YouTube; the only write is the
Reporting API job subscription above.

Failure model mirrors reporting_poll: a channel crash fails the run once every
channel has been polled; per-report errors are judged by
job_status.item_error_verdict; TokenExpiredError skips the channel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app import eligibility, job_status
from app.analytics_client import AnalyticsNotAuthorizedError
from app.reporting_client import (
    TRAFFIC_REPORT_TYPE_ID,
    download_report_csv,
    ensure_traffic_job,
    list_reports,
    parse_traffic_csv,
    report_data_date,
    reporting_for_channel,
)
from app.reporting_poll import ingested_report_ids, record_ingested, replace_data_day
from app.youtube_client import TokenExpiredError

log = logging.getLogger("midas.traffic_poll")


def _newest_per_day(reports: list[dict]) -> list[dict]:
    """The newest report (by createTime) for each data-day, oldest day first."""
    newest: dict = {}
    for r in reports:
        day = report_data_date(r)
        if day not in newest or (r.get("createTime") or "") > (newest[day].get("createTime") or ""):
            newest[day] = r
    return [newest[d] for d in sorted(newest)]


def _ingest_report(handle, channel_id: str, job_id: str, report: dict) -> int:
    """Download, aggregate and land one report. Returns rows written."""
    data_date = report_data_date(report).isoformat()
    rows = parse_traffic_csv(download_report_csv(handle, channel_id, report["downloadUrl"]))
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
    replace_data_day("video_traffic_source_daily", channel_id, data_date, report["id"],
                     payload, on_conflict="video_id,date,source_type,source_detail")
    record_ingested(report, job_id, channel_id, TRAFFIC_REPORT_TYPE_ID, data_date, len(payload))
    log.info("traffic_poll %s data-day %s: %d rows written (report %s)",
             channel_id, data_date, len(payload), report["id"])
    return len(payload)


def _poll_channel(channel_id: str) -> dict:
    handle = reporting_for_channel(channel_id)
    job_id = ensure_traffic_job(handle, channel_id)
    if job_id is None:
        # DRY_RUN with no existing job — nothing to ingest yet.
        return {"job": None, "reports_new": 0, "rows_ingested": 0}

    reports = list_reports(handle, channel_id, job_id)
    seen = ingested_report_ids(channel_id)
    new = [r for r in _newest_per_day(reports) if r["id"] not in seen]

    rows_ingested = 0
    reports_err = 0
    for report in new:
        try:
            rows_ingested += _ingest_report(handle, channel_id, job_id, report)
        except TokenExpiredError:
            raise
        except Exception as e:
            reports_err += 1
            log.warning(
                "traffic report ingest failed for %s report %s: %s",
                channel_id, report.get("id"), e,
            )

    return {
        "job": job_id,
        "reports_listed": len(reports),
        "reports_new": len(new),
        "reports_err": reports_err,
        "rows_ingested": rows_ingested,
    }


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
            failure, partial = job_status.item_error_verdict(
                {"reports": (c.get("reports_err", 0), c.get("reports_new", 0))})
            if failure:
                log.error("traffic_poll %s: every new report failed to ingest: %s", cid, failure)
                crashed[cid] = f"ItemsFailed: {failure}"
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
