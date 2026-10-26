"""Slice 2 — Short → video links (spec Part 5 S2.4, Part 2 §2.3, P4).

A Short's related-video link sends Shorts-feed viewers to a long video (type
32 on the target). The YouTube API can neither read nor write it (A2), so this
lever is recommend-only, permanently: Midas lists, per Short, the long videos
it should link to, and the team sets the link in Studio. Nothing here reaches
YouTube.

S2.4, the recommendations:

    shorts(channel_id)    -- the Shorts with Shorts-feed views, most first
    targets(short)        -- its ranked same-channel targets
    refresh(channel_id)   -- weekly: pending rows for Shorts with none yet
    preview(channel_id)   -- the same, writing nothing and asking no backend
    run_weekly()          -- the `short_link_refresh` job

Targets are on the Short's own channel only: Studio links a Short only to a
video on its channel (Part 5 finding 6), unlike backlinks' siblings. Similarity
is on B6 vectors only (`reembed.MODEL_VERSION`), against the channel's
calibrated `join_low`, refused as `backlinks.candidates` refuses: no fallback
to EMBED_MODEL vectors or title overlap. Each pair gets the next-watch question
in shadow (`decide.NEXT_WATCH`, as `agent_tick._next_watch` asks it); its
decision_log row's id is stored on the recommendation, and the log row's
`intervention_id` stays NULL, since a recommendation is no intervention.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Mapping, NamedTuple

from app import decide, job_status, reach, warm
from app.backlinks import NO_THRESHOLDS, SOURCE_NOT_EMBEDDED, THRESHOLDS_OTHER_MODEL, _thresholds
from app.config import settings
from app.db import supabase
from app.embeddings import pooled_embeddings
from app.playlists import _cosine_sim
from app.reembed import MODEL_VERSION
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID
from app.rows import all_rows, rows_for_ids
from app.status_vocab import ShortLinkStatus

log = logging.getLogger(__name__)

#: The feed window: the channel's latest this-many ingested traffic data-days
#: (E9), counted as `backlinks.siblings` counts them.
FEED_WINDOW_DAYS = 28
_SHORTS_FEED = 24
#: job_status.item_error_verdict's category for the job's per-Short errors.
SHORTS = "shorts"


class Targets(NamedTuple):
    """`targets`' answer, shaped as `backlinks.Candidates`.

    `rows` are `{video_id, channel_id, title, similarity, impressions}`, best
    first, at most SHORT_LINK_TARGETS. `skipped_unembedded` counts the Short
    (1, with `reason` SOURCE_NOT_EMBEDDED) or the otherwise eligible targets
    with no B6 vector. `reason` is set when the Short got none without targets
    being considered; `join_low` is the threshold applied, once read.
    """

    rows: list[dict]
    skipped_unembedded: int = 0
    reason: str | None = None
    join_low: float | None = None


class Pool(NamedTuple):
    """A channel's eligible long videos with their vectors: the same for every
    one of its Shorts, so `refresh` reads it once."""

    join_low: float
    videos: list[dict]
    vectors: dict[str, list[float]]
    impressions: dict[str, int]
    unembedded: int


def _videos(ids) -> list[dict]:
    return rows_for_ids(
        lambda c: (
            supabase().table("videos")
            .select("id,channel_id,title,privacy_status,is_short")
            .in_("id", c)
        ),
        list(ids),
    )


def shorts(channel_id: str) -> list[dict]:
    """The channel's Shorts (`is_short` true), public or NULL, with at least
    SHORT_LINK_MIN_FEED_VIEWS Shorts-feed (type 24) views over its latest
    FEED_WINDOW_DAYS ingested `channel_traffic_source_a3` data-days, as
    `{id, channel_id, title, feed_views}`, most views first, ties by id."""
    covered = reach.coverage(channel_id, report_type=TRAFFIC_REPORT_TYPE_ID)
    if not covered:
        return []
    window = set(sorted(covered, reverse=True)[:FEED_WINDOW_DAYS])

    views: dict[str, int] = defaultdict(int)
    for r in all_rows(
        supabase().table("video_traffic_source_daily")
        .select("video_id,date,views")
        .eq("channel_id", channel_id)
        .eq("source_type", _SHORTS_FEED)
        .gte("date", min(window))
        .lte("date", max(window))
    ):
        if r["date"] in window:
            views[r["video_id"]] += r["views"]

    listed = [
        {"id": v["id"], "channel_id": v["channel_id"], "title": v.get("title"),
         "feed_views": views[v["id"]]}
        for v in _videos(vid for vid, n in views.items()
                         if n >= settings.SHORT_LINK_MIN_FEED_VIEWS)
        if v["channel_id"] == channel_id
        and v.get("is_short") is True
        and v.get("privacy_status") in (None, "public")
    ]
    listed.sort(key=lambda s: (-s["feed_views"], s["id"]))
    return listed


def _pool(channel_id: str) -> tuple[Pool | None, str | None]:
    """(the channel's target pool, None), or (None, why the thresholds were refused)."""
    thresholds = _thresholds(channel_id)
    if thresholds.get("join_low") is None:
        return None, NO_THRESHOLDS
    if thresholds.get("model_version") != MODEL_VERSION:
        return None, THRESHOLDS_OTHER_MODEL

    impressions = warm.warm_impressions(channel_id)
    eligible = [
        v for v in _videos(impressions)
        if v["channel_id"] == channel_id
        and v.get("privacy_status") in (None, "public")
        and v.get("is_short") is not True
    ]
    vectors = pooled_embeddings([v["id"] for v in eligible], model_version=MODEL_VERSION)
    embedded = [v for v in eligible if v["id"] in vectors]
    return Pool(thresholds["join_low"], embedded, vectors, impressions,
                len(eligible) - len(embedded)), None


def targets(short: Mapping, *, pool: Pool | None = None) -> Targets:
    """Link targets for `short` (a row of `shorts`, or any `videos` row with
    `id` and `channel_id`), ranked by similarity, then impressions, then id.

    A target is a long video (`is_short` not true) on the Short's own channel,
    public, warm (`warm.warm_impressions`), and at least the channel's
    `join_low` similar to the Short on B6 vectors. A NULL privacy or
    `is_short` is not yet known, and eligible (as `backlinks.candidates`).
    `pool` is the channel's `_pool`, for a caller asking for many Shorts.
    """
    if pool is None:
        pool, reason = _pool(short["channel_id"])
        if pool is None:
            return Targets([], reason=reason)
    short_id = short["id"]
    vector = pooled_embeddings([short_id], model_version=MODEL_VERSION).get(short_id)
    if vector is None:
        return Targets([], skipped_unembedded=1, reason=SOURCE_NOT_EMBEDDED,
                       join_low=pool.join_low)

    rows = []
    for v in pool.videos:
        similarity = _cosine_sim(vector, pool.vectors[v["id"]])
        if v["id"] != short_id and similarity >= pool.join_low:
            rows.append({"video_id": v["id"], "channel_id": v["channel_id"],
                         "title": v.get("title"), "similarity": similarity,
                         "impressions": pool.impressions[v["id"]]})
    rows.sort(key=lambda r: (-r["similarity"], -r["impressions"], r["video_id"]))
    return Targets(rows[:settings.SHORT_LINK_TARGETS], skipped_unembedded=pool.unembedded,
                   join_low=pool.join_low)


def _recommended(channel_id: str) -> set[str]:
    """The channel's Shorts that already have recommendation rows, of any status."""
    return {r["short_id"] for r in all_rows(
        supabase().table("short_link_recommendations").select("short_id")
        .eq("channel_id", channel_id))}


def _plan(channel_id: str) -> dict:
    """What `refresh` would write: up to SHORT_LINK_MAX_PER_RUN Shorts with no
    rows yet and at least one target, in `shorts` order. Writes nothing."""
    plan = {"channel_id": channel_id, "refused": None, "shorts": 0, "already": 0,
            "skipped_unembedded": 0, "no_targets": 0, "targets_unembedded": 0,
            "join_low": None, "plan": []}
    listed = shorts(channel_id)
    have = _recommended(channel_id) if listed else set()
    new = [s for s in listed if s["id"] not in have]
    plan["shorts"], plan["already"] = len(listed), len(listed) - len(new)
    if not new:
        return plan
    pool, plan["refused"] = _pool(channel_id)
    if pool is None:
        return plan
    plan["join_low"], plan["targets_unembedded"] = pool.join_low, pool.unembedded
    for short in new:
        if len(plan["plan"]) >= settings.SHORT_LINK_MAX_PER_RUN:
            break
        found = targets(short, pool=pool)
        if found.reason == SOURCE_NOT_EMBEDDED:
            plan["skipped_unembedded"] += 1
        elif not found.rows:
            plan["no_targets"] += 1
        else:
            plan["plan"].append({**short, "targets": found.rows})
    return plan


def _next_watch(short: dict, target: dict, join_low: float) -> int | None:
    """`decide(NEXT_WATCH, …)` for one pair, in shadow, with
    `agent_tick._next_watch`'s context (the Short is the source). Its log id."""
    context = {"source_video_id": short["id"], "source_title": short.get("title"),
               "target_video_id": target["video_id"], "target_channel_id": target["channel_id"],
               "target_title": target.get("title"), "similarity": target["similarity"],
               "join_low": join_low}
    return decide.decide(decide.NEXT_WATCH, f"{short['id']}->{target['video_id']}",
                         context).log_id


def _write(channel_id: str, short: dict, join_low: float) -> int:
    """Each pair's shadow next-watch, then one Short's `pending` rows, rank
    1…, with their log ids, in one insert: a Short is written whole or not at
    all, so one that raises is tried again next run. Returns the rows written."""
    rows = [
        {"channel_id": channel_id, "short_id": short["id"], "target_video_id": t["video_id"],
         "rank": rank, "similarity": t["similarity"], "impressions": t["impressions"],
         "feed_views": short["feed_views"], "status": ShortLinkStatus.PENDING,
         "decision_log_id": _next_watch(short, t, join_low)}
        for rank, t in enumerate(short["targets"], 1)
    ]
    supabase().table("short_link_recommendations").insert(rows).execute()
    return len(rows)


def _counts(plan: dict) -> dict:
    return {k: plan[k] for k in ("channel_id", "refused", "shorts", "already",
                                 "skipped_unembedded", "no_targets", "targets_unembedded")}


def refresh(channel_id: str) -> dict:
    """Recommend targets for up to SHORT_LINK_MAX_PER_RUN of the channel's
    Shorts that have no rows yet, as `pending` rows, with next-watch asked in
    shadow per pair. A Short that has rows is never re-recommended, so a
    person's tick or dismissal stands; one with no vector or no target is
    tried again next run.

    Returns the counts of `_plan` plus `attempted`/`errored` (Shorts, for
    job_status.item_error_verdict), `recommended` and `rows`. A Short whose
    write raises is logged and counted, and the others still run. Writes
    nothing when the thresholds are refused (`refused`).
    """
    plan = _plan(channel_id)
    counts = {**_counts(plan), "attempted": 0, "errored": 0, "recommended": 0, "rows": 0}
    for short in plan["plan"]:
        counts["attempted"] += 1
        try:
            counts["rows"] += _write(channel_id, short, plan["join_low"])
            counts["recommended"] += 1
        except Exception as e:
            counts["errored"] += 1
            log.warning("short_link_refresh %s: Short %s failed: %s", channel_id, short["id"], e)
    return counts


def preview(channel_id: str) -> dict:
    """`refresh`'s plan for the channel: the Shorts it would recommend, with
    their targets, and its counts. Writes nothing and asks no decide backend."""
    return _plan(channel_id)


def run_weekly() -> dict | None:
    """APScheduler entry point (`short_link_refresh`, Monday 10:30 UTC).

    `refresh` for every channel in SHORT_LINK_CHANNELS that is also in
    TRAFFIC_INGEST_CHANNELS (its feed views come from that report).
    traffic_poll's failure model: a channel that raises fails the run once
    every channel has run; per-Short errors are judged by
    job_status.item_error_verdict under `shorts`. A channel whose thresholds
    are refused is `degraded`, naming the reason. DB and OpenRouter only.
    """
    channels = sorted(settings.SHORT_LINK_CHANNELS & settings.TRAFFIC_INGEST_CHANNELS)
    if not channels:
        log.info("short_link_refresh: no channels (SHORT_LINK_CHANNELS ∩ "
                 "TRAFFIC_INGEST_CHANNELS); nothing to do")
        return None
    crashed: dict[str, str] = {}
    partial_errors: dict[str, str] = {}
    for cid in channels:
        try:
            counts = refresh(cid)
        except Exception as e:
            log.exception("short_link_refresh %s crashed: %s", cid, e)
            crashed[cid] = job_status.describe(e)
            continue
        log.info("short_link_refresh %s: %s", cid, counts)
        failure, partial = job_status.item_error_verdict(
            {SHORTS: (counts["errored"], counts["attempted"])})
        if counts["refused"]:
            partial = "; ".join(filter(None, [partial, f"refused: {counts['refused']}"]))
        if failure:
            crashed[cid] = f"ItemsFailed: {failure}"
        elif partial:
            partial_errors[cid] = partial
    if crashed:
        raise job_status.JobRunFailed("short_link_refresh", crashed)
    return {"partial_errors": partial_errors} if partial_errors else None
