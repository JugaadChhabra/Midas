"""One-off: create a channel's reach reporting job (Phase 0.5 operator tool).

`reporting_poll.ensure_reach_job` respects DRY_RUN and will not create a
missing job while DRY_RUN=true — it logs a warning instead. This script is
the human-gated path: run it once per channel to subscribe the channel to
`channel_reach_basic_a1`. Idempotent — if a job already exists, it prints
the existing id and exits.

YouTube starts generating daily CSVs (plus ~60 days of historical backfill)
only after the job exists, so create it as soon as a channel is re-consented.

Usage:
    PYTHONPATH=. python scripts/create_reporting_job.py <channel_id>
"""

from __future__ import annotations

import sys

from app.reporting_client import (
    REACH_JOB_NAME,
    REACH_REPORT_TYPE_ID,
    list_jobs,
    reporting_for_channel,
)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    channel_id = sys.argv[1]

    handle = reporting_for_channel(channel_id)
    for j in list_jobs(handle, channel_id):
        if j.get("reportTypeId") == REACH_REPORT_TYPE_ID:
            print(f"job already exists: {j['id']} (created {j.get('createTime')})")
            return 0

    created = handle.service.jobs().create(body={
        "reportTypeId": REACH_REPORT_TYPE_ID,
        "name": REACH_JOB_NAME,
    }).execute()
    print(f"created job {created['id']} for {channel_id}")
    print("first CSVs typically appear within 24-48h; historical backfill follows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
