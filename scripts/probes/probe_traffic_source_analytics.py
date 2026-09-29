"""Live probe (Phase A1 on-demand + A3): per-video traffic source via reports.query.

Gap 6 (`docs/PHASE_0_GAPS.md`) recorded a 400 "The query is not supported."
on one traffic-source query shape. This probe tries each variant Phase A needs
on one warm video and records which succeed:

  1. dimensions=insightTrafficSourceType,     filters=video==<id>
  2. dimensions=day,insightTrafficSourceType, filters=video==<id>  (per day)
  3. dimensions=insightTrafficSourceDetail,
     filters=video==<id>;insightTrafficSourceType==<T>
     for T in RELATED_VIDEO, PLAYLIST, SHORTS, YT_SEARCH. The YT_SEARCH
     variant is A3: its detail values are the search terms.

Each variant prints OK plus the first rows, or the exact HTTP status and error
message. A failure never stops the run.

Quota: 0 Data API units. The YouTube Analytics API has its own quota, and
analytics_client logs no quota_log rows for it. 6 queries per run with the
default types.

Requires `analytics_authorized = true` on the channel; otherwise
`AnalyticsNotAuthorizedError` is raised before any query.

Read-only. Nothing is written to YouTube or to the DB, except that
`analytics_for_channel` stores a refreshed access token if the old one
expired.

Usage:
    PYTHONPATH=. venv/bin/python scripts/probes/probe_traffic_source_analytics.py
        <channel_id> <video_id> [--days N] [--rows N] [--type T ...]
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from googleapiclient.errors import HttpError

from app.analytics_client import ANALYTICS_DATA_LAG_DAYS, analytics_for_channel

DEFAULT_TYPES = ("RELATED_VIDEO", "PLAYLIST", "SHORTS", "YT_SEARCH")
METRICS = "views,estimatedMinutesWatched"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Try the on-demand traffic-source query variants on one video.",
    )
    p.add_argument("channel_id")
    p.add_argument("video_id", help="a warm video (recent impressions) on that channel")
    p.add_argument("--days", type=int, default=28, help="window length (default 28)")
    p.add_argument("--rows", type=int, default=10, help="rows to print per variant (default 10)")
    p.add_argument("--type", dest="types", action="append", metavar="T",
                   help=f"insightTrafficSourceType to drill into (repeatable; "
                        f"default {', '.join(DEFAULT_TYPES)})")
    return p


def _error_message(e: HttpError) -> str:
    raw = e.content.decode("utf-8", "replace") if isinstance(e.content, bytes) else str(e.content)
    try:
        return json.loads(raw)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return raw


def _run(analytics, label: str, show_rows: int, **params) -> bool:
    print(f"\n── {label} ────────────────────────────────────────────")
    print(f"params: {json.dumps(params)}")
    try:
        resp = analytics.reports().query(**params).execute()
    except HttpError as e:
        print(f"FAILED HTTP {e.resp.status}: {_error_message(e)}")
        print(f"raw: {e.content!r}")
        return False
    headers = [h.get("name") for h in resp.get("columnHeaders") or []]
    rows = resp.get("rows") or []
    print(f"OK: {len(rows)} rows, columns {headers}")
    for r in rows[:show_rows]:
        print(f"  {r}")
    return True


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    types = args.types or list(DEFAULT_TYPES)

    end = date.today() - timedelta(days=ANALYTICS_DATA_LAG_DAYS)
    start = end - timedelta(days=args.days - 1)
    print(f"channel {args.channel_id}, video {args.video_id}, window {start} → {end}")
    base = dict(ids="channel==MINE", startDate=str(start), endDate=str(end), metrics=METRICS)

    analytics = analytics_for_channel(args.channel_id)
    results: dict[str, bool] = {}
    results["1. by type"] = _run(
        analytics, "1. insightTrafficSourceType, filters=video", args.rows,
        dimensions="insightTrafficSourceType", filters=f"video=={args.video_id}", **base,
    )
    results["2. by day + type"] = _run(
        analytics, "2. day,insightTrafficSourceType, filters=video", args.rows,
        dimensions="day,insightTrafficSourceType", filters=f"video=={args.video_id}",
        sort="day", **base,
    )
    for t in types:
        results[f"3. detail {t}"] = _run(
            analytics, f"3. insightTrafficSourceDetail, type=={t}"
                       + ("  (A3: search terms)" if t == "YT_SEARCH" else ""),
            args.rows,
            dimensions="insightTrafficSourceDetail",
            filters=f"video=={args.video_id};insightTrafficSourceType=={t}",
            sort="-views", maxResults=25, **base,
        )

    print("\n=== summary ===")
    for label, ok in results.items():
        print(f"  {'OK    ' if ok else 'FAILED'}  {label}")
    print("\n── done ─────────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
