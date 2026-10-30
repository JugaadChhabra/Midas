"""Slice 1 · S1.4b — the agent tick's video work (spec Part 4 S1.4, Part 2 §2.1, §2.2, §1.3, §6.1; #65).

On a channel with `agent_enabled`, `autopilot.tick` runs its gates (eligibility,
resync, daily cap, quota) and then hands the video work here. Nothing here
calls `audit_video`: since Slice 3 S3.3 (#118) a title goes through
app/titles.py's writer and app/titles_apply.py's title-only write.

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
    the ApplyError goes on to the tick, which reacts as for an audit apply;
  - `title` (S3.3, after backlinks in the rules, on TITLE_CHANNELS only),
    holdout -> `holdout` with `{title_before}`, no writer call;
  - `title`, treated -> the path's writer, then `planned` and
    `titles_apply.apply_title` as backlinks (`_run_title`).

The decisions and the intervention point at each other: `triage_json` holds the
`decision_log_id` (and each pair's, under `next_watch`), and `decide.link` sets
`decision_log.intervention_id` on every one.
"""
from __future__ import annotations

import logging
import random
import time
from array import array
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app import backlinks, backlinks_apply, decide, human_edits, interventions, reach, warm
from app import lever_verdicts, titles, titles_apply
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
#: `payload.error.reason` when the title writer gave no candidate passing the
#: checks (Part 6 S3.3).
CHECKS_FAILED = "checks_failed"
#: `payload.error.reason` when the title writer raised (OpenRouter down, …).
WRITER_EXCEPTION = "writer_exception"

_VIDEO_COLUMNS = "id,channel_id,title,description,is_short"


def backlinks_stopped(channel_id: str) -> bool:
    """Whether the backlinks lever has stopped for the channel (the P1 stop
    rule, spec Part 4 S1.6): `lever_verdicts.stopped`. Once stopped, it stays so."""
    return lever_verdicts.stopped(channel_id)


def backlinks_enabled(language: str | None) -> bool:
    """Whether the backlinks lever can run on a channel in `language`: its
    writes are on and the language has a heading (S1.2)."""
    return settings.BACKLINK_APPLY_ENABLED and language in backlinks.HEADINGS


def titles_open(channel_id: str) -> bool:
    """`title_enabled`'s channel-level parts (Part 6 S3.3): the channel is in
    TITLE_CHANNELS, TITLE_APPLY_ENABLED is on, and the title lever hasn't
    stopped (`titles.stopped`)."""
    return (channel_id in settings.TITLE_CHANNELS and settings.TITLE_APPLY_ENABLED
            and not titles.stopped(channel_id))


def _today_start_iso() -> str:
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).isoformat()


def _titles_today(channel_id: str) -> tuple[int, int]:
    """(today's treated title rows that aren't declined, today's agent runs)
    on the channel, UTC day. One query: a day's title rows are bounded by the
    limits, far under the 1000-row page."""
    rows = (
        supabase().table("interventions").select("arm,status,payload")
        .eq("channel_id", channel_id)
        .eq("origin", InterventionOrigin.MIDAS)
        .eq("lever", InterventionLever.TITLE)
        .gte("created_at", _today_start_iso())
        .limit(1000)
        .execute()
    ).data or []
    treated = sum(1 for r in rows if r["arm"] == InterventionArm.TREATED
                  and r["status"] != InterventionStatus.DECLINED)
    agent = sum(1 for r in rows if (r.get("payload") or {}).get("path") == titles.AGENT)
    return treated, agent


def _title_enabled(channel_id: str, video_id: str) -> bool:
    """Part 6 S3.3: the lever is open on the channel, today's treated title
    rows are below TITLE_DAILY_CAP, and, for a video on the agent path, today's
    agent runs are below TITLE_AGENT_DAILY_RUNS."""
    if not titles_open(channel_id):
        return False
    treated, agent_runs = _titles_today(channel_id)
    return (treated < settings.TITLE_DAILY_CAP
            and (titles.route(channel_id, video_id) != titles.AGENT
                 or agent_runs < settings.TITLE_AGENT_DAILY_RUNS))


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


#: How long a channel's backlink target pool (`backlinks.target_pool`) is
#: reused before it is read again. Reading it pulls every warm target's
#: vector(3072) on the channel and its siblings, minutes for a channel with
#: many siblings; warmth and vectors change daily at most.
POOL_TTL_SECONDS = 3600

#: channel id -> (monotonic time read, pool or None, refusal reason, the
#: channel's `titles.ChannelContext` or None until a title triage asks for it).
_pools: dict[str, tuple[float, backlinks.Pool | None, str | None,
                        titles.ChannelContext | None]] = {}


def _pool(channel_id: str) -> tuple[backlinks.Pool | None, str | None]:
    """The channel's target pool, read at most once per POOL_TTL_SECONDS.

    Vectors are kept as `array('d')` (a third of a list of floats' memory) and
    shared between channels' pools, so a video that is a target for several
    channels is held, and read, once."""
    now = time.monotonic()
    hit = _pools.get(channel_id)
    if hit is not None and now - hit[0] < POOL_TTL_SECONDS:
        return hit[1], hit[2]
    known = {vid: vec for _, p, *_ in _pools.values() if p is not None
             for vid, vec in p.vectors.items()}
    pool, reason = backlinks.target_pool(channel_id, known_vectors=known)
    if pool is not None:
        pool = pool._replace(vectors={
            vid: vec if isinstance(vec, array) else array("d", vec)
            for vid, vec in pool.vectors.items()})
    _pools[channel_id] = (now, pool, reason, None)
    return pool, reason


def title_channel(channel_id: str) -> titles.ChannelContext:
    """The channel's title context (`titles.channel_context`: its warm long
    videos' impressions and CTR, their median CTR, the ceiling, the top
    performers), kept with the target pool and read again with it."""
    _pool(channel_id)
    read_at, pool, reason, channel = _pools[channel_id]
    if channel is None:
        channel = titles.channel_context(channel_id)
        _pools[channel_id] = (read_at, pool, reason, channel)
    return channel


def _assess(video: dict, language: str | None, *, backlinks_on: bool | None = None,
            titles_on: bool | None = None) -> tuple[backlinks.Candidates, dict]:
    """The candidates and the triage context for `video`, on a channel in
    `language`. `backlinks_enabled` is `backlinks_enabled(language)` unless
    `backlinks_on` says, and `title_enabled` `_title_enabled` unless
    `titles_on` says: each preview takes its own lever as open. Reads only."""
    channel_id = video["channel_id"]
    pool, reason = _pool(channel_id)
    found = (backlinks.candidates(video, pool=pool) if pool is not None
             else backlinks.Candidates([], reason=reason))
    impressions, ctr = _reach(video)
    title_on = _title_enabled(channel_id, video["id"]) if titles_on is None else titles_on
    channel = title_channel(channel_id) if title_on else None
    context = {
        "has_related_block": _has_related_block(video),
        "backlink_candidates": len(found.rows),
        "backlinks_enabled": (backlinks_enabled(language) if backlinks_on is None
                              else backlinks_on),
        "backlinks_stopped": backlinks_stopped(channel_id),
        "traffic_mix_28d": _traffic_mix(video),
        "impressions": impressions,
        "ctr": ctr,
        "recent_interventions": _recent_interventions(video["id"]),
        "title_enabled": title_on,
        "title_excluded": (video["id"] in settings.TITLE_EXCLUDE_VIDEOS
                           or (channel is not None and video["id"] in channel.ceiling)),
        "channel_median_ctr": channel.median_ctr if channel is not None else None,
        "is_short": video.get("is_short"),
    }
    return found, context


def _rationale(context: dict) -> str:
    """Why the rules said no_change, in their order: backlinks' reason, then,
    when the title lever was open for the video, the title's."""
    if not context.get("backlinks_enabled"):
        why = "backlinks can't run on this channel (BACKLINK_APPLY_ENABLED off or no heading)"
    elif context["backlinks_stopped"]:
        why = "the backlinks lever has stopped for this channel"
    elif context["has_related_block"]:
        why = "the description already links to one of our videos (D5)"
    else:
        why = (f"{context['backlink_candidates']} backlink candidates, fewer than "
               f"BACKLINK_MIN_CANDIDATES = {settings.BACKLINK_MIN_CANDIDATES}")
    if not context.get("title_enabled"):
        return why
    if context.get("is_short"):
        title = "a Short"
    elif context.get("title_excluded"):
        title = "excluded (the channel's ceiling or TITLE_EXCLUDE_VIDEOS)"
    elif context.get("ctr") is None or context.get("channel_median_ctr") is None:
        title = "no CTR to compare with the channel median"
    else:
        title = "CTR at or above the channel median"
    return f"{why}; title: {title}"


def _language(channel_id: str) -> str | None:
    rows = (
        supabase().table("channels").select("default_language")
        .eq("id", channel_id).limit(1).execute()
    ).data or []
    return rows[0].get("default_language") if rows else None


def _unrenderable(video: dict, targets: list[dict], language: str | None) -> str | None:
    """Why the block can't be rendered onto the stored description (e.g. the
    description would pass 5,000 characters), or None. Checked before the arm
    is drawn, so such a video is declined in either arm alike."""
    try:
        backlinks.render(video.get("description"), targets, language)
    except backlinks.RenderRefused as e:
        return str(e)
    return None


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

    found, context = _assess(video, channel.get("default_language"))
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

    if decision.answer == InterventionLever.TITLE:
        return _run_title(video, triage, decision)

    common = dict(video_id=video["id"], channel_id=channel_id,
                  lever=InterventionLever.BACKLINKS, origin=InterventionOrigin.MIDAS,
                  triage_json=triage)
    refused = (_unrenderable(video, _targets(found), _language(channel_id))
               if decision.answer == InterventionLever.BACKLINKS else None)
    if refused:
        triage["render_refused"] = refused
    try:
        if decision.answer != InterventionLever.BACKLINKS or refused:
            row = interventions.record(
                **common, arm=InterventionArm.NOT_APPLICABLE,
                status=InterventionStatus.DECLINED,
                payload={"rationale": (f"the block can't be rendered: {refused}" if refused
                                       else _rationale(context))})
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
    return _apply(row, backlinks_apply.apply_backlinks, "description")


def _apply(row: dict, apply, dry_run_key: str) -> str:
    """Send a planned treated row with `apply`; a refusal or failure cancels it
    with `payload.error` and re-raises for the tick; DRY_RUN cancels it with
    the rehearsal's `dry_run_key` kept on the payload."""
    try:
        result = apply(row)
    except ApplyError as e:
        _cancel(row, e.outcome.value, e.detail)
        raise
    except Exception as e:
        _cancel(row, APPLY_EXCEPTION, f"{type(e).__name__}: {e}")
        raise
    if result.get("status") == DRY_RUN:
        _cancel(row, DRY_RUN, "DRY_RUN: nothing sent to YouTube",
                **{dry_run_key: result.get(dry_run_key)})
        return DRY_RUN
    return result.get("status") or InterventionStatus.MEASURING


def _run_title(video: dict, triage: dict, decision: decide.Decision) -> str:
    """Record and apply a video triage sent to titles (Part 6 S3.3).

    Holdout -> `holdout` with `{title_before}`, no writer call. Treated -> the
    path's writer (both paths use the pipeline until S3.4) -> `planned` with
    `{title_before, title, candidates, reason, path}` and the path's
    `strategy_version` -> `titles_apply.apply_title`: `measuring`, or
    `cancelled` with `payload.error` as backlinks. No passing candidate ->
    `cancelled`, reason `checks_failed`; a writer that raises -> `cancelled`,
    reason `writer_exception`, re-raised for the tick.
    """
    channel_id = video["channel_id"]
    title_before = video.get("title") or ""
    common = dict(video_id=video["id"], channel_id=channel_id,
                  lever=InterventionLever.TITLE, origin=InterventionOrigin.MIDAS,
                  triage_json=triage)
    arm = interventions.assign_arm(video["id"], InterventionLever.TITLE)
    try:
        if arm == InterventionArm.HOLDOUT:
            row = interventions.record(**common, arm=arm, status=InterventionStatus.HOLDOUT,
                                       payload={"title_before": title_before})
        else:
            path = titles.route(channel_id, video["id"])
            base = {"title_before": title_before, "path": path}
            try:
                written = titles.pipeline(video, channel=title_channel(channel_id))
            except Exception as e:
                row = interventions.record(
                    **common, arm=arm, status=InterventionStatus.CANCELLED,
                    payload={**base, "error": {"reason": WRITER_EXCEPTION,
                                               "detail": f"{type(e).__name__}: {e}"}})
                decide.link(decision.log_id, row["id"])
                raise
            payload = {**base, "title": written.title, "candidates": written.candidates,
                       "reason": written.reason}
            if written.title is None:
                row = interventions.record(
                    **common, arm=arm, status=InterventionStatus.CANCELLED,
                    payload={**payload, "error": {"reason": CHECKS_FAILED,
                                                  "detail": "; ".join(written.failures)}})
            else:
                row = interventions.record(
                    **common, arm=arm, status=InterventionStatus.PLANNED, payload=payload,
                    strategy_version=titles.strategy_version(path))
    except interventions.ActiveInterventionExists as e:
        log.info("agent %s: %s", channel_id, e)
        return ACTIVE_INTERVENTION
    decide.link(decision.log_id, row["id"])
    log.info("agent %s: %s title %s (intervention %s, arm %s)", channel_id, video["id"],
             row["status"], row["id"], row["arm"])
    if row["status"] != InterventionStatus.PLANNED:
        return row["status"]          # holdout, or cancelled (checks_failed): no YouTube call
    return _apply(row, titles_apply.apply_title, "title")


def preview(channel_id: str, n: int) -> list[dict]:
    """What the next `n` agent ticks on the channel would do, up to the render.

    Reads only: no intervention, no decision_log row (the rules are asked
    directly; no backend call), no YouTube call. Each item has the video, the
    rules answer, the arm, the targets, the description before and after, and
    a render refusal (`refused`) instead of `after` when the block can't be
    rendered (no heading for the language yet, S1.2). A holdout's `after` is
    what it would have got.
    """
    language = _language(channel_id)

    out = []
    for picked in warm.warm_pool(channel_id)[:n]:
        video = _video(picked["id"])
        if video is None:
            continue
        # Taken as open, so the preview shows the targets before the switch is
        # on, and a missing heading as the render's refusal.
        found, context = _assess(video, language, backlinks_on=True)
        answer = decide.TRIAGE.rules(context)
        item = {"video_id": video["id"], "title": video.get("title"),
                "explore": picked.get("explore"), "answer": answer, "arm": None,
                "rationale": None, "targets": [], "before": video.get("description") or "",
                "after": None, "refused": None, "context": context}
        if answer == InterventionLever.TITLE:    # scripts/preview_titles.py shows the writer
            item["arm"] = interventions.assign_arm(video["id"], InterventionLever.TITLE)
        elif answer != InterventionLever.BACKLINKS:
            item["rationale"] = _rationale(context)
        elif refused := _unrenderable(video, _targets(found), language):
            # As run: declined before the arm is drawn.
            item.update(answer="no_change", refused=refused,
                        rationale=f"the block can't be rendered: {refused}")
        else:
            item["arm"] = interventions.assign_arm(video["id"], InterventionLever.BACKLINKS)
            item["targets"] = _targets(found)
            item["after"] = backlinks.render(video.get("description"), item["targets"], language)
        out.append(item)
    return out
