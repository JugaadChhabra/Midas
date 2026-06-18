"""Phase 0.5 live probe (Reporting API — closes PHASE_0_GAPS.md Gap 1).

The on-demand `youtubeAnalytics.reports.query` does NOT expose
`videoThumbnailImpressions` / CTR (verified by scripts/probe_analytics.py,
2026-06-10). Those metrics ship only via the YouTube **Reporting API**
(bulk daily CSV reports). This probe surfaces the real Reporting API shape
BEFORE we write any abstraction:

  1. List system-managed report types (find the one carrying impressions/CTR).
  2. List existing reporting jobs for the channel.
  3. If a job exists, list its available reports + download one CSV.
  4. Pretty-print everything: report-type IDs, job IDs, CSV header row.

Read-only. Will NOT create a job (mutation deferred to the real
reporting_client). If no job exists yet for the channel, the probe stops
after step 2 with a note about which reportTypeId to subscribe to.

Usage:
    python scripts/probe_reporting.py <channel_id>
    python scripts/probe_reporting.py <channel_id> --download <report_id> --job <job_id>

Requires:
  - channel re-consented with yt-analytics.readonly (analytics_authorized=true)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys

import httpx
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

from app.config import settings
from app.db import supabase
from app.youtube_client import _client_secrets


# Filter report-type listings to ones whose ID hints at video-level
# impressions/CTR. We surface ALL system-managed types but highlight matches.
_CTR_HINTS = ("basic", "impression", "ctr", "thumbnail")


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


def _safe(call, *, label: str):
    print(f"\n── {label} ────────────────────────────────────────────")
    try:
        resp = call.execute()
    except HttpError as e:
        print(f"HttpError {e.resp.status}: {e.content!r}")
        return None
    print(json.dumps(resp, indent=2))
    return resp


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("channel_id")
    p.add_argument("--download", help="report id to download (requires --job)")
    p.add_argument("--job", help="job id (for --download)")
    args = p.parse_args()

    creds = _load_creds(args.channel_id)
    reporting = build("youtubereporting", "v1", credentials=creds, cache_discovery=False)

    # 1. List system-managed report types. Highlight candidates that look
    #    like they'd carry impressions/CTR.
    types_resp = _safe(
        reporting.reportTypes().list(includeSystemManaged=True, pageSize=100),
        label="1. reportTypes.list (system-managed=true)",
    )
    if types_resp:
        types = types_resp.get("reportTypes") or []
        print(f"\n=== candidate types (id contains any of {_CTR_HINTS}) ===")
        for t in types:
            tid = t.get("id", "")
            name = t.get("name", "")
            if any(h in tid.lower() for h in _CTR_HINTS):
                print(f"  ★ {tid:50s}  {name}")
        print(f"\n=== ALL {len(types)} report types ===")
        for t in types:
            print(f"    {t.get('id', ''):50s}  {t.get('name', '')}")

    # 2. List existing jobs for this channel/account.
    jobs_resp = _safe(
        reporting.jobs().list(includeSystemManaged=True),
        label="2. jobs.list (includeSystemManaged=true)",
    )
    jobs = (jobs_resp or {}).get("jobs") or []
    if not jobs:
        print("\nNO JOBS exist for this channel yet.")
        print("To create one, the real client would call:")
        print('    reporting.jobs().create(body={"reportTypeId": "<id>"}).execute()')
        print("Pick a reportTypeId from the candidates above and re-run with --create later.")
        return 0

    # 3. For each job, list a few reports.
    for j in jobs:
        jid = j["id"]
        report_type = j.get("reportTypeId", "")
        print(f"\n=== reports for job {jid} (type={report_type}) ===")
        reports_resp = _safe(
            reporting.jobs().reports().list(jobId=jid, pageSize=5),
            label=f"3.{jid}. jobs.reports.list",
        )
        if not reports_resp:
            continue

        # 4. If --download was provided AND matches this job, fetch one CSV.
        if args.download and args.job == jid:
            target = next(
                (r for r in reports_resp.get("reports") or [] if r["id"] == args.download),
                None,
            )
            if not target:
                print(f"\n  --download {args.download} not in this job's first page of reports")
                continue
            url = target.get("downloadUrl")
            if not url:
                print("  report has no downloadUrl")
                continue
            print(f"\n── 4. downloading report {target['id']} from {url} ──")
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers={"Authorization": f"Bearer {creds.token}"})
            print(f"HTTP {resp.status_code}, {len(resp.content)} bytes")
            text = resp.text
            print(f"\nCSV first 20 lines:")
            for i, line in enumerate(text.splitlines()[:20]):
                print(f"  {i:3d}: {line}")
            # Parse header to surface column names cleanly.
            reader = csv.reader(io.StringIO(text))
            header = next(reader, [])
            print(f"\nparsed columns ({len(header)}):")
            for c in header:
                print(f"  - {c}")
            row_count = sum(1 for _ in reader) + 1  # +header
            print(f"\ntotal lines including header: {row_count}")

    if not args.download:
        print("\nTo inspect a specific CSV, re-run with:")
        print("  python scripts/probe_reporting.py <cid> --job <jobId> --download <reportId>")
    print("\n── done ─────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
