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

S2.5, the team's page and the tick (`router`, mounted in app/main.py):

    GET  /channels/{id}/short-links  -- Shorts with their recommendations, paged; ?format=csv
    POST /short-links/{id}/set       -- the team set this target in Studio: the human ledger
    POST /short-links/{id}/dismiss   -- the team says this target is wrong; no intervention

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

import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal, Mapping, NamedTuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app import decide, interventions, job_status, reach, warm
from app.backlinks import NO_THRESHOLDS, SOURCE_NOT_EMBEDDED, THRESHOLDS_OTHER_MODEL, _thresholds
from app.config import settings
from app.db import supabase
from app.embeddings import pooled_embeddings
from app.playlists import _cosine_sim
from app.reembed import MODEL_VERSION
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID
from app.rows import PAGE_SIZE, all_rows, rows_for_ids
from app.status_vocab import (
    ALL_SHORT_LINK_STATUSES,
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
    ShortLinkStatus,
)

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


# ── S2.5: the page, the tick, the ledger ─────────────────────────────────

router = APIRouter(tags=["short-links"])

_CSV_COLUMNS = ["short_id", "short_title", "short_url", "studio_url", "feed_views",
                "recommendation_id", "rank", "target_video_id", "target_title", "target_url",
                "similarity", "impressions", "status", "decided_at"]


def _short_url(video_id: str) -> str:
    return f"https://www.youtube.com/shorts/{video_id}"


def _studio_url(video_id: str) -> str:
    """Where the team sets a Short's related video."""
    return f"https://studio.youtube.com/video/{video_id}/edit"


def _video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _page(channel_id: str, status: str | None, limit: int, offset: int) -> dict:
    """One page of the channel's Shorts with their recommendations (rank
    order), Shorts with a pending row first, then by feed views, then id.

    The page is of Shorts, not rows, so a Short's targets never split across
    pages; that grouping is done here over the channel's rows (`all_rows`),
    which grow by at most SHORT_LINK_MAX_PER_RUN × SHORT_LINK_TARGETS a week.
    `status` keeps only the rows in it, and the Shorts that have one.
    """
    q = supabase().table("short_link_recommendations").select("*").eq("channel_id", channel_id)
    if status is not None:
        q = q.eq("status", status)
    by_short: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows(q):
        by_short[r["short_id"]].append(r)
    order = sorted(by_short, key=lambda sid: (
        not any(r["status"] == ShortLinkStatus.PENDING for r in by_short[sid]),
        -max(r.get("feed_views") or 0 for r in by_short[sid]), sid))
    page = order[offset:offset + limit]

    recs = [r for sid in page for r in by_short[sid]]
    titles = {v["id"]: v.get("title") for v in _videos(
        {r["short_id"] for r in recs} | {r["target_video_id"] for r in recs})}
    listed = []
    for sid in page:
        rows = sorted(by_short[sid], key=lambda r: (r["rank"], r["id"]))
        listed.append({
            "short_id": sid, "title": titles.get(sid),
            "youtube_url": _short_url(sid), "studio_url": _studio_url(sid),
            "feed_views": max(r.get("feed_views") or 0 for r in rows),
            "recommendations": [
                {"id": r["id"], "rank": r["rank"], "target_video_id": r["target_video_id"],
                 "title": titles.get(r["target_video_id"]),
                 "youtube_url": _video_url(r["target_video_id"]),
                 "similarity": r["similarity"], "impressions": r.get("impressions"),
                 "feed_views": r.get("feed_views"), "status": r["status"],
                 "decided_at": r.get("decided_at"), "intervention_id": r.get("intervention_id")}
                for r in rows],
        })
    return {"shorts": listed, "limit": limit, "offset": offset,
            "next_offset": offset + limit if len(page) == limit else None}


def _csv(channel_id: str, body: dict) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    w.writeheader()
    for s in body["shorts"]:
        for t in s["recommendations"]:
            w.writerow({"short_id": s["short_id"], "short_title": s["title"],
                        "short_url": s["youtube_url"], "studio_url": s["studio_url"],
                        "feed_views": s["feed_views"], "recommendation_id": t["id"],
                        "rank": t["rank"], "target_video_id": t["target_video_id"],
                        "target_title": t["title"], "target_url": t["youtube_url"],
                        "similarity": t["similarity"], "impressions": t["impressions"],
                        "status": t["status"], "decided_at": t["decided_at"]})
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="short-links-{channel_id}.csv"'},
    )


@router.get("/channels/{channel_id}/short-links")
def channel_short_links(
    channel_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    format: Literal["json", "csv"] = Query(default="json"),
):
    """The channel's Shorts with their recommended targets, one page of Shorts
    at a time (`_page`), as JSON or, with `format=csv`, the same page as CSV,
    one line per recommendation.

    Paged as `GET /channels/{id}/interventions`: `next_offset` is set whenever
    the page came back full, an unknown `status` is 400, and `limit` is at
    most PAGE_SIZE (422 above).
    """
    if status is not None and status not in ALL_SHORT_LINK_STATUSES:
        raise HTTPException(400, f"unknown status {status!r}")
    body = _page(channel_id, status, limit, offset)
    return _csv(channel_id, body) if format == "csv" else body


def _recommendation(recommendation_id: int) -> dict:
    rows = (supabase().table("short_link_recommendations").select("*")
            .eq("id", recommendation_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, f"unknown Short-link recommendation {recommendation_id}")
    return rows[0]


def _ledger_key(rec: Mapping) -> str:
    """The pair's human-ledger key; S2.6's traffic detection writes the same."""
    return f"short_link:{rec['short_id']}:{rec['target_video_id']}"


def _ledger_id(key: str) -> int:
    return (supabase().table("interventions").select("id")
            .eq("ledger_key", key).limit(1).execute().data)[0]["id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/short-links/{recommendation_id}/set")
def set_short_link(recommendation_id: int):
    """The team set this target on its Short in Studio (Part 2 §1.4, E11).

    Records one `human` `short_link` intervention on the target, keyed by the
    pair, so a pair already in the ledger (an earlier tick, or S2.6 seeing
    the link in the traffic) is linked rather than recorded twice. Then the
    Short's other pending or set rows become `not_chosen` (a dismissed one
    stays dismissed), and this one `set`, last: a tick that dies partway is
    redone whole by the next. Ticking a row already `set` changes nothing.
    Setting another target for a Short moves `set` and records a new
    intervention; the old one stays, since the link was on the Short.
    """
    rec = _recommendation(recommendation_id)
    if rec["status"] == ShortLinkStatus.SET:
        return {"recommendation": rec, "intervention_id": rec.get("intervention_id"),
                "recorded": False}
    now, key = _now(), _ledger_key(rec)
    stored = interventions.record(
        video_id=rec["target_video_id"], channel_id=rec["channel_id"],
        lever=InterventionLever.SHORT_LINK, origin=InterventionOrigin.HUMAN,
        arm=InterventionArm.NOT_APPLICABLE, status=InterventionStatus.APPLIED,
        detected_at=now, ledger_key=key,
        payload={"short_id": rec["short_id"], "target_video_id": rec["target_video_id"],
                 "recommendation_id": rec["id"], "timing": "ticked"},
    )
    intervention_id = stored["id"] if stored else _ledger_id(key)
    table = supabase().table("short_link_recommendations")
    (table.update({"status": ShortLinkStatus.NOT_CHOSEN, "decided_at": now})
     .eq("short_id", rec["short_id"]).neq("id", rec["id"])
     .in_("status", [ShortLinkStatus.PENDING, ShortLinkStatus.SET]).execute())
    updated = (supabase().table("short_link_recommendations")
               .update({"status": ShortLinkStatus.SET, "decided_at": now,
                        "intervention_id": intervention_id})
               .eq("id", rec["id"]).execute().data)[0]
    return {"recommendation": updated, "intervention_id": intervention_id,
            "recorded": stored is not None}


@router.post("/short-links/{recommendation_id}/dismiss")
def dismiss_short_link(recommendation_id: int):
    """The team says this target is wrong for its Short: `dismissed`, no
    intervention. A `set` row is refused (409): the link is on the Short, and
    the ledger says so; the team changes it by setting another target."""
    rec = _recommendation(recommendation_id)
    if rec["status"] == ShortLinkStatus.SET:
        raise HTTPException(409, "set: tick another target to change the Short's link")
    if rec["status"] == ShortLinkStatus.DISMISSED:
        return {"recommendation": rec}
    updated = (supabase().table("short_link_recommendations")
               .update({"status": ShortLinkStatus.DISMISSED, "decided_at": _now()})
               .eq("id", rec["id"]).execute().data)[0]
    return {"recommendation": updated}
