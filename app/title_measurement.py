"""Slice 3 · S3.5 — title measurement per video (spec Part 6 S3.5, Part 2 §1.2,
§1.7, F6, F14; #120).

A title is shown on the home page and beside other videos, so its indicator is
the video's own browse (3) + suggested (7) views in its channel's traffic
report (Part 6 finding 3), not a pair as backlinks' (app/lever_measurement.py):

    windows(d0)                -- (pre, post) around the as-of date
    evaluate(row, ...)         -- one row's progress, outcome and numbers
    measure_channel(channel_id) -- judge every title row of the channel whose window is complete

Which rows: `midas` `title` rows on the channel,

  - treated (arm `treated`, `measuring`, `applied_at` set): d0 = the `applied_at` date;
  - holdout (arm `holdout`, `holdout`): d0 = the `created_at` date;
  - an agent decline (arm `treated`, `declined`, F14: intention-to-treat):
    d0 = the `created_at` date.

`cancelled` rows (a failed write, checks_failed, a revert) are not measured.
d0 is a data-day, the Pacific date (as lever_measurement.as_of).

Windows: pre = d0−14 … d0−1, post = d0+1 … d0+TITLE_WINDOW_DAYS. Complete once
the channel has ingested `channel_traffic_source_a3` through the post's last
day (the ledger frontier); until then the row waits. `delta` =
ln((post + 1) / (pre + 1)). A pre under TITLE_MIN_PRE_VIEWS is
`insufficient_data`, with no extension; else `judged`. Both carry the numbers,
with the video's impressions and CTR over the same windows (`video_reach_daily`),
recorded only.

Decided rows are recomputed within lever_measurement.RESTATEMENT_HORIZON_DAYS
of their post window, as backlinks' are. The weekly `lever_measurement` job
(app/lever_verdicts.py `run_weekly`) calls `measure_channel`.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from app import reach
from app.config import settings
from app.db import supabase
from app.lever_measurement import RESTATEMENT_HORIZON_DAYS, Window, _day, _in, _in_horizon, _update
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID
from app.rows import all_rows
from app.status_vocab import (
    InterventionArm,
    InterventionLever,
    InterventionMeasurement,
    InterventionOrigin,
    InterventionStatus,
)

log = logging.getLogger("midas.title_measurement")

#: The pre window (Part 6 S3.5, F6); the post is TITLE_WINDOW_DAYS.
PRE_DAYS = 14
#: Browse features and suggested videos: where a title is read (finding 3).
SOURCE_TYPES = (3, 7)
#: The job's item category for title rows (app/lever_verdicts.py run_weekly).
ROWS = "title interventions"

_DECIDED = (InterventionStatus.JUDGED, InterventionStatus.INSUFFICIENT_DATA)
_COLUMNS = ("id,video_id,channel_id,lever,origin,arm,status,payload,applied_at,created_at,"
            "measurement_status,measurement_result")


def as_of(row: dict) -> date | None:
    """d0: applied (treated), else created (holdout, an agent decline)."""
    return _day(row.get("applied_at") or row.get("created_at"))


def windows(d0: date) -> tuple[Window, Window]:
    """(pre, post): d0−14 … d0−1 and d0+1 … d0+TITLE_WINDOW_DAYS."""
    pre = ((d0 - timedelta(days=PRE_DAYS)).isoformat(), (d0 - timedelta(days=1)).isoformat())
    post = ((d0 + timedelta(days=1)).isoformat(),
            (d0 + timedelta(days=settings.TITLE_WINDOW_DAYS)).isoformat())
    return pre, post


def views(video_id: str, pre: Window, post: Window) -> tuple[int, int]:
    """The video's browse + suggested views over (pre, post)."""
    rows = all_rows(
        supabase().table("video_traffic_source_daily")
        .select("date,source_type,views")
        .eq("video_id", video_id)
        .in_("source_type", list(SOURCE_TYPES))
        .gte("date", pre[0])
        .lte("date", post[1])
    )
    return (sum(r["views"] for r in rows if _in(pre, r["date"])),
            sum(r["views"] for r in rows if _in(post, r["date"])))


def evaluate(row: dict, complete_through: Callable[[str], bool],
             missing: Callable[[Window, Window], list[str]] = lambda *_: []
             ) -> tuple[str, str | None, dict | None]:
    """(measurement_status, outcome status or None, measurement_result or None).

    `complete_through(day)` says whether the channel has ingested traffic data
    through `day`; `missing(pre, post)` lists the windows' data-days it lacks
    (counted as zero views, listed as S1.6a does)."""
    d0 = as_of(row)
    if d0 is None:
        raise ValueError(f"intervention {row.get('id')} has no as-of date")
    pre, post = windows(d0)
    if not complete_through(post[1]):
        return InterventionMeasurement.AWAITING_WINDOW, None, None
    pre_views, post_views = views(row["video_id"], pre, post)
    pre_reach, post_reach = reach.aggregate(row["video_id"], pre), reach.aggregate(row["video_id"], post)
    result = {
        "pre": pre_views,
        "post": post_views,
        "delta": math.log((post_views + 1) / (pre_views + 1)),
        "impressions": {"pre": pre_reach[0], "post": post_reach[0]},
        "ctr": {"pre": pre_reach[1], "post": post_reach[1]},
        "missing_days": missing(pre, post),
        "window": {"d0": d0.isoformat(), "pre": list(pre), "post": list(post)},
    }
    outcome = (InterventionStatus.JUDGED if pre_views >= settings.TITLE_MIN_PRE_VIEWS
               else InterventionStatus.INSUFFICIENT_DATA)
    return InterventionMeasurement.DONE, outcome, result


def _pending(row: dict) -> bool:
    if row.get("arm") == InterventionArm.HOLDOUT:
        return row["status"] == InterventionStatus.HOLDOUT
    if row.get("arm") != InterventionArm.TREATED:
        return False
    if row["status"] == InterventionStatus.DECLINED:
        return True
    return row["status"] == InterventionStatus.MEASURING and bool(row.get("applied_at"))


def _rows(channel_id: str, today: date) -> list[dict]:
    """The channel's `midas` title rows awaiting a verdict, and the decided ones
    still within the restatement horizon."""
    def base():
        return (supabase().table("interventions").select(_COLUMNS)
                .eq("channel_id", channel_id).eq("lever", InterventionLever.TITLE)
                .eq("origin", InterventionOrigin.MIDAS))

    pending = all_rows(base().in_("status", [InterventionStatus.MEASURING,
                                             InterventionStatus.HOLDOUT,
                                             InterventionStatus.DECLINED]))
    # A decided row's post window ends at most TITLE_WINDOW_DAYS (+1 for a
    # midnight between insert and apply) after it was created.
    since = today - timedelta(days=RESTATEMENT_HORIZON_DAYS + settings.TITLE_WINDOW_DAYS + 1)
    decided = all_rows(base().in_("status", list(_DECIDED)).gte("created_at", since.isoformat()))
    return ([r for r in pending if _pending(r)]
            + [r for r in decided if _in_horizon(r, today)])


def measure_channel(channel_id: str, *, today: date | None = None) -> dict:
    """Measure the channel's title interventions.

    Returns counts: `attempted` and `errored` (rows, for
    job_status.item_error_verdict), `judged`, `insufficient_data`,
    `awaiting_window`, and `changed` (rows written). A row that errors is
    logged and left as it was.
    """
    today = today or datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc).isoformat()
    rows = _rows(channel_id, today)
    covered = reach.coverage(channel_id, report_type=TRAFFIC_REPORT_TYPE_ID) if rows else set()

    def complete_through(day: str) -> bool:
        return (reach.frontier(covered) or "") >= day

    def missing(*windows_: Window) -> list[str]:
        return reach.missing_days(covered, *windows_)

    counts = dict.fromkeys(("attempted", "errored", "judged", "insufficient_data",
                            "awaiting_window", "changed"), 0)
    for row in rows:
        counts["attempted"] += 1
        try:
            progress, outcome, result = evaluate(row, complete_through, missing)
            update = _update(row, progress, outcome, result, now)
        except Exception as e:
            counts["errored"] += 1
            log.warning("title_measurement %s: intervention %s failed: %s",
                        channel_id, row.get("id"), e)
            continue
        counts[outcome or progress] += 1
        if update:
            supabase().table("interventions").update(update).eq("id", row["id"]).execute()
            counts["changed"] += 1
    log.info("title_measurement %s: %s", channel_id, counts)
    return counts
