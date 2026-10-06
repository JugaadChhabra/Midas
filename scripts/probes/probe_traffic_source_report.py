"""Live probe (Phase A1): what does the `channel_traffic_source_a2` report hold?

Phase A1 asks whether we can get per-video, per-day views by traffic source,
and ideally by *referring video*. This probe reads the Reporting API job for
`channel_traffic_source_a2` on a channel (create it first with
`scripts/create_reporting_job.py --report-type channel_traffic_source_a2`),
lists its reports, downloads the newest, and prints:

  - the CSV header row, verbatim;
  - the distinct values of the traffic-source-type column, with row counts;
  - for RELATED_VIDEO / PLAYLIST / SHORTS / YT_SEARCH, every type value that
    matches it case-insensitively (or a similar name, e.g. "suggested" for
    related videos) and up to 5 sample values from the detail column;
  - each report's data date against its create time (the lag).

If the type column holds numeric codes rather than names, nothing will match
by name: the probe says so. Look the codes up in the Reporting API dimension
docs and re-run with `--sample-value <code>` for each one you want sampled.

If the job has no reports yet, the probe says so and prints the job's
creation time, so the wait can be judged against it.

Quota: 0 Data API units. Reporting API calls (jobs.list, jobs.reports.list,
the CSV download) draw on the Reporting API's own pool, and reporting_client
logs no quota_log rows for them.

Requires `analytics_authorized = true` on the channel (the Reporting API is
authorized by the yt-analytics.readonly scope); otherwise
`AnalyticsNotAuthorizedError` is raised before any call.

Read-only. Nothing is written to YouTube or to the DB, except that
`reporting_for_channel` stores a refreshed access token if the old one
expired. It never creates a job. `--save` writes the downloaded CSV to a
local file.

Usage:
    PYTHONPATH=. venv/bin/python scripts/probes/probe_traffic_source_report.py <channel_id>
        [--job-id JOB] [--report-id REPORT] [--save PATH] [--sample-value VALUE ...]
"""

from __future__ import annotations

import argparse
import csv
import io
import statistics
from collections import Counter
from datetime import datetime

from app.reporting_client import (
    download_report_csv,
    list_jobs,
    list_reports,
    report_data_date,
    reporting_for_channel,
)

# Google versions report types (_a2, _a3, …) and retires old ones. On 2026-09-29
# jobs.create returned 404 for _a2 on the office machine. Pass another live ID with
# --report-type (e.g. playlist_traffic_source_a2); list them with scripts/probe_reporting.py.
REPORT_TYPE_ID = "channel_traffic_source_a3"  # _a2 retired; 404 on 2026-09-29

# The four source types Part 2 §1.2 routes on, and the substrings that count
# as "a similar name" for each. Matched case-insensitively against the values
# of the type column.
WANTED_TYPES: dict[str, tuple[str, ...]] = {
    "RELATED_VIDEO": ("related", "suggest"),
    "PLAYLIST": ("playlist",),
    "SHORTS": ("short",),
    "YT_SEARCH": ("search",),
}

SAMPLES_PER_TYPE = 5


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=f"Inspect the newest {REPORT_TYPE_ID} report for a channel.",
    )
    p.add_argument("channel_id")
    p.add_argument("--report-type", default=REPORT_TYPE_ID,
                   help=f"reportTypeId of the job to read (default {REPORT_TYPE_ID})")
    p.add_argument("--job-id", help=f"job to read (default: the channel's {REPORT_TYPE_ID} job)")
    p.add_argument("--report-id", help="report to download (default: newest data date)")
    p.add_argument("--save", metavar="PATH", help="also write the downloaded CSV here")
    p.add_argument("--sample-value", action="append", default=[], metavar="VALUE",
                   help="an exact type-column value to sample detail for (repeatable); "
                        "use for numeric type codes")
    return p


def _report_order(r: dict) -> tuple[str, str]:
    """Data date first, then create time: the order "newest" means here."""
    return r.get("startTime") or "", r.get("createTime") or ""


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _find_column(header: list[str], needle: str) -> int | None:
    for i, name in enumerate(header):
        if needle in name.lower():
            return i
    return None


def _print_lag(reports: list[dict]) -> None:
    print(f"\n=== {len(reports)} reports: data date vs create time ===")
    lags: list[int] = []
    for r in sorted(reports, key=_report_order):
        data_day = report_data_date(r)
        created = _parse_ts(r.get("createTime"))
        lag = (created.date() - data_day).days if created else None
        if lag is not None:
            lags.append(lag)
        print(f"  {r['id']:>14s}  data {data_day}  created {r.get('createTime')}  lag {lag} d")
    if lags:
        print(f"lag (days, create date - data date): min {min(lags)}, max {max(lags)}, "
              f"median {statistics.median(lags)}")


def _print_samples(rows: list[list[str]], type_ix: int, detail_ix: int | None,
                   label: str, values: list[str]) -> None:
    print(f"\n--- {label}: matching type values {values or '(none)'}")
    for value in values:
        matched = [r for r in rows if len(r) > type_ix and r[type_ix] == value]
        print(f"  {value!r}: {len(matched)} rows")
        if detail_ix is None:
            continue
        samples: list[str] = []
        for r in matched:
            d = r[detail_ix] if len(r) > detail_ix else ""
            if d and d not in samples:
                samples.append(d)
            if len(samples) == SAMPLES_PER_TYPE:
                break
        empty = sum(1 for r in matched if len(r) <= detail_ix or not r[detail_ix])
        print(f"    detail samples: {samples or '(all empty)'}  ({empty} rows with empty detail)")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report_type = args.report_type
    channel_id = args.channel_id

    handle = reporting_for_channel(channel_id)
    jobs = [j for j in list_jobs(handle, channel_id)
            if j.get("reportTypeId") == report_type
            and (not args.job_id or j.get("id") == args.job_id)]
    if not jobs:
        print(f"no {report_type} job on {channel_id}"
              + (f" with id {args.job_id}" if args.job_id else "")
              + ". Create it with scripts/create_reporting_job.py "
                f"{channel_id} --report-type {report_type}")
        return 1
    job = jobs[0]
    print(f"job {job['id']} (type {job.get('reportTypeId')}, name {job.get('name')}, "
          f"created {job.get('createTime')})")

    reports = list_reports(handle, channel_id, job["id"])
    if not reports:
        print(f"\nNO REPORTS yet for job {job['id']}. Job created {job.get('createTime')}; "
              "the first report can take a day or more. Re-run later.")
        return 0
    _print_lag(reports)

    if args.report_id:
        target = next((r for r in reports if r["id"] == args.report_id), None)
        if target is None:
            print(f"\nreport {args.report_id} is not in job {job['id']}")
            return 1
    else:
        target = max(reports, key=_report_order)
    print(f"\n── downloading report {target['id']} (data {report_data_date(target)}, "
          f"created {target.get('createTime')}) ──")
    text = download_report_csv(handle, channel_id, target["downloadUrl"])
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"saved CSV to {args.save}")

    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    rows = [r for r in reader if r]
    print(f"\n=== header row (verbatim, {len(header)} columns) ===")
    print(text.splitlines()[0] if text else "(empty body)")
    print(f"{len(rows)} data rows")

    type_ix = _find_column(header, "traffic_source_type")
    detail_ix = _find_column(header, "traffic_source_detail")
    print(f"type column:   {header[type_ix] if type_ix is not None else 'NOT FOUND'}")
    print(f"detail column: {header[detail_ix] if detail_ix is not None else 'NOT FOUND'}")
    if type_ix is None:
        print("\nno traffic-source-type column; first 5 rows:")
        for r in rows[:5]:
            print(f"  {r}")
        return 0

    counts = Counter(r[type_ix] for r in rows if len(r) > type_ix)
    print(f"\n=== distinct {header[type_ix]} values ({len(counts)}) ===")
    for value, n in counts.most_common():
        print(f"  {value!r}: {n} rows")
    if counts and all(v.isdigit() for v in counts):
        print("  (values are numeric codes: no name will match below. Map them via the "
              "Reporting API dimension docs and re-run with --sample-value <code>.)")

    for label, needles in WANTED_TYPES.items():
        values = [v for v in counts
                  if v.lower() == label.lower() or any(n in v.lower() for n in needles)]
        _print_samples(rows, type_ix, detail_ix, label, values)
    for value in args.sample_value:
        _print_samples(rows, type_ix, detail_ix, f"--sample-value {value}", [value])

    print("\n── done ─────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
