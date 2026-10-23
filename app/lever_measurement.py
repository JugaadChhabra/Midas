"""Slice 1 · S1.6a — pair measurement per backlinks intervention (spec Part 4 S1.6,
Part 2 §1.2, §1.3, §1.7; #67).

A backlink A → B is attributable: the views it sends land in B's channel's
traffic report as rows with `video_id = B, source_type = 7 (suggested),
source_detail = A` (Part 4 finding 1; B1's retention keeps that detail because
A is ours, `traffic_poll.keeps_detail`). An intervention's indicator over a
window is the sum of those views over its targets:

    pair_views(source, targets, window)   -- the indicator
    windows(d0, post_days)                -- (pre, post) around the as-of date
    measure_channel(channel_id)           -- judge every row of the channel whose window is complete

The weekly `lever_measurement` job (S1.6b, app/lever_verdicts.py `run_weekly`)
calls `measure_channel` per channel, then writes the week's verdicts.

Which rows: `backlinks` interventions on the channel (the source's channel),

  - treated (`midas`, arm `treated`, `measuring`): d0 = the `applied_at` date;
  - holdout (`midas`, arm `holdout`, `holdout`): d0 = the `created_at` date;
  - human (`human`, `applied`), only on channels in TRAFFIC_INGEST_CHANNELS:
    d0 = the `detected_at` date, which is when sync saw the edit, not when it
    was made (B3).

d0 is a data-day: the Pacific date of that timestamp (YouTube's day, as reach's).

Windows: pre = d0−7 … d0−1, post = d0+1 … d0+7. A window is complete once
every target's channel, and the source's (whose report holds the source's
own views), has ingested `channel_traffic_source_a3` through the post window's
last day: the ledger's frontier, as `reach.coverage` reads it. Until then the
row waits. If the source had fewer than LEVER_MIN_SOURCE_VIEWS views in the
post window, the post window is extended once to d0+14 (and waits for it);
still short is `insufficient_data`, otherwise `judged`. Both carry the numbers
in `measurement_result`.

`status` carries the outcome (`judged`, `insufficient_data`); `measurement_status`
only how far the measurement got (`status_vocab.InterventionMeasurement`).

Restatements: YouTube reissues traffic days, and traffic_poll replaces the day
(B1). A decided row is recomputed on every run while its post window ended
within RESTATEMENT_HORIZON_DAYS, so a restated day is re-read on the next run.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from app import reach
from app.config import settings
from app.db import supabase
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID
from app.rows import all_rows, rows_for_ids
from app.status_vocab import (
    InterventionArm,
    InterventionLever,
    InterventionMeasurement,
    InterventionOrigin,
    InterventionStatus,
)

log = logging.getLogger("midas.lever_measurement")

#: The pre window, and the post window before any extension (Part 4 S1.6).
WEEK = 7
#: The post window after the one extension (Part 2 §1.7).
EXTENDED_DAYS = 14
#: How long after its post window ends a decided row is still recomputed, so a
#: restated traffic day reaches it. Not in the spec: four weekly runs. The
#: steady report lag is 2 days and Phase A saw restatements within days
#: (docs/PHASE_A_FINDINGS.md A1.1); a longer horizon only costs re-reads.
RESTATEMENT_HORIZON_DAYS = 28

_SUGGESTED = 7
#: Traffic data-days are YouTube's, which roll over on Pacific time (as reach's,
#: app/reach.py), so d0 is the Pacific date of the timestamp: the apply's own
#: data-day, never in either window, whatever the UTC hour.
_DATA_DAY_TZ = ZoneInfo("America/Los_Angeles")

_DECIDED = (InterventionStatus.JUDGED, InterventionStatus.INSUFFICIENT_DATA)
_COLUMNS = ("id,video_id,channel_id,origin,arm,status,payload,applied_at,created_at,"
            "detected_at,measurement_status,measurement_result")

Window = tuple[str, str]


def _day(value) -> date | None:
    """The data-day (Pacific date) of a timestamptz as PostgREST returns it, or None."""
    if not value:
        return None
    ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_DATA_DAY_TZ).date()


def as_of(row: dict) -> date | None:
    """d0: applied (treated), created (holdout) or detected (human)."""
    if row.get("origin") == InterventionOrigin.HUMAN:
        return _day(row.get("detected_at"))
    if row.get("arm") == InterventionArm.HOLDOUT:
        return _day(row.get("created_at"))
    return _day(row.get("applied_at"))


def windows(d0: date, post_days: int = WEEK) -> tuple[Window, Window]:
    """(pre, post): d0−7 … d0−1 and d0+1 … d0+post_days. d0 is in neither."""
    pre = ((d0 - timedelta(days=WEEK)).isoformat(), (d0 - timedelta(days=1)).isoformat())
    post = ((d0 + timedelta(days=1)).isoformat(), (d0 + timedelta(days=post_days)).isoformat())
    return pre, post


def targets(row: dict) -> list[str]:
    """The intervention's target video ids: a Midas row's `payload.targets`
    (S1.4b), a human row's single `payload.target_video_id` (B3a)."""
    payload = row.get("payload") or {}
    if row.get("origin") == InterventionOrigin.HUMAN:
        target = payload.get("target_video_id")
        return [target] if target else []
    return [t["video_id"] for t in payload.get("targets") or [] if t.get("video_id")]


def _in(window: Window, day: str) -> bool:
    return window[0] <= day <= window[1]


def _pair_rows(source: str, target_ids: list[str], span: Window) -> list[dict]:
    return rows_for_ids(
        lambda chunk: supabase().table("video_traffic_source_daily")
        .select("video_id,date,views")
        .in_("video_id", chunk)
        .eq("source_type", _SUGGESTED)
        .eq("source_detail", source)
        .gte("date", span[0])
        .lte("date", span[1]),
        target_ids,
    )


def pair_views(source: str, target_ids: list[str], window: Window) -> int:
    """Views the targets got as suggested (type 7) from `source`, over `window`."""
    return sum(r["views"] for r in _pair_rows(source, target_ids, window)
               if _in(window, r["date"]))


def source_views(source: str, window: Window) -> int:
    """The source's own views over `window`, every traffic source."""
    rows = all_rows(
        supabase().table("video_traffic_source_daily")
        .select("date,views")
        .eq("video_id", source)
        .gte("date", window[0])
        .lte("date", window[1])
    )
    return sum(r["views"] for r in rows if _in(window, r["date"]))


def _result(source: str, target_ids: list[str], d0: date, post_days: int,
            views_of_source: int, missing: Callable[[Window, Window], list[str]]) -> dict:
    """`measurement_result` for a decided row. `delta` is in views per week:
    an extended post window is scaled to 7 days before the pre is subtracted,
    so it compares with the 7-day pre and with unextended rows.

    `missing_days`: data-days in either window that some channel the row reads
    has no ingested report for (a gap, or ingestion that began inside the pre
    window). They count as zero views; the row says so instead of hiding it.
    """
    pre, post = windows(d0, post_days)
    pre_views = pair_views(source, target_ids, pre)
    post_views = pair_views(source, target_ids, post)
    delta = (post_views - pre_views if post_days == WEEK
             else post_views * WEEK / post_days - pre_views)
    return {
        "pre": pre_views,
        "post": post_views,
        "delta": delta,
        "source_views": views_of_source,
        "missing_days": missing(pre, post),
        "window": {"d0": d0.isoformat(), "pre": list(pre), "post": list(post),
                   "post_days": post_days, "extended": post_days != WEEK},
    }


def evaluate(row: dict, complete_through: Callable[[str], bool],
             missing: Callable[[Window, Window], list[str]] = lambda *_: []
             ) -> tuple[str, str | None, dict | None]:
    """(measurement_status, outcome status or None, measurement_result or None).

    `complete_through(day)` says whether every channel the row reads has
    ingested traffic data through `day`; `missing(pre, post)` lists the
    windows' data-days one of them lacks.
    """
    d0 = as_of(row)
    if d0 is None:
        raise ValueError(f"intervention {row.get('id')} has no as-of date")
    source, target_ids = row["video_id"], targets(row)
    if not target_ids:
        raise ValueError(f"intervention {row.get('id')} has no targets")

    for post_days, waiting in ((WEEK, InterventionMeasurement.AWAITING_WINDOW),
                               (EXTENDED_DAYS, InterventionMeasurement.EXTENDED)):
        _, post = windows(d0, post_days)
        if not complete_through(post[1]):
            return waiting, None, None
        seen = source_views(source, post)
        if seen >= settings.LEVER_MIN_SOURCE_VIEWS:
            return (InterventionMeasurement.DONE, InterventionStatus.JUDGED,
                    _result(source, target_ids, d0, post_days, seen, missing))
    # Extended once and still under the floor (Part 2 §1.7).
    return (InterventionMeasurement.DONE, InterventionStatus.INSUFFICIENT_DATA,
            _result(source, target_ids, d0, EXTENDED_DAYS, seen, missing))


def _measured(row: dict, channel_id: str) -> bool:
    """Whether the row is one of the three kinds this measures."""
    if row.get("origin") == InterventionOrigin.HUMAN:
        return channel_id in settings.TRAFFIC_INGEST_CHANNELS
    return row.get("arm") in (InterventionArm.TREATED, InterventionArm.HOLDOUT)


def _pending(row: dict) -> bool:
    if row.get("origin") == InterventionOrigin.HUMAN:
        return row["status"] == InterventionStatus.APPLIED
    if row.get("arm") == InterventionArm.HOLDOUT:
        return row["status"] == InterventionStatus.HOLDOUT
    return row["status"] == InterventionStatus.MEASURING and bool(row.get("applied_at"))


def _in_horizon(row: dict, today: date) -> bool:
    post = ((row.get("measurement_result") or {}).get("window") or {}).get("post")
    return bool(post) and date.fromisoformat(post[1]) >= today - timedelta(days=RESTATEMENT_HORIZON_DAYS)


def _rows(channel_id: str, today: date) -> list[dict]:
    """The channel's backlinks rows awaiting a verdict, and the decided ones
    still within the restatement horizon."""
    def base():
        return (supabase().table("interventions").select(_COLUMNS)
                .eq("channel_id", channel_id).eq("lever", InterventionLever.BACKLINKS))

    pending = all_rows(base().in_("status", [InterventionStatus.MEASURING,
                                             InterventionStatus.HOLDOUT,
                                             InterventionStatus.APPLIED]))
    # A decided row's post window ends at most EXTENDED_DAYS (+1 for a midnight
    # between insert and apply) after it was created: older ones are past the horizon.
    since = today - timedelta(days=RESTATEMENT_HORIZON_DAYS + EXTENDED_DAYS + 1)
    decided = all_rows(base().in_("status", list(_DECIDED)).gte("created_at", since.isoformat()))
    return ([r for r in pending if _measured(r, channel_id) and _pending(r)]
            + [r for r in decided if _measured(r, channel_id) and _in_horizon(r, today)])


def _target_channels(rows: list[dict]) -> dict[str, str]:
    """{target video id: its channel}: from a Midas row's payload, else `videos`."""
    out: dict[str, str] = {}
    for r in rows:
        for t in (r.get("payload") or {}).get("targets") or []:
            if t.get("video_id") and t.get("channel_id"):
                out[t["video_id"]] = t["channel_id"]
    unknown = {t for r in rows for t in targets(r)} - set(out)
    for v in rows_for_ids(
        lambda chunk: supabase().table("videos").select("id,channel_id").in_("id", chunk),
        sorted(unknown),
    ):
        out[v["id"]] = v["channel_id"]
    return out


def measure_channel(channel_id: str, *, today: date | None = None) -> dict:
    """Measure the channel's backlinks interventions (source on the channel).

    Returns counts: `attempted` and `errored` (rows, for
    job_status.item_error_verdict), `judged`, `insufficient_data`,
    `awaiting_window`, `extended`, and `changed` (rows written). A row that
    errors is logged and left as it was.
    """
    today = today or datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc).isoformat()
    rows = _rows(channel_id, today)
    channel_of = _target_channels(rows)
    covered: dict[str, set[str]] = {}

    def coverage(cid: str) -> set[str]:
        if cid not in covered:
            covered[cid] = reach.coverage(cid, report_type=TRAFFIC_REPORT_TYPE_ID)
        return covered[cid]

    counts = dict.fromkeys(("attempted", "errored", "judged", "insufficient_data",
                            "awaiting_window", "extended", "changed"), 0)
    for row in rows:
        counts["attempted"] += 1
        try:
            unknown = [t for t in targets(row) if t not in channel_of]
            if unknown:
                raise ValueError(f"no channel known for target(s) {', '.join(unknown)}")
            channels = {channel_of[t] for t in targets(row)} | {row["channel_id"]}

            def complete_through(day: str) -> bool:
                return all((reach.frontier(coverage(c)) or "") >= day for c in channels)

            def missing(*windows_: Window) -> list[str]:
                return sorted({d for c in channels for d in reach.missing_days(coverage(c), *windows_)})

            progress, outcome, result = evaluate(row, complete_through, missing)
            update = _update(row, progress, outcome, result, now)
        except Exception as e:
            counts["errored"] += 1
            log.warning("lever_measurement %s: intervention %s failed: %s",
                        channel_id, row.get("id"), e)
            continue
        counts[outcome or progress] += 1
        if update:
            supabase().table("interventions").update(update).eq("id", row["id"]).execute()
            counts["changed"] += 1
    log.info("lever_measurement %s: %s", channel_id, counts)
    return counts


def _update(row: dict, progress: str, outcome: str | None, result: dict | None,
            now: str) -> dict | None:
    """The columns to write, or None when nothing changed.

    A decided row that can't be decided again yet (a restatement took the source
    under the floor, and the extended window isn't complete) keeps its verdict.
    `judged_at` is when the row got its current outcome, kept across recomputes
    that don't change it; `computed_at` is the last time its numbers changed.
    """
    previous = row.get("measurement_result") or {}
    if outcome is None:
        if row["status"] in _DECIDED or row.get("measurement_status") == progress:
            return None
        return {"measurement_status": progress}
    numbers = {k: v for k, v in previous.items() if k not in ("judged_at", "computed_at")}
    if (row["status"] == outcome and row.get("measurement_status") == progress
            and numbers == result):
        return None
    return {
        "status": outcome,
        "measurement_status": progress,
        "measurement_result": {**result,
                               "judged_at": (previous.get("judged_at") if row["status"] == outcome
                                             else None) or now,
                               "computed_at": now},
    }
