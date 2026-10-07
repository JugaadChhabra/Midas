"""Phase B · B4 — the warm filter (spec Part 2 §2.1, Part 3 B4; #35).

A channel's eligible ("warm") pool for Slice 1's pick:

    ranked_pool(channel_id)          -- the pool, most impressions first (deterministic)
    explore_order(ranked, pct, rng)  -- the pick order, WARM_EXPLORE_PCT of it exploration
    warm_pool(channel_id, rng=None)  -- both

Warm means: public, not an episode, on a channel whose reach is certified
(`reach.certify`), with >= WARM_MIN_IMPRESSIONS over the channel's latest
WARM_WINDOW_DAYS *ingested* reach data-days, and no active Midas intervention.

Ingested, not calendar: the window is the latest WARM_WINDOW_DAYS days the
reach ledger has a report for (`reach.coverage`), so a gap in ingestion
reaches further back instead of counting days nobody watched as zero.

Only Midas interventions hold a video, as in `interventions.active_for` (§1.6).
A `human` row records an edit and never closes, so counting it would bar every
video the team has ever touched.

The ranking runs in-app or in Postgres (`warm_pool()`, migration
20261006040000) behind WARM_POOL_USE_RPC, as next_audit_candidate does; the
two are held together by tests/test_warm_pool_parity.py. The explore share is
drawn here, over either, with an injectable `random.Random`.

Not called from the tick in Phase B: Slice 1's tick routing wires it in, and
checks `channels.agent_enabled` itself.
"""
from __future__ import annotations

import logging
import random
from collections import defaultdict

from app import reach
from app.config import settings
from app.db import supabase
from app.rows import all_rows, rows_for_ids
from app.status_vocab import ACTIVE_INTERVENTION_STATUSES, InterventionOrigin

log = logging.getLogger("midas.warm")


def _rpc_params(channel_id: str) -> dict:
    return {
        "p_channel_id": channel_id,
        "p_min_impressions": settings.WARM_MIN_IMPRESSIONS,
        "p_window_days": settings.WARM_WINDOW_DAYS,
        # certify's window, for the SQL twin of reach.certify_covered.
        "p_measurement_window_days": reach.window_length(),
    }


def _ranked_pool_rpc(channel_id: str) -> list[dict]:
    # A set-returning RPC is capped at 1000 rows like a table, and the bigger
    # channels' pools are past that (A7: Hindi 1,120), so it is paged.
    return all_rows(
        supabase().rpc("warm_pool", _rpc_params(channel_id)).order("impressions", desc=True)
    )


def _ranked_pool_inapp(channel_id: str) -> list[dict]:
    covered = reach.coverage(channel_id)
    if not reach.certify_covered(covered)["certified"]:
        return []
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
    warm = {vid for vid, n in impressions.items() if n >= settings.WARM_MIN_IMPRESSIONS}

    videos = rows_for_ids(
        lambda c: (
            supabase().table("videos")
            .select("id,privacy_status,is_episode")
            .eq("channel_id", channel_id)
            .in_("id", c)
        ),
        warm,
    )
    held = {
        r["video_id"] for r in rows_for_ids(
            lambda c: (
                supabase().table("interventions")
                .select("video_id")
                .eq("origin", InterventionOrigin.MIDAS)
                .in_("status", sorted(ACTIVE_INTERVENTION_STATUSES))
                .in_("video_id", c)
            ),
            warm,
        )
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


def warm_pool(channel_id: str, *, rng: random.Random | None = None) -> list[dict]:
    """The channel's warm pool in pick order, WARM_EXPLORE_PCT of it exploration."""
    return explore_order(ranked_pool(channel_id), settings.WARM_EXPLORE_PCT,
                         rng or random.Random())
