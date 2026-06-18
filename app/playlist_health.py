"""Phase 1B Step 2 — Playlist health scoring (recommend-only).

Reads weekly `playlist_metrics` rows produced by Phase 0's `metrics_poll`,
aggregates the trailing window per playlist, applies the `MIN_PLAYLIST_STARTS`
data gate, computes a tier-1 session-contribution score, ranks per-channel
percentiles, and writes `playlists.health_score` /
`playlists.health_recommendation` / `playlists.health_computed_at` /
`playlists.health_rationale_json`.

No YouTube writes. No `playlistItems.insert/delete`. No `playlists.delete`.
This module **only writes to the `playlists.health_*` columns** — that is the
"recommend-only" contract from PHASE_1B_PLAN.md §1 / §6.

Tier-2 scoring (`insightTrafficSource=PLAYLIST` member breakdown — Gap 6) is
intentionally deferred to Step B. Every recommendation rationale carries
`tier_2_pending=true` until that ships; downstream consumers must not treat
the tier-1-only score as final.

Spec references:
  - PO §Sensor "Min-data + age gate" (the MIN_PLAYLIST_STARTS gate)
  - PO §Sensor "Gotchas" (web-only counts → per-channel relative comparison)
  - PO §Control loop "Decision policy" (the metric pair that drives the score)
  - PHASE_1B_PLAN.md §5 (the implementation contract this module honours)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.db import supabase

log = logging.getLogger("midas.playlist_health")


# Sentinel recommendation values. Mirror the
# `revive | remove | keep | insufficient_data` enum in the migration comment.
_REC_REMOVE = "remove"
_REC_REVIVE = "revive"
_REC_KEEP = "keep"
_REC_INSUFFICIENT = "insufficient_data"


# ── Aggregation ──────────────────────────────────────────────────────────────


def _aggregate_window(rows: list[dict]) -> dict | None:
    """Aggregate up to PLAYLIST_HEALTH_AGG_WEEKS rows for one playlist.

    Returns a dict with summed playlist_starts and impressions-weighted-average
    views_per_playlist_start + avg_time_in_playlist_sec. Returns None when
    every row has zero starts (defensive — division by zero would otherwise
    explode the weighted-average; treat as 'no signal').
    """
    if not rows:
        return None
    total_starts = sum(int(r.get("playlist_starts") or 0) for r in rows)
    if total_starts <= 0:
        return None
    weighted_vps_num = sum(
        float(r.get("views_per_playlist_start") or 0.0)
        * int(r.get("playlist_starts") or 0)
        for r in rows
    )
    weighted_atip_num = sum(
        int(r.get("avg_time_in_playlist_sec") or 0)
        * int(r.get("playlist_starts") or 0)
        for r in rows
    )
    return {
        "playlist_starts": total_starts,
        "views_per_playlist_start": weighted_vps_num / total_starts,
        "avg_time_in_playlist_sec": weighted_atip_num / total_starts,
        "rows_aggregated": len(rows),
    }


def _percentile(score: float, ranked_scores: list[float]) -> int:
    """Per-channel percentile rank, 1–100 (lower = worse).

    Uses the standard "average rank" method for ties: a tied group spanning
    1-indexed positions [a..b] gets rank (a+b)/2. This prevents the
    pathological case where every playlist scores 0 (e.g. a brand-new
    channel) collapses all percentiles to 100 → all 'keep'. Ties now land
    at their midpoint, so a uniform-zero channel maps to ~50 → still 'keep'
    (correct — no signal to recommend remove), but a single bottom cluster
    of K tied lowest scores correctly lands at percentile ≈ ceil(50K/n)
    instead of 100.

    Special case `n <= 1`: single gate-passing playlist can't be ranked
    against itself; returns 100 (→ keep). Caller can detect via the
    `gated_in` count in the summary.
    """
    n = len(ranked_scores)
    if n <= 1:
        return 100
    count_below = sum(1 for s in ranked_scores if s < score)
    count_equal = sum(1 for s in ranked_scores if s == score)
    if count_equal == 0:
        return 100  # score isn't in the set; defensive — shouldn't happen
    avg_rank = count_below + (count_equal + 1) / 2.0   # 1-indexed midpoint
    return max(1, min(100, math.ceil(100.0 * avg_rank / n)))


def _classify(percentile: int, remove_pctl: int, revive_pctl: int) -> str:
    if percentile <= remove_pctl:
        return _REC_REMOVE
    if percentile <= revive_pctl:
        return _REC_REVIVE
    return _REC_KEEP


# ── Per-channel scoring entry point ──────────────────────────────────────────


def score_channel(channel_id: str) -> dict[str, Any]:
    """Compute and persist health scores + recommendations for one channel.

    Does NOT check `channels.playlist_health_enabled` here — that gating
    happens at the caller (Step 4's cron + Step 3's endpoint). Keeping the
    function flag-agnostic makes it directly invocable for ops debugging.

    Returns a summary dict suitable for logging:
      {
        "channel_id": ...,
        "playlists_total": int,
        "gated_in": int,            # passed MIN_PLAYLIST_STARTS
        "insufficient_data": int,
        "remove": int, "revive": int, "keep": int,
        "computed_at": iso8601,
      }
    """
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

    # Pull every playlist on the channel (paginate past Supabase 1000-row cap
    # for symmetry with metrics_poll, even though hitting that cap on
    # playlists is hypothetical today).
    playlists: list[dict] = []
    offset = 0
    PAGE = 1000
    while True:
        page = (
            supabase().table("playlists")
            .select("id,title")
            .eq("channel_id", channel_id)
            .range(offset, offset + PAGE - 1)
            .execute()
            .data or []
        )
        playlists.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE

    if not playlists:
        log.info("playlist_health %s: no playlists", channel_id)
        return {
            "channel_id": channel_id,
            "playlists_total": 0,
            "gated_in": 0,
            "insufficient_data": 0,
            "remove": 0, "revive": 0, "keep": 0,
            "computed_at": now_iso,
        }

    playlist_ids = [p["id"] for p in playlists]

    # Pull the last N weekly windows per playlist. Fetch ordered by window_end
    # desc; `_aggregate_window` ignores any extras. Single query covers all
    # playlists; group in Python to avoid N round-trips. Bound to recent
    # AGG_WEEKS windows via a min window_end cutoff so old rows from prior
    # months don't drown out the trailing aggregation.
    aggregation_weeks = settings.PLAYLIST_HEALTH_AGG_WEEKS
    # Conservative cutoff: agg_weeks * 7 days, plus 14 days of slack for the
    # 2-day Analytics lag + per-row drift. Anything older is definitely not
    # in the current trailing window.
    cutoff_dt = now_dt.date().toordinal() - (aggregation_weeks * 7 + 14)
    # Use ISO date string for the supabase query.
    from datetime import date as _date
    cutoff_iso = _date.fromordinal(cutoff_dt).isoformat()

    # Chunk playlist_ids and paginate the rows within each chunk so we never
    # hit Supabase's 1000-row default cap. Without chunking, a channel with
    # >250 playlists (1000 rows / 4 weekly windows) would silently lose
    # metric rows for the alphabetic tail of playlist_ids — those rows would
    # never be aggregated and every affected playlist would land in
    # insufficient_data with no signal that it was a query truncation, not a
    # real data gap.
    METRIC_ID_CHUNK = 100
    METRIC_ROW_PAGE = 1000
    metric_rows: list[dict] = []
    for chunk_start in range(0, len(playlist_ids), METRIC_ID_CHUNK):
        id_chunk = playlist_ids[chunk_start:chunk_start + METRIC_ID_CHUNK]
        row_offset = 0
        while True:
            page = (
                supabase().table("playlist_metrics")
                .select("playlist_id,window_start,window_end,playlist_starts,"
                        "views_per_playlist_start,avg_time_in_playlist_sec")
                .in_("playlist_id", id_chunk)
                .gte("window_end", cutoff_iso)
                .order("window_end", desc=True)
                .range(row_offset, row_offset + METRIC_ROW_PAGE - 1)
                .execute()
                .data or []
            )
            metric_rows.extend(page)
            if len(page) < METRIC_ROW_PAGE:
                break
            row_offset += METRIC_ROW_PAGE

    # Group + keep only the most-recent AGG_WEEKS rows per playlist.
    by_pid: dict[str, list[dict]] = {}
    for r in metric_rows:
        bucket = by_pid.setdefault(r["playlist_id"], [])
        if len(bucket) < aggregation_weeks:
            bucket.append(r)

    # Aggregate + gate.
    aggregated: dict[str, dict] = {}      # playlist_id -> agg dict (gated in)
    insufficient: list[str] = []          # playlist_ids that fail the gate
    for pid in playlist_ids:
        agg = _aggregate_window(by_pid.get(pid) or [])
        if agg is None or agg["playlist_starts"] < settings.MIN_PLAYLIST_STARTS:
            insufficient.append(pid)
            continue
        aggregated[pid] = agg

    # Compute scores (tier-1 only — tier-2 deferred per PHASE_1B_PLAN.md §9).
    scores: dict[str, float] = {
        pid: agg["avg_time_in_playlist_sec"] * agg["views_per_playlist_start"]
        for pid, agg in aggregated.items()
    }

    # Sorted ascending for percentile lookup. The list can be empty (every
    # playlist failed the gate) — handled by the per-row loop below.
    ranked = sorted(scores.values())

    # ── Write back ──────────────────────────────────────────────────────────
    # Under strict thresholds (decision #7: remove=5, revive=20), small
    # channels cannot reach the `remove` band by design — with n=10 gate-
    # passing playlists the lowest percentile is ceil(100*1/10) = 10, above
    # the 5 cutoff. This is a deliberate safety property: don't auto-
    # recommend `remove` on thin signal. The bottom playlist of a small
    # channel still surfaces as `revive` for human review.
    counts = {"remove": 0, "revive": 0, "keep": 0}
    title_by_id = {p["id"]: p.get("title") for p in playlists}
    gated_n = len(ranked)
    # Approximate smallest n where `remove` is reachable, given current pctl.
    min_n_for_remove = (
        math.ceil(100.0 / settings.PLAYLIST_HEALTH_REMOVE_PCTL)
        if settings.PLAYLIST_HEALTH_REMOVE_PCTL > 0 else 0
    )
    small_channel = gated_n < min_n_for_remove

    payload: list[dict] = []

    # 1. Gate-passing playlists get a real score + classification.
    for pid, score in scores.items():
        pctl = _percentile(score, ranked)
        rec = _classify(
            pctl,
            settings.PLAYLIST_HEALTH_REMOVE_PCTL,
            settings.PLAYLIST_HEALTH_REVIVE_PCTL,
        )
        counts[rec] += 1
        agg = aggregated[pid]
        rationale: dict[str, Any] = {
            "gate": "pass",
            "window_weeks": aggregation_weeks,
            "rows_aggregated": agg["rows_aggregated"],
            "playlist_starts": agg["playlist_starts"],
            "views_per_playlist_start": agg["views_per_playlist_start"],
            "avg_time_in_playlist_sec": agg["avg_time_in_playlist_sec"],
            "score_tier_1": float(score),
            "percentile": pctl,
            "thresholds": {
                "remove_pctl": settings.PLAYLIST_HEALTH_REMOVE_PCTL,
                "revive_pctl": settings.PLAYLIST_HEALTH_REVIVE_PCTL,
            },
            "tier_2_pending": True,
            "comparison": f"percentile {pctl} of {gated_n} gated playlists on this channel",
        }
        if small_channel:
            rationale["small_channel_note"] = (
                f"only {gated_n} playlist(s) passed the gate; `remove` band "
                f"unreachable with REMOVE_PCTL={settings.PLAYLIST_HEALTH_REMOVE_PCTL} "
                f"(needs ≥{min_n_for_remove}). Lowest scorer surfaces as `revive` "
                f"for human review."
            )
        payload.append({
            "id": pid,
            # channel_id + title included so the INSERT-fallback path of
            # UPSERT cannot violate playlists.{channel_id,title} NOT NULL if
            # the row is concurrently deleted between our SELECT and this
            # write. They are also unchanged on UPDATE (same values), so
            # this is a no-op for the common path.
            "channel_id": channel_id,
            "title": title_by_id.get(pid),
            "health_score": float(score),
            "health_recommendation": rec,
            "health_computed_at": now_iso,
            "health_rationale_json": rationale,
        })

    # 2. Gate-failing playlists get insufficient_data + null score.
    for pid in insufficient:
        starts = sum(int(r.get("playlist_starts") or 0) for r in (by_pid.get(pid) or []))
        payload.append({
            "id": pid,
            "channel_id": channel_id,
            "title": title_by_id.get(pid),
            "health_score": None,
            "health_recommendation": _REC_INSUFFICIENT,
            "health_computed_at": now_iso,
            "health_rationale_json": {
                "gate": "fail",
                "reason": "below_min_playlist_starts",
                "window_weeks": aggregation_weeks,
                "playlist_starts_in_window": starts,
                "min_required": settings.MIN_PLAYLIST_STARTS,
                "tier_2_pending": True,
            },
        })

    # Single upsert; on_conflict=id updates the health_* columns on existing
    # rows. channel_id + title are duplicated (defensive) so the INSERT
    # fallback path is safe under a delete race.
    if payload:
        supabase().table("playlists").upsert(payload, on_conflict="id").execute()

    summary = {
        "channel_id": channel_id,
        "playlists_total": len(playlist_ids),
        "gated_in": len(aggregated),
        "insufficient_data": len(insufficient),
        "remove": counts["remove"],
        "revive": counts["revive"],
        "keep": counts["keep"],
        "computed_at": now_iso,
    }
    log.info("playlist_health %s: %s", channel_id, summary)
    return summary
