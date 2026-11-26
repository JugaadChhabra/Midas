"""The early read: a signal for Midas's changes still inside their measurement
window (#172, spec #167 "The early read").

Read-only and computed per request for the Results page (`app/seo_results.py`).
It is never written anywhere, and nothing that judges or stops a lever reads it:
`lever_verdicts`, `titles.stopped` and `auto_revert` read only the stored
`measurement_result`s the weekly job writes. Only `seo_results` imports this.

Which rows: treated and holdout `midas` rows of lever `title` or `backlinks`
that the weekly measurement will judge (each module's own `_pending`) and that
have no `measurement_result` yet. A title row needs a known path, as a verdict
mean does (`lever_verdicts._title_arm`; an agent decline is treated); a
backlinks row on a Short is left out, as the verdicts leave it
(`lever_verdicts._without_shorts`).

Post days are the *ingested* traffic data-days (`channel_traffic_source_a3`,
the ledger `reach.coverage` reads) from d0+1 to the frontier, capped at the
window the verdict will use. A row with no post day yet has no early read.

  - Titles: d0, the pre window (`PRE_DAYS`), the cap (`TITLE_WINDOW_DAYS`) and
    the views (`SOURCE_TYPES`: browse, search, suggested) are
    `title_measurement`'s. Per-day means on both sides, so a partial post
    window compares like with like: delta = ln((post mean + 1) / (pre mean + 1)).
    Impressions (per day) and CTR (impression-weighted, `reach.weighted_ctr`)
    over the same pre and post days, from `video_reach_daily`.
  - Backlinks: d0, the windows (`WEEK`, `EXTENDED_DAYS` for a row already
    extended), the pair views (type 7, `SOURCE_TYPES[backlinks]`, from the
    source as `source_detail`, to its targets) and their channels are
    `lever_measurement`'s. In views per week, as the verdict's: delta =
    post × 7 / post days − pre. A target channel's frontier counts as the
    verdict's does: a day is ingested once every channel the row reads has it.

Traffic and reach rows are read only for the open rows' videos, over their
windows, through `rows.rows_for_ids`.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from app import lever_measurement, lever_verdicts, reach, title_measurement
from app.config import settings
from app.db import supabase
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID
from app.rows import rows_for_ids
from app.status_vocab import (
    InterventionArm,
    InterventionLever,
    InterventionMeasurement,
    InterventionOrigin,
)

ARMS = (InterventionArm.TREATED, InterventionArm.HOLDOUT)
_BACKLINK_SOURCE_TYPE = lever_measurement.SOURCE_TYPES[InterventionLever.BACKLINKS]
#: Sources per pair-views query: each brings up to BACKLINK_MAX targets into
#: the same query string, so fewer than `rows.IN_CHUNK`.
SOURCES_PER_QUERY = 100


def _open(row: dict, pending) -> bool:
    return (row.get("origin") == InterventionOrigin.MIDAS
            and row.get("arm") in ARMS
            and not row.get("measurement_result")
            and pending(row))


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _post_days(d0: date, cap: int, covered: set[str]) -> list[str]:
    """The ingested data-days from d0+1 to the frontier, at most `cap` of them."""
    return [d for d in _days(d0 + timedelta(days=1), d0 + timedelta(days=cap)) if d in covered]


class Coverage:
    """Each channel's ingested traffic data-days, read once per request."""

    def __init__(self):
        self._by_channel: dict[str, set[str]] = {}

    def of(self, channel_ids) -> set[str]:
        """The days every one of the channels has ingested."""
        sets = []
        for cid in channel_ids:
            if cid not in self._by_channel:
                self._by_channel[cid] = reach.coverage(cid, report_type=TRAFFIC_REPORT_TYPE_ID)
            sets.append(self._by_channel[cid])
        return set.intersection(*sets) if sets else set()


def _span(windows: list[tuple[str, str]]) -> tuple[str, str]:
    return min(w[0] for w in windows), max(w[1] for w in windows)


def titles(rows: list[dict], coverage: Coverage | None = None) -> dict:
    """{intervention id: {arm, channel_id, post_days, delta, impressions, ctr}}
    for the open title rows."""
    coverage = coverage or Coverage()
    plan = {}
    for r in rows:
        if not (_open(r, title_measurement._pending) and lever_verdicts._title_arm(r)):
            continue
        d0 = title_measurement.as_of(r)
        if d0 is None:
            continue
        post = _post_days(d0, settings.TITLE_WINDOW_DAYS, coverage.of([r["channel_id"]]))
        if post:
            plan[r["id"]] = (r, title_measurement.windows(d0)[0], post)
    if not plan:
        return {}
    videos = sorted({r["video_id"] for r, _, _ in plan.values()})
    start, end = _span([(pre[0], post[-1]) for _, pre, post in plan.values()])
    traffic = rows_for_ids(
        lambda chunk: supabase().table("video_traffic_source_daily")
        .select("id,video_id,date,views")
        .in_("video_id", chunk)
        .in_("source_type", list(title_measurement.SOURCE_TYPES))
        .gte("date", start).lte("date", end),
        videos)
    reach_rows = rows_for_ids(
        lambda chunk: supabase().table("video_reach_daily")
        .select("id,video_id,date,impressions,ctr")
        .in_("video_id", chunk)
        .gte("date", start).lte("date", end),
        videos)
    views_on: dict[tuple[str, str], int] = {}
    for t in traffic:
        key = (t["video_id"], t["date"])
        views_on[key] = views_on.get(key, 0) + t["views"]
    reach_on: dict[str, list[dict]] = {}
    for x in reach_rows:
        reach_on.setdefault(x["video_id"], []).append(x)

    out = {}
    for rid, (r, pre, post) in plan.items():
        v = r["video_id"]
        pre_days = _days(date.fromisoformat(pre[0]), date.fromisoformat(pre[1]))
        pre_mean = sum(views_on.get((v, d), 0) for d in pre_days) / len(pre_days)
        post_mean = sum(views_on.get((v, d), 0) for d in post) / len(post)
        post_set = set(post)
        pre_reach = [x for x in reach_on.get(v, []) if lever_measurement._in(pre, x["date"])]
        post_reach = [x for x in reach_on.get(v, []) if x["date"] in post_set]
        pre_impr, pre_ctr = reach.weighted_ctr(pre_reach)
        post_impr, post_ctr = reach.weighted_ctr(post_reach)
        out[rid] = {
            "arm": r["arm"], "channel_id": r["channel_id"], "post_days": len(post),
            "delta": math.log((post_mean + 1) / (pre_mean + 1)),
            "impressions": {"pre": pre_impr / len(pre_days), "post": post_impr / len(post)},
            "reach": {"pre": pre_reach, "post": post_reach},
        }
    return out


def backlinks(rows: list[dict], coverage: Coverage | None = None) -> dict:
    """{intervention id: {arm, channel_id, post_days, delta}} for the open
    backlinks rows, in views per week."""
    coverage = coverage or Coverage()
    candidates = [r for r in rows if r.get("lever", InterventionLever.BACKLINKS)
                  == InterventionLever.BACKLINKS and _open(r, lever_measurement._pending)]
    candidates = lever_verdicts._without_shorts(candidates)
    if not candidates:
        return {}
    channel_of = lever_measurement._target_channels(candidates)
    plan = {}
    for r in candidates:
        d0, src, tgts = (lever_measurement.as_of(r), lever_measurement.source(r),
                         lever_measurement.targets(r))
        if d0 is None or not src or not tgts or any(t not in channel_of for t in tgts):
            continue
        cap = (lever_measurement.EXTENDED_DAYS
               if r.get("measurement_status") == InterventionMeasurement.EXTENDED
               else lever_measurement.WEEK)
        post = _post_days(d0, cap, coverage.of({channel_of[t] for t in tgts} | {r["channel_id"]}))
        if post:
            plan[r["id"]] = (r, src, tgts, lever_measurement.windows(d0)[0], post)
    if not plan:
        return {}
    targets_of: dict[str, set[str]] = {}
    for _, src, tgts, _, _ in plan.values():
        targets_of.setdefault(src, set()).update(tgts)
    start, end = _span([(pre[0], post[-1]) for _, _, _, pre, post in plan.values()])
    # Chunked on the sources, each chunk asking only its own targets, so the
    # query string stays bounded however many rows are open.
    traffic = rows_for_ids(
        lambda chunk: supabase().table("video_traffic_source_daily")
        .select("id,video_id,date,source_detail,views")
        .in_("source_detail", chunk)
        .in_("video_id", sorted(set().union(*(targets_of[s] for s in chunk))))
        .eq("source_type", _BACKLINK_SOURCE_TYPE)
        .gte("date", start).lte("date", end),
        sorted(targets_of), chunk=SOURCES_PER_QUERY)
    views_on: dict[tuple[str, str, str], int] = {}
    for t in traffic:
        key = (t["source_detail"], t["video_id"], t["date"])
        views_on[key] = views_on.get(key, 0) + t["views"]

    out = {}
    for rid, (r, src, tgts, pre, post) in plan.items():
        pre_days = _days(date.fromisoformat(pre[0]), date.fromisoformat(pre[1]))
        pre_views = sum(views_on.get((src, t, d), 0) for t in tgts for d in pre_days)
        post_views = sum(views_on.get((src, t, d), 0) for t in tgts for d in post)
        out[rid] = {
            "arm": r["arm"], "channel_id": r["channel_id"], "post_days": len(post),
            "delta": post_views * lever_measurement.WEEK / len(post) - pre_views,
        }
    return out


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summary(reads: list[dict], *, with_reach: bool) -> dict | None:
    """A cell's `early`: treated vs holdout over the rows' early deltas, the
    post days they cover, and (titles) the changed videos' impressions per day
    and CTR, before and after. None when no row has a post day yet."""
    if not reads:
        return None
    by_arm = {arm: [x for x in reads if x["arm"] == arm] for arm in ARMS}
    t = _mean([x["delta"] for x in by_arm[InterventionArm.TREATED]])
    h = _mean([x["delta"] for x in by_arm[InterventionArm.HOLDOUT]])
    days = [x["post_days"] for x in reads]
    out = {
        "n_treated": len(by_arm[InterventionArm.TREATED]),
        "n_holdout": len(by_arm[InterventionArm.HOLDOUT]),
        "post_days_min": min(days), "post_days_max": max(days),
        "treated_mean_delta": t, "holdout_mean_delta": h,
        "lift": None if t is None or h is None else t - h,
        "impressions": None, "ctr": None,
    }
    treated = by_arm[InterventionArm.TREATED]
    if with_reach and treated:
        out["impressions"] = {side: _mean([x["impressions"][side] for x in treated])
                              for side in ("pre", "post")}
        out["ctr"] = {side: reach.weighted_ctr([d for x in treated for d in x["reach"][side]])[1]
                      for side in ("pre", "post")}
    return out
