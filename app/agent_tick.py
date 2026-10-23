"""Slice 1 · S1.4b — the agent tick's video work (spec Part 4 S1.4, Part 2 §2.1, §2.2, §1.3, §6.1; #65).

On a channel with `agent_enabled`, `autopilot.tick` runs its gates (eligibility,
resync, daily cap, quota) and then hands the video work here instead of the
audit path. Nothing here calls `audit_video`: the title lever is off until
Slice 3.

    run(channel)            -- one video: pick → triage → record → (treated) apply
    preview(channel_id, n)  -- the same up to the render, recording nothing
                               (scripts/preview_backlinks.py)

Pick: the first of the warm pool (`warm.warm_pool`, with its explore share and
S1.4a's cooldown and once-per-experiment exclusions). Triage: `decide(TRIAGE,
…)`, the rules answer used and the backend's logged in shadow. A video triaged
to `backlinks` (either arm) also gets `decide(NEXT_WATCH, …)` per candidate
pair, in shadow (S1.5), stored as `triage_json.next_watch`. Record, through
`interventions.record` (one active Midas intervention per video):

  - `no_change` -> `declined`, arm `n/a`, with the rationale;
  - `backlinks`, holdout -> `holdout`, with the targets it would have got;
  - `backlinks`, treated -> `planned`, then `backlinks_apply.apply_backlinks`:
    success makes it `measuring` (S1.3 does that); a refusal or failure makes
    it `cancelled` with `payload.error = {reason, detail}`, `reason` being the
    ApplyOutcome (`apply_disabled` while BACKLINK_APPLY_ENABLED is false), and
    the ApplyError goes on to the tick, which reacts as for an audit apply.

The decisions and the intervention point at each other: `triage_json` holds the
`decision_log_id` (and each pair's, under `next_watch`), and `decide.link` sets
`decision_log.intervention_id` on every one.
"""
from __future__ import annotations

import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app import backlinks, backlinks_apply, decide, human_edits, interventions, reach, warm
from app.apply_outcome import ApplyError
from app.config import settings
from app.db import supabase
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID, TRAFFIC_SOURCE_TYPES
from app.rows import all_rows
from app.status_vocab import (
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
    LeverVerdictScope,
)

log = logging.getLogger("midas.agent_tick")

#: The triage context's traffic mix and "recent interventions" span: the
#: video's latest this-many ingested traffic data-days (Part 4 S1.4, "the
#: 28-day traffic mix"), and interventions created in the last this-many days.
CONTEXT_DAYS = 28

#: tick.outcome when the warm pool has nothing to pick.
NO_VIDEO = "no_video"
#: tick.outcome when the pick already has an active Midas intervention (a race
#: with another writer; the pool excludes them).
ACTIVE_INTERVENTION = "active_intervention"
#: tick.outcome, and `payload.error.reason`, for a treated row under DRY_RUN.
DRY_RUN = "dry_run"
#: `payload.error.reason` when apply_backlinks raised something unclassified.
APPLY_EXCEPTION = "apply_exception"

_VIDEO_COLUMNS = "id,channel_id,title,description"


def backlinks_stopped(channel_id: str) -> bool:
    """Whether the backlinks lever has stopped for the channel (the P1 stop
    rule, spec Part 4 S1.6): any of its treated-vs-holdout weekly verdicts has
    `stop_rule_triggered` (app/lever_verdicts.py). Once stopped, it stays so."""
    rows = (
        supabase().table("lever_verdicts").select("id")
        .eq("channel_id", channel_id).eq("lever", InterventionLever.BACKLINKS)
        .eq("arm_scope", LeverVerdictScope.TREATED_VS_HOLDOUT)
        .eq("stop_rule_triggered", True).limit(1).execute()
    ).data or []
    return bool(rows)


def _video(video_id: str) -> dict | None:
    rows = (
        supabase().table("videos").select(_VIDEO_COLUMNS)
        .eq("id", video_id).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def _latest(covered: set[str], n: int) -> set[str]:
    return set(sorted(covered, reverse=True)[:n])


def _traffic_mix(video: dict) -> dict[str, int]:
    """Views by source type over the channel's latest CONTEXT_DAYS ingested
    traffic data-days (B1, `video_traffic_source_daily`)."""
    covered = reach.coverage(video["channel_id"], report_type=TRAFFIC_REPORT_TYPE_ID)
    if not covered:
        return {}
    window = _latest(covered, CONTEXT_DAYS)
    by_type: dict[int, int] = defaultdict(int)
    for r in all_rows(
        supabase().table("video_traffic_source_daily")
        .select("source_type,date,views")
        .eq("video_id", video["id"])
        .gte("date", min(window))
        .lte("date", max(window))
    ):
        if r["date"] in window:
            by_type[r["source_type"]] += r["views"]
    return {TRAFFIC_SOURCE_TYPES.get(t, str(t)): n for t, n in sorted(by_type.items())}


def _reach(video: dict) -> tuple[int, float | None]:
    """(impressions, CTR) over the warm window: the channel's latest
    WARM_WINDOW_DAYS ingested reach data-days, as the pool ranks by."""
    covered = reach.coverage(video["channel_id"])
    if not covered:
        return 0, None
    window = _latest(covered, settings.WARM_WINDOW_DAYS)
    rows = [
        r for r in all_rows(
            supabase().table("video_reach_daily")
            .select("video_id,date,impressions,ctr")
            .eq("video_id", video["id"])
            .gte("date", min(window))
            .lte("date", max(window))
        )
        if r["date"] in window
    ]
    return reach.weighted_ctr(rows)


def _recent_interventions(video_id: str) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=CONTEXT_DAYS)).isoformat()
    return all_rows(
        supabase().table("interventions")
        .select("lever,origin,arm,status,created_at")
        .eq("video_id", video_id)
        .gte("created_at", since)
    )


def _has_related_block(video: dict) -> bool:
    """D5: the description already links to one of our videos (any channel),
    other than itself."""
    linked = human_edits.video_links(video.get("description")) - {video["id"]}
    return bool(linked and human_edits.our_videos(linked))


def _assess(video: dict) -> tuple[backlinks.Candidates, dict]:
    """The candidates and the triage context for `video`. Reads only."""
    found = backlinks.candidates(video)
    impressions, ctr = _reach(video)
    context = {
        "has_related_block": _has_related_block(video),
        "backlink_candidates": len(found.rows),
        "backlinks_stopped": backlinks_stopped(video["channel_id"]),
        "traffic_mix_28d": _traffic_mix(video),
        "impressions": impressions,
        "ctr": ctr,
        "recent_interventions": _recent_interventions(video["id"]),
    }
    return found, context


def _rationale(context: dict) -> str:
    """Why the rules said no_change, in their order."""
    if context["backlinks_stopped"]:
        return "the backlinks lever has stopped for this channel"
    if context["has_related_block"]:
        return "the description already links to one of our videos (D5)"
    return (f"{context['backlink_candidates']} backlink candidates, fewer than "
            f"BACKLINK_MIN_CANDIDATES = {settings.BACKLINK_MIN_CANDIDATES}")


def _targets(found: backlinks.Candidates) -> list[dict]:
    """The top BACKLINK_MAX candidates, in link order."""
    return found.rows[:settings.BACKLINK_MAX]


def _next_watch(video: dict, found: backlinks.Candidates) -> list[dict]:
    """S1.5: `decide(NEXT_WATCH, …)` for every pair `candidates` returned
    (not only the targets kept), the rules answer used and the backend's
    logged in shadow. One decision_log row per pair; the per-pair results go
    on the intervention's `triage_json.next_watch`."""
    out = []
    for c in found.rows:
        context = {"source_video_id": video["id"], "source_title": video.get("title"),
                   "target_video_id": c["video_id"], "target_channel_id": c["channel_id"],
                   "target_title": c.get("title"), "similarity": c["similarity"],
                   "join_low": found.join_low}
        d = decide.decide(decide.NEXT_WATCH, f"{video['id']}->{c['video_id']}", context)
        out.append({"target_video_id": c["video_id"], "similarity": c["similarity"],
                    "decision_log_id": d.log_id, "answer": d.answer, "probs": d.probs})
    return out


def _cancel(row: dict, reason: str, detail: str | None, **payload) -> None:
    supabase().table("interventions").update({
        "status": InterventionStatus.CANCELLED,
        "payload": {**(row.get("payload") or {}), **payload,
                    "error": {"reason": reason, "detail": detail}},
    }).eq("id", row["id"]).execute()


def run(channel: dict, *, rng: random.Random | None = None) -> str:
    """Pick one warm video of `channel`, triage it, record the intervention,
    and apply a treated one. Returns the tick outcome.

    Raises the ApplyError of a treated row's refused or failed apply, after
    recording the row `cancelled`, so the tick can react (pause on a token
    expiry, go dormant on quotaExceeded, count a failure).
    """
    channel_id = channel["id"]
    picked = next(iter(warm.warm_pool(channel_id, rng=rng)), None)
    video = _video(picked["id"]) if picked else None
    if video is None:
        log.info("agent %s: warm pool has nothing to pick", channel_id)
        return NO_VIDEO

    found, context = _assess(video)
    decision = decide.decide(decide.TRIAGE, video["id"], context)
    triage = {
        "decision_log_id": decision.log_id,
        "question_set_version": decide.QUESTION_SET_VERSION,
        "answer": decision.answer,
        "probs": decision.probs,
        "context": context,
        "explore": picked.get("explore"),
        "candidates_reason": found.reason,
        "skipped_unembedded": found.skipped_unembedded,
    }

    common = dict(video_id=video["id"], channel_id=channel_id,
                  lever=InterventionLever.BACKLINKS, origin=InterventionOrigin.MIDAS,
                  triage_json=triage)
    try:
        if decision.answer != InterventionLever.BACKLINKS:
            row = interventions.record(
                **common, arm=InterventionArm.NOT_APPLICABLE,
                status=InterventionStatus.DECLINED,
                payload={"rationale": _rationale(context)})
        else:
            triage["next_watch"] = _next_watch(video, found)
            arm = interventions.assign_arm(video["id"], InterventionLever.BACKLINKS)
            row = interventions.record(
                **common, arm=arm,
                status=(InterventionStatus.HOLDOUT if arm == InterventionArm.HOLDOUT
                        else InterventionStatus.PLANNED),
                payload={"targets": _targets(found)})
    except interventions.ActiveInterventionExists as e:
        log.info("agent %s: %s", channel_id, e)
        return ACTIVE_INTERVENTION
    pair_log_ids = [p["decision_log_id"] for p in triage.get("next_watch", ())]
    for log_id in (decision.log_id, *pair_log_ids):
        decide.link(log_id, row["id"])
    log.info("agent %s: %s %s (intervention %s, arm %s)", channel_id, video["id"],
             row["status"], row["id"], row["arm"])
    if row["status"] != InterventionStatus.PLANNED:
        return row["status"]                     # declined, or holdout: no YouTube call

    try:
        result = backlinks_apply.apply_backlinks(row)
    except ApplyError as e:
        _cancel(row, e.outcome.value, e.detail)
        raise
    except Exception as e:
        _cancel(row, APPLY_EXCEPTION, f"{type(e).__name__}: {e}")
        raise
    if result.get("status") == DRY_RUN:
        _cancel(row, DRY_RUN, "DRY_RUN: nothing sent to YouTube",
                description=result.get("description"))
        return DRY_RUN
    return result.get("status") or InterventionStatus.MEASURING


def preview(channel_id: str, n: int) -> list[dict]:
    """What the next `n` agent ticks on the channel would do, up to the render.

    Reads only: no intervention, no decision_log row (the rules are asked
    directly; no backend call), no YouTube call. Each item has the video, the
    rules answer, the arm, the targets, the description before and after, and
    a render refusal (`refused`) instead of `after` when the block can't be
    rendered (no heading for the language yet, S1.2). A holdout's `after` is
    what it would have got.
    """
    rows = (
        supabase().table("channels").select("default_language")
        .eq("id", channel_id).limit(1).execute()
    ).data or []
    language = rows[0].get("default_language") if rows else None

    out = []
    for picked in warm.warm_pool(channel_id)[:n]:
        video = _video(picked["id"])
        if video is None:
            continue
        found, context = _assess(video)
        answer = decide.TRIAGE.rules(context)
        item = {"video_id": video["id"], "title": video.get("title"),
                "explore": picked.get("explore"), "answer": answer, "arm": None,
                "rationale": None, "targets": [], "before": video.get("description") or "",
                "after": None, "refused": None, "context": context}
        if answer != InterventionLever.BACKLINKS:
            item["rationale"] = _rationale(context)
        else:
            item["arm"] = interventions.assign_arm(video["id"], InterventionLever.BACKLINKS)
            item["targets"] = _targets(found)
            try:
                item["after"] = backlinks.render(video.get("description"), item["targets"], language)
            except backlinks.RenderRefused as e:
                item["refused"] = str(e)
        out.append(item)
    return out
