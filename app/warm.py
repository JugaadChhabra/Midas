"""Phase B · B4 — the warm filter (spec Part 2 §2.1, Part 3 B4; #35).

A channel's eligible ("warm") pool for Slice 1's pick:

    ranked_pool(channel_id)          -- the pool, most impressions first (deterministic)
    explore_order(ranked, pct, rng)  -- the pick order, WARM_EXPLORE_PCT of it exploration
    warm_pool(channel_id, rng=None)  -- both

Warm means: public, not an episode, on a channel whose reach is certified
(`reach.certify`), with >= WARM_MIN_IMPRESSIONS over the channel's latest
WARM_WINDOW_DAYS *ingested* reach data-days, and not held by a Midas intervention.

Held (S1.4a, spec Part 4 S1.4 "Pick", finding 2), by any Midas row that is:
  - active (status_vocab.ACTIVE_INTERVENTION_STATUSES), as B4;
  - created within TRIAGE_COOLDOWN_DAYS, whatever its lever or status: a
    `no_change` is `declined`, not active, and would be offered again next tick;
  - a `backlinks` row of either arm (treated or holdout), at any age: each video
    is in the backlinks experiment once;
  - a `title` row (S3.5) of the holdout arm, or of the treated arm unless it was
    cancelled before reaching YouTube, at any age: a judged, reverted or
    declined title never re-enters the title experiment.

Ingested, not calendar: the window is the latest WARM_WINDOW_DAYS days the
reach ledger has a report for (`reach.coverage`), so a gap in ingestion
reaches further back instead of counting days nobody watched as zero.

Only Midas interventions hold a video, as in `interventions.active_for` (§1.6).
A `human` row records an edit and never closes, so counting it would bar every
video the team has ever touched.

The ranking runs in-app or in Postgres (`warm_pool()`, migration
20261030020000) behind WARM_POOL_USE_RPC, as next_audit_candidate does; the
two are held together by tests/test_warm_pool_parity.py. The explore share is
drawn here, over either, with an injectable `random.Random`.

The agent tick (app/agent_tick.py, S1.4b) picks from `warm_pool`; the tick
checks `channels.agent_enabled` itself (`eligibility.can_run_agent`).

`warm_pool` also leaves out Shorts (`videos.is_short` true; NULL, not yet
probed, stays in), on either path: links in a Short's description aren't
clickable, so a backlink block there is a wasted apply and a row the
experiment can't learn from. `ranked_pool` stays the twin of the SQL function.
"""
from __future__ import annotations

import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app import reach
from app.config import settings
from app.db import supabase
from app.rows import all_rows, rows_for_ids
from app.status_vocab import (
    ACTIVE_INTERVENTION_STATUSES,
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
)

log = logging.getLogger("midas.warm")


def _rpc_params(channel_id: str) -> dict:
    return {
        "p_channel_id": channel_id,
        "p_min_impressions": settings.WARM_MIN_IMPRESSIONS,
        "p_window_days": settings.WARM_WINDOW_DAYS,
        # certify's window, for the SQL twin of reach.certify_covered.
        "p_measurement_window_days": reach.window_length(),
        "p_cooldown_days": settings.TRIAGE_COOLDOWN_DAYS,
    }




def _holds(row: dict, cooldown_start: datetime) -> bool:
    """Whether a Midas intervention row keeps its video out of the pool."""
    if row["status"] in ACTIVE_INTERVENTION_STATUSES:
        return True
    # Once per experiment: a holdout row, or a treated row whose write reached
    # YouTube. A treated row cancelled before its write never gave the video a
    # block, so it doesn't use up the video (as warm_pool() in SQL).
    if row["lever"] == InterventionLever.BACKLINKS and (
            row["arm"] == InterventionArm.HOLDOUT
            or (row["arm"] == InterventionArm.TREATED and row.get("applied_at"))):
        return True
    # Titles (S3.5): the same, and a treated row that never reached YouTube
    # but wasn't cancelled either (an agent decline, measured in the agent's
    # arm), so a judged, reverted or declined title never comes back.
    if row["lever"] == InterventionLever.TITLE and (
            row["arm"] == InterventionArm.HOLDOUT
            or (row["arm"] == InterventionArm.TREATED
                and (row.get("applied_at") or row["status"] != InterventionStatus.CANCELLED))):
        return True
    created = row.get("created_at")
    return created is not None and (
        datetime.fromisoformat(created.replace("Z", "+00:00")) > cooldown_start)


def _ranked_pool_rpc(channel_id: str) -> list[dict]:
    # A set-returning RPC is capped at 1000 rows like a table, and the bigger
    # channels' pools are past that (A7: Hindi 1,120), so it is paged.
    return all_rows(
        supabase().rpc("warm_pool", _rpc_params(channel_id)).order("impressions", desc=True)
    )


def warm_impressions(channel_id: str) -> dict[str, int]:
    """{video_id: impressions} for the channel's videos at or over
    WARM_MIN_IMPRESSIONS across its latest WARM_WINDOW_DAYS ingested reach
    data-days; {} when its reach isn't certified.

    The warmth measure alone, with none of the pool's other filters: S1.1's
    backlink targets (app/backlinks.py) need a video to be warm, not free of
    an intervention. A video in `video_reach_daily` but not in `videos` is here.
    """
    covered = reach.coverage(channel_id)
    if not reach.certify_covered(covered)["certified"]:
        return {}
    window = set(sorted(covered, reverse=True)[:settings.WARM_WINDOW_DAYS])

    impressions: dict[str, int] = defaultdict(int)
    for r in all_rows(
        supabase().table("video_reach_daily")
        .select("video_id,date,impressions")
        .eq("channel_id", channel_id)
        .gte("date", min(window))
        .lte("date", max(window))
    ):
        if r["date"] in window:
            impressions[r["video_id"]] += r["impressions"]
    return {vid: n for vid, n in impressions.items() if n >= settings.WARM_MIN_IMPRESSIONS}


def _ranked_pool_inapp(channel_id: str) -> list[dict]:
    impressions = warm_impressions(channel_id)
    warm = set(impressions)

    videos = rows_for_ids(
        lambda c: (
            supabase().table("videos")
            .select("id,privacy_status,is_episode")
            .eq("channel_id", channel_id)
            .in_("id", c)
        ),
        warm,
    )
    cooldown_start = datetime.now(timezone.utc) - timedelta(days=settings.TRIAGE_COOLDOWN_DAYS)
    held = {
        r["video_id"] for r in rows_for_ids(
            lambda c: (
                supabase().table("interventions")
                .select("video_id,lever,arm,status,created_at,applied_at")
                .eq("origin", InterventionOrigin.MIDAS)
                .in_("video_id", c)
            ),
            warm,
        )
        if _holds(r, cooldown_start)
    }
    pool = [
        {"id": v["id"], "impressions": impressions[v["id"]]}
        for v in videos
        # NULL privacy / is_episode = not yet known, eligible (as next_audit_candidate).
        if v.get("privacy_status") in (None, "public")
        and v.get("is_episode") is not True
        and v["id"] not in held
    ]
    pool.sort(key=lambda r: r["id"])
    pool.sort(key=lambda r: r["impressions"], reverse=True)
    return pool


def ranked_pool(channel_id: str) -> list[dict]:
    """The channel's warm pool as `{id, impressions}`, most impressions first, id tie-break."""
    if settings.WARM_POOL_USE_RPC:
        try:
            return _ranked_pool_rpc(channel_id)
        except Exception:
            log.warning("warm_pool RPC failed; falling back to the in-app pool", exc_info=True)
    return _ranked_pool_inapp(channel_id)


def explore_order(ranked: list[dict], explore_pct: float, rng: random.Random) -> list[dict]:
    """The pick order over a ranked pool: each pick is the best video left, or,
    with probability `explore_pct`, a uniformly random one from the rest.

    Every row comes back once, copied, with `explore` saying which kind of
    pick it was. The input isn't modified.
    """
    left = list(ranked)
    order = []
    while left:
        if len(left) > 1 and rng.random() < explore_pct:
            order.append({**left.pop(rng.randrange(1, len(left))), "explore": True})
        else:
            order.append({**left.pop(0), "explore": False})
    return order


def _without_shorts(pool: list[dict]) -> list[dict]:
    shorts = {
        v["id"] for v in rows_for_ids(
            lambda c: supabase().table("videos").select("id,is_short").in_("id", c),
            [r["id"] for r in pool],
        )
        if v.get("is_short") is True
    }
    return [r for r in pool if r["id"] not in shorts]


def warm_pool(channel_id: str, *, rng: random.Random | None = None) -> list[dict]:
    """The channel's warm pool in pick order, WARM_EXPLORE_PCT of it
    exploration, Shorts left out (module docstring)."""
    return explore_order(_without_shorts(ranked_pool(channel_id)), settings.WARM_EXPLORE_PCT,
                         rng or random.Random())
