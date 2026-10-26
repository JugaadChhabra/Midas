"""Slice 1 · S1.6b — the weekly lever verdict, the P1 stop rule, the human
benchmark and their read endpoints (spec Part 4 S1.6, Part 2 §1.3–§1.5; #68).

S1.6a (app/lever_measurement.py) judges each backlinks intervention's pair
views, `delta` in views per week. Once a week, per channel, this turns the rows
judged that week into one `lever_verdicts` row per comparison:

  - `treated_vs_holdout`: `lift` = the treated arm's mean delta − the holdout
    arm's, over the `midas` rows judged that week; `cumulative_lift` the same
    over every row judged so far. `verdict` is directional against
    BACKLINK_MIN_LIFT (D6): `helped` at lift ≥ it, `worse` at lift ≤ −it,
    else `no_change`. A week without a judged row in each arm writes none.
  - `human`: the team's backlinks judged that week, on their own (§1.4): their
    count and mean delta, never a lift, a verdict or a stop.

`week_start` is the Monday (UTC) of the week a row was judged in
(`measurement_result.judged_at`, which S1.6a keeps across recomputes). Each run
writes the current week and any earlier week that has judged rows but no
verdict row yet (a run that measured, then died before its verdicts), oldest
first. A week's row, once written, is never rewritten after its week: a rerun
in the same week replaces that week's row only. A recompute after a restatement
still reaches the verdicts, through the cumulative lift, which reads every
judged row's current delta.

Stop rule (P1): once `windows_judged` (the channel's treated-vs-holdout weeks so
far, this one included) reaches BACKLINK_EXPERIMENT_WINDOWS and the cumulative
lift is under BACKLINK_MIN_LIFT, the row is `stop_rule_triggered`, and from then
on triage answers `no_change` for the channel (agent_tick.backlinks_stopped).
Blocks already applied stay (D8). It doesn't undo itself: a later week's row
doesn't clear an earlier one's flag, and a same-week rerun keeps a flag already
set.

    run_weekly()               -- the `lever_measurement` job: measure, then verdicts
    write_verdicts(channel_id) -- the week's rows (and any missed week's) for one channel
    stopped(channel_id)        -- the stop state triage reads

The playlist test's verdicts (Slice 2 S2.3, `lever = 'playlist'`) are written
by app/playlist_test.py `measure_channel`, which run_weekly also calls, with
`directional` and this table's key.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from app import eligibility, job_status, lever_measurement, playlist_test
from app.config import settings
from app.db import supabase
from app.rows import PAGE_SIZE, all_rows
from app.status_vocab import (
    ALL_INTERVENTION_LEVERS,
    ALL_INTERVENTION_STATUSES,
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
    LeverVerdict,
    LeverVerdictScope,
)

log = logging.getLogger("midas.lever_verdicts")

router = APIRouter(tags=["interventions"])

#: The table's unique key, which every verdict writer upserts on (playlist_test too).
ON_CONFLICT = "channel_id,lever,arm_scope,week_start"


def week_start(day: date) -> date:
    """The Monday of `day`'s week."""
    return day - timedelta(days=day.weekday())


def _judged_week(row: dict) -> date | None:
    judged_at = (row.get("measurement_result") or {}).get("judged_at")
    if not judged_at:
        return None
    ts = datetime.fromisoformat(str(judged_at).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return week_start(ts.astimezone(timezone.utc).date())


def _scope(row: dict) -> str | None:
    """Which mean a judged row enters: treated, holdout or human (or none)."""
    if row.get("origin") == InterventionOrigin.HUMAN:
        return LeverVerdictScope.HUMAN
    if row.get("arm") in (InterventionArm.TREATED, InterventionArm.HOLDOUT):
        return row["arm"]
    return None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def directional(lift: float, min_lift: float) -> str:
    """helped / no_change / worse against the lever's `min_lift` (§1.5;
    BACKLINK_MIN_LIFT, D6, or PLAYLIST_MIN_LIFT, E8)."""
    if lift >= min_lift:
        return LeverVerdict.HELPED
    if lift <= -min_lift:
        return LeverVerdict.WORSE
    return LeverVerdict.NO_CHANGE


def verdicts(rows: list[dict], week: date, windows_before: dict[str, int], *,
             min_lift: float, windows: int) -> dict[str, dict]:
    """{arm_scope: the verdict row's numbers} for `week`, from judged rows.

    `rows` are the channel's judged rows of one lever; those judged after
    `week` are ignored. `windows_before` counts each scope's verdict weeks
    before this one. A scope with nothing to report this week is absent.
    `min_lift` and `windows` are the lever's verdict band and time box
    (BACKLINK_MIN_LIFT, BACKLINK_EXPERIMENT_WINDOWS for backlinks).
    """
    this_week: dict[str, list[float]] = {}
    so_far: dict[str, list[float]] = {}
    for row in rows:
        judged, scope = _judged_week(row), _scope(row)
        if judged is None or scope is None or judged > week:
            continue
        delta = float(row["measurement_result"]["delta"])
        so_far.setdefault(scope, []).append(delta)
        if judged == week:
            this_week.setdefault(scope, []).append(delta)

    out: dict[str, dict] = {}
    treated, held = this_week.get(InterventionArm.TREATED), this_week.get(InterventionArm.HOLDOUT)
    if treated and held:
        lift = _mean(treated) - _mean(held)
        cumulative = (_mean(so_far[InterventionArm.TREATED])
                      - _mean(so_far[InterventionArm.HOLDOUT]))
        judged_ = windows_before.get(LeverVerdictScope.TREATED_VS_HOLDOUT, 0) + 1
        out[LeverVerdictScope.TREATED_VS_HOLDOUT] = {
            "n_treated": len(treated), "n_holdout": len(held),
            "treated_mean_delta": _mean(treated), "holdout_mean_delta": _mean(held),
            "lift": lift, "cumulative_lift": cumulative, "windows_judged": judged_,
            "verdict": directional(lift, min_lift),
            "stop_rule_triggered": judged_ >= windows and cumulative < min_lift,
        }
    human = this_week.get(LeverVerdictScope.HUMAN)
    if human:
        out[LeverVerdictScope.HUMAN] = {
            "n_treated": len(human), "n_holdout": 0,
            "treated_mean_delta": _mean(human), "holdout_mean_delta": None,
            "lift": None, "cumulative_lift": None,
            "windows_judged": windows_before.get(LeverVerdictScope.HUMAN, 0) + 1,
            "verdict": None, "stop_rule_triggered": False,
        }
    return out


def write_verdicts(channel_id: str, *, today: date | None = None) -> dict[str, dict]:
    """Write the week's verdict rows for the channel; returns the current week's
    by scope.

    Also writes an earlier week that has judged rows and no verdict row of any
    scope yet. A scope with no row this week has any row a same-week earlier
    run wrote for it deleted (its judged rows moved on, e.g. a restatement made
    one `insufficient_data`), unless that row triggered the stop rule.
    """
    today = today or datetime.now(timezone.utc).date()
    current = week_start(today)
    lever = InterventionLever.BACKLINKS
    judged = all_rows(
        supabase().table("interventions")
        .select("id,origin,arm,status,measurement_result")
        .eq("channel_id", channel_id).eq("lever", lever)
        .eq("status", InterventionStatus.JUDGED)
    )
    stored = all_rows(
        supabase().table("lever_verdicts").select("id,arm_scope,week_start,stop_rule_triggered")
        .eq("channel_id", channel_id).eq("lever", lever)
        .lte("week_start", current.isoformat())
    )
    written = {v["week_start"] for v in stored if v["week_start"] < current.isoformat()}
    missed = sorted({w for w in map(_judged_week, judged)
                     if w is not None and w < current and w.isoformat() not in written})

    now = datetime.now(timezone.utc).isoformat()
    out: dict[str, dict] = {}
    for week in missed + [current]:
        windows_before: dict[str, int] = {}
        for v in stored:
            if v["week_start"] < week.isoformat():
                windows_before[v["arm_scope"]] = windows_before.get(v["arm_scope"], 0) + 1
        this_week = {v["arm_scope"]: v for v in stored if v["week_start"] == week.isoformat()}
        out = verdicts(judged, week, windows_before, min_lift=settings.BACKLINK_MIN_LIFT,
                       windows=settings.BACKLINK_EXPERIMENT_WINDOWS)
        for scope in (LeverVerdictScope.TREATED_VS_HOLDOUT, LeverVerdictScope.HUMAN):
            key = {"channel_id": channel_id, "lever": lever, "arm_scope": scope,
                   "week_start": week.isoformat()}
            held = (this_week.get(scope) or {}).get("stop_rule_triggered") is True
            if scope in out:
                row = {**key, **out[scope], "computed_at": now}
                row["stop_rule_triggered"] = row["stop_rule_triggered"] or held
                supabase().table("lever_verdicts").upsert(row, on_conflict=ON_CONFLICT).execute()
                stored = [v for v in stored if not (v["arm_scope"] == scope
                                                    and v["week_start"] == key["week_start"])]
                stored.append(row)
            elif scope in this_week and not held:
                q = supabase().table("lever_verdicts").delete()
                for column, value in key.items():
                    q = q.eq(column, value)
                q.execute()
                stored = [v for v in stored if v is not this_week[scope]]
        log.info("lever_verdicts %s week %s: %s", channel_id, week, out or "no verdict")
    return out


def stopped(channel_id: str, lever: str = InterventionLever.BACKLINKS) -> bool:
    """Whether the lever has stopped for the channel (the P1 stop rule): any of
    its treated-vs-holdout weekly verdicts has `stop_rule_triggered`."""
    rows = (
        supabase().table("lever_verdicts").select("id")
        .eq("channel_id", channel_id).eq("lever", lever)
        .eq("arm_scope", LeverVerdictScope.TREATED_VS_HOLDOUT)
        .eq("stop_rule_triggered", True).limit(1).execute()
    ).data or []
    return bool(rows)


def run_weekly(*, today: date | None = None) -> dict | None:
    """APScheduler entry point (`lever_measurement`). Per channel: S1.6a's
    measurement, then this week's verdicts; then, for a channel with
    `playlist_arms` rows, the playlist test's measurement and verdicts
    (playlist_test.measure_channel, S2.3), errors under `playlist arms`.

    traffic_poll's failure model: a channel that raises fails the run once
    every channel has run; per-row errors are judged by
    job_status.item_error_verdict (every row errored fails the channel, some
    is `degraded`). A channel whose every row errored gets no verdicts this
    run: the next run writes the week it missed.
    """
    crashed: dict[str, str] = {}
    partial_errors: dict[str, str] = {}

    def note(into: dict[str, str], cid: str, message: str) -> None:
        into[cid] = "; ".join(filter(None, [into.get(cid), message]))

    # The channels whose playlist test is drawn.
    drawn = {r["channel_id"] for r in all_rows(
        supabase().table("playlist_arms").select("id,channel_id"))}
    for cid in eligibility.channel_ids_for(eligibility.Job.EVERY):
        try:
            counts = lever_measurement.measure_channel(cid, today=today)
            failure, partial = job_status.item_error_verdict(
                {"interventions": (counts["errored"], counts["attempted"])})
            if failure:
                log.error("lever_measurement %s: every intervention failed: %s", cid, failure)
                note(crashed, cid, f"ItemsFailed: {failure}")
            else:
                write_verdicts(cid, today=today)
                if partial:
                    note(partial_errors, cid, partial)
        except Exception as e:
            log.exception("lever_measurement %s crashed: %s", cid, e)
            note(crashed, cid, job_status.describe(e))
        if cid not in drawn:
            continue
        # The playlist test (S2.3), its own category: a failure here doesn't
        # stop the channel's backlinks above, nor theirs this.
        try:
            counts = playlist_test.measure_channel(cid)
            failure, partial = job_status.item_error_verdict(
                {playlist_test.ARMS: (counts["errored"], counts["attempted"])})
            if failure:
                log.error("lever_measurement %s: every playlist arm failed: %s", cid, failure)
                note(crashed, cid, f"ItemsFailed: {failure}")
            elif partial:
                note(partial_errors, cid, partial)
        except Exception as e:
            log.exception("lever_measurement %s: playlist test crashed: %s", cid, e)
            note(crashed, cid, job_status.describe(e))
    if crashed:
        raise job_status.JobRunFailed("lever_measurement", crashed)
    return {"partial_errors": partial_errors} if partial_errors else None


@router.get("/channels/{channel_id}/interventions")
def channel_interventions(
    channel_id: str,
    lever: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
):
    """The channel's interventions, newest first, one page at a time.

    `next_offset` is the next page's `offset` whenever this page came back
    full, else None. A last page that is exactly full therefore points at one
    more, empty page (fetching limit + 1 rows would hit PostgREST's own cap at
    limit = PAGE_SIZE). One page is at most PAGE_SIZE rows (app/rows.py).
    """
    if lever is not None and lever not in ALL_INTERVENTION_LEVERS:
        raise HTTPException(400, f"unknown lever {lever!r}")
    if status is not None and status not in ALL_INTERVENTION_STATUSES:
        raise HTTPException(400, f"unknown status {status!r}")
    q = supabase().table("interventions").select("*").eq("channel_id", channel_id)
    if lever is not None:
        q = q.eq("lever", lever)
    if status is not None:
        q = q.eq("status", status)
    # One bounded page for the caller, not a read-everything loop (that's
    # all_rows). `id` breaks created_at ties, so the pages are a total order
    # (app/rows.py ORDER_KEY).
    last = offset + limit - 1
    rows = (q.order("created_at", desc=True).order("id", desc=True)
            .range(offset, last).execute()).data or []
    return {"interventions": rows, "limit": limit, "offset": offset,
            "next_offset": offset + limit if len(rows) == limit else None}


@router.get("/channels/{channel_id}/lever-verdicts")
def channel_lever_verdicts(channel_id: str):
    """Every weekly verdict row of the channel, newest week first, and whether
    the backlinks lever is stopped there."""
    rows = all_rows(
        supabase().table("lever_verdicts").select("*")
        .eq("channel_id", channel_id).order("week_start", desc=True)
    )
    return {"verdicts": rows, "backlinks_stopped": stopped(channel_id)}
