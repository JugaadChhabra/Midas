"""One-off: create a channel's Reporting API job (Phase 0.5 / Phase A1 operator tool).

`reporting_poll.ensure_reach_job` respects DRY_RUN and will not create a
missing job while DRY_RUN=true — it logs a warning instead. This script is
the human-gated path: run it once per channel to subscribe the channel to a
report type, by default `channel_reach_basic_a1`. Idempotent — if a job for
that report type already exists, it prints the existing id and exits.

YouTube starts generating daily CSVs (plus ~60 days of historical backfill)
only after the job exists, so create it as soon as a channel is re-consented.

Phase A1 creates the traffic-source job on the probe channel:
    PYTHONPATH=. python scripts/create_reporting_job.py UCr5-YUqBiW7PUmeAtxUWuRg \\
        --report-type channel_traffic_source_a2 --job-name midas-traffic-source

Writes: one `jobs.create` on the channel's Reporting API config (not a video,
not the Data API quota). Quota: 0 Data API units; Reporting API calls draw
on that API's own pool. The only DB write is the token refresh inside
`reporting_for_channel`.

Usage:
    PYTHONPATH=. python scripts/create_reporting_job.py <channel_id>
        [--report-type TYPE] [--job-name NAME]
"""

from __future__ import annotations

import argparse

from app.reporting_client import (
    REACH_JOB_NAME,
    REACH_REPORT_TYPE_ID,
    list_jobs,
    reporting_for_channel,
)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create (or confirm) a Reporting API job for a channel.",
    )
    p.add_argument("channel_id")
    p.add_argument("--report-type", default=REACH_REPORT_TYPE_ID,
                   help=f"reportTypeId (default {REACH_REPORT_TYPE_ID})")
    p.add_argument("--job-name", default=None,
                   help=f"name stamped on a created job (default {REACH_JOB_NAME} "
                        f"for the reach type, else midas-<report-type>)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    channel_id = args.channel_id
    report_type = args.report_type
    job_name = args.job_name or (
        REACH_JOB_NAME if report_type == REACH_REPORT_TYPE_ID else f"midas-{report_type}"
    )

    handle = reporting_for_channel(channel_id)

    # jobs.create answers an unknown reportTypeId with a bare 404 ("Requested
    # entity was not found"). Check the ID against the live list first, so a
    # retired or misspelt type fails with the IDs that do exist.
    types = handle.service.reportTypes().list(pageSize=100).execute().get("reportTypes") or []
    known = {t["id"] for t in types}
    if report_type not in known:
        stem = report_type.rsplit("_", 1)[0]
        close = sorted(t for t in known if t.startswith(stem)) or sorted(known)
        print(f"unknown report type {report_type!r}. Available"
              f"{' ' + stem + '*' if close != sorted(known) else ''}: {', '.join(close)}")
        return 2

    for j in list_jobs(handle, channel_id):
        if j.get("reportTypeId") == report_type:
            print(f"job already exists: {j['id']} (type {report_type}, "
                  f"name {j.get('name')}, created {j.get('createTime')})")
            return 0

    created = handle.service.jobs().create(body={
        "reportTypeId": report_type,
        "name": job_name,
    }).execute()
    print(f"created job {created['id']} (type {report_type}, name {job_name}) "
          f"for {channel_id} at {created.get('createTime')}")
    print("first CSVs typically appear within 24-48h; historical backfill follows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
