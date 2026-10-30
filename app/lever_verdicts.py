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

Short links (Slice 2 S2.6, `lever = 'short_link'`) are human rows only, so
`write_verdicts(lever='short_link')` writes `human` rows alone, as backlinks'
human rows: no lift, no verdict, never a stop. Before measuring, run_weekly has
app/short_links.py `detect` record the links seen in the traffic.

Titles (Slice 3 S3.5, `lever = 'title'`) are measured per video by
app/title_measurement.py. `write_verdicts(lever='title')` writes one row per
path, `pipeline_vs_holdout` and `agent_vs_holdout`, each against the one
holdout (an agent decline in the agent's mean, F14), with this arithmetic at
TITLE_MIN_LIFT; a path also stops early on the harm guard (F7), and
titles.path_stopped reads it. `auto_revert` then puts back the losing titles
(F8), and `GET /channels/{id}/title-test` reports the test.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from app import eligibility, job_status, lever_measurement, playlist_test, short_links
from app import title_measurement, titles_apply
from app.agent import loop as agent_loop
from app.apply_outcome import ApplyError, ApplyOutcome
from app.config import settings
from app.db import supabase
from app.rows import PAGE_SIZE, all_rows, rows_for_ids
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
#: A title row's `payload.path` (app/titles.py PATHS) → its path's verdict scope (S3.5).
TITLE_SCOPES = {"pipeline": LeverVerdictScope.PIPELINE_VS_HOLDOUT,
                "agent": LeverVerdictScope.AGENT_VS_HOLDOUT}
#: The job's item category for the title auto-reverts (S3.5).
REVERTS = "title reverts"


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


def _versus(this_week: dict[str, list[float]], so_far: dict[str, list[float]], arm: str,
            windows_judged: int, *, min_lift: float, windows: int) -> dict | None:
    """The verdict row's numbers for `arm`'s deltas against the holdout's, or
    None when either has no judged row this week. `this_week` and `so_far` map
    an arm to its deltas judged this week and up to it."""
    treated, held = this_week.get(arm), this_week.get(InterventionArm.HOLDOUT)
    if not (treated and held):
        return None
    lift = _mean(treated) - _mean(held)
    cumulative = _mean(so_far[arm]) - _mean(so_far[InterventionArm.HOLDOUT])
    return {
        "n_treated": len(treated), "n_holdout": len(held),
        "treated_mean_delta": _mean(treated), "holdout_mean_delta": _mean(held),
        "lift": lift, "cumulative_lift": cumulative, "windows_judged": windows_judged,
        "verdict": directional(lift, min_lift),
        "stop_rule_triggered": windows_judged >= windows and cumulative < min_lift,
    }


def _deltas(rows: list[dict], week: date, key) -> tuple[dict[str, list[float]],
                                                       dict[str, list[float]]]:
    """({group: deltas judged in `week`}, {group: deltas judged up to it}), the
    group being `key(row)` (rows keyed None are left out)."""
    this_week: dict[str, list[float]] = {}
    so_far: dict[str, list[float]] = {}
    for row in rows:
        judged, group = _judged_week(row), key(row)
        if judged is None or group is None or judged > week:
            continue
        delta = float(row["measurement_result"]["delta"])
        so_far.setdefault(group, []).append(delta)
        if judged == week:
            this_week.setdefault(group, []).append(delta)
    return this_week, so_far


def verdicts(rows: list[dict], week: date, windows_before: dict[str, int], *,
             min_lift: float, windows: int) -> dict[str, dict]:
    """{arm_scope: the verdict row's numbers} for `week`, from judged rows.

    `rows` are the channel's judged rows of one lever; those judged after
    `week` are ignored. `windows_before` counts each scope's verdict weeks
    before this one. A scope with nothing to report this week is absent.
    `min_lift` and `windows` are the lever's verdict band and time box
    (BACKLINK_MIN_LIFT, BACKLINK_EXPERIMENT_WINDOWS for backlinks).
    """
    this_week, so_far = _deltas(rows, week, _scope)
    out: dict[str, dict] = {}
    versus = _versus(this_week, so_far, InterventionArm.TREATED,
                     windows_before.get(LeverVerdictScope.TREATED_VS_HOLDOUT, 0) + 1,
                     min_lift=min_lift, windows=windows)
    if versus:
        out[LeverVerdictScope.TREATED_VS_HOLDOUT] = versus
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


def _title_arm(row: dict) -> str | None:
    """Which mean a judged title row enters: the holdout, or its path's
    (`payload.path`; an agent decline is in the agent's, F14)."""
    if row.get("arm") == InterventionArm.HOLDOUT:
        return InterventionArm.HOLDOUT
    if row.get("arm") == InterventionArm.TREATED:
        path = (row.get("payload") or {}).get("path")
        return path if path in TITLE_SCOPES else None
    return None


def title_verdicts(rows: list[dict], week: date,
                   windows_before: dict[str, int]) -> dict[str, dict]:
    """{arm_scope: the verdict row's numbers} for `week`, one per path against
    the shared holdout (Part 6 S3.5, F7): the backlinks arithmetic at
    ±TITLE_MIN_LIFT, stopped at TITLE_EXPERIMENT_WINDOWS with a cumulative
    lift under it, or early, at TITLE_HARM_WINDOWS with a cumulative lift at
    or under −TITLE_HARM_LIFT."""
    this_week, so_far = _deltas(rows, week, _title_arm)
    out: dict[str, dict] = {}
    for path, scope in TITLE_SCOPES.items():
        versus = _versus(this_week, so_far, path, windows_before.get(scope, 0) + 1,
                         min_lift=settings.TITLE_MIN_LIFT,
                         windows=settings.TITLE_EXPERIMENT_WINDOWS)
        if versus:
            versus["stop_rule_triggered"] = versus["stop_rule_triggered"] or (
                versus["windows_judged"] >= settings.TITLE_HARM_WINDOWS
                and versus["cumulative_lift"] <= -settings.TITLE_HARM_LIFT)
            out[scope] = versus
    return out


def _title_judged(channel_id: str) -> list[dict]:
    """The channel's judged `midas` title rows, and those put back after they
    were judged (`cancelled` with their numbers, pre at the floor or over):
    a reverted title stays in its path's mean, as the decision it was."""
    rows = all_rows(
        supabase().table("interventions")
        .select("id,video_id,channel_id,lever,origin,arm,status,payload,applied_at,"
                "before_state,measurement_result")
        .eq("channel_id", channel_id).eq("lever", InterventionLever.TITLE)
        .eq("origin", InterventionOrigin.MIDAS)
        .in_("status", [InterventionStatus.JUDGED, InterventionStatus.CANCELLED])
    )
    return [r for r in rows if r["status"] == InterventionStatus.JUDGED
            or ((r.get("measurement_result") or {}).get("pre", -1)
                >= settings.TITLE_MIN_PRE_VIEWS)]


def _without_shorts(rows: list[dict]) -> list[dict]:
    """The rows whose video isn't a Short (`is_short` true; NULL stays in).

    Before 2026-10-26 (#103) the agent's pick took Shorts, where description
    links aren't clickable, so their backlinks rows (either arm, or the team's)
    would only pull the means toward zero. The arm is a hash of the video id,
    so dropping them from both arms keeps the comparison fair. They stay
    measured; only the verdicts leave them out."""
    shorts = {v["id"] for v in rows_for_ids(
        lambda chunk: supabase().table("videos").select("id,is_short")
        .in_("id", chunk).eq("is_short", True),
        sorted({r["video_id"] for r in rows if r.get("video_id")}),
    )}
    return [r for r in rows if r.get("video_id") not in shorts]


def write_verdicts(channel_id: str, *, today: date | None = None,
                   lever: str = InterventionLever.BACKLINKS) -> dict[str, dict]:
    """Write the week's verdict rows of the lever (backlinks, the human-only
    short_link, or title's two paths) for the channel; returns the current
    week's by scope.

    Also writes an earlier week that has judged rows and no verdict row of any
    scope yet. A scope with no row this week has any row a same-week earlier
    run wrote for it deleted (its judged rows moved on, e.g. a restatement made
    one `insufficient_data`), unless that row triggered the stop rule.
    """
    today = today or datetime.now(timezone.utc).date()
    current = week_start(today)
    if lever == InterventionLever.TITLE:
        judged = _title_judged(channel_id)
        scopes = tuple(TITLE_SCOPES.values())
    else:
        judged = all_rows(
            supabase().table("interventions")
            .select("id,video_id,origin,arm,status,measurement_result")
            .eq("channel_id", channel_id).eq("lever", lever)
            .eq("status", InterventionStatus.JUDGED)
        )
        scopes = (LeverVerdictScope.TREATED_VS_HOLDOUT, LeverVerdictScope.HUMAN)
    if lever == InterventionLever.BACKLINKS:
        judged = _without_shorts(judged)
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
        out = (title_verdicts(judged, week, windows_before) if lever == InterventionLever.TITLE
               else verdicts(judged, week, windows_before, min_lift=settings.BACKLINK_MIN_LIFT,
                             windows=settings.BACKLINK_EXPERIMENT_WINDOWS))
        for scope in scopes:
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


def stopped(channel_id: str, lever: str = InterventionLever.BACKLINKS,
            scope: str = LeverVerdictScope.TREATED_VS_HOLDOUT) -> bool:
    """Whether the lever has stopped for the channel (the P1 stop rule): any of
    its weekly verdicts of `scope` (treated vs holdout; a title path's,
    app/titles.py path_stopped) has `stop_rule_triggered`."""
    rows = (
        supabase().table("lever_verdicts").select("id")
        .eq("channel_id", channel_id).eq("lever", lever)
        .eq("arm_scope", scope)
        .eq("stop_rule_triggered", True).limit(1).execute()
    ).data or []
    return bool(rows)


def auto_revert(channel_id: str) -> dict:
    """Put back the channel's losing titles (Part 6 S3.5, F8).

    A judged treated row that reached YouTube (not a decline) whose `delta`
    minus the holdout mean Δ of its judged week (else the channel's cumulative
    holdout mean; none yet → it waits) is ≤ −TITLE_REVERT_LIFT goes to
    `titles_apply.revert_title(auto=True)`, worst first, at most
    TITLE_REVERTS_PER_DAY a run. A live title someone else changed is left
    alone (`title_changed`), and the kill switch or a short ledger stops the
    run; both are retried next run. The row keeps its judged numbers.

    Returns counts: `attempted`, `errored` (for job_status.item_error_verdict,
    under REVERTS), `reverted`, `skipped`.
    """
    rows = _title_judged(channel_id)
    holdout = [r for r in rows if r.get("arm") == InterventionArm.HOLDOUT]
    cumulative = _mean([float(r["measurement_result"]["delta"]) for r in holdout])
    by_week: dict[date, list[float]] = {}
    for r in holdout:
        by_week.setdefault(_judged_week(r), []).append(float(r["measurement_result"]["delta"]))

    gaps = []
    for r in rows:
        if (r["status"] != InterventionStatus.JUDGED or r.get("arm") != InterventionArm.TREATED
                or not r.get("applied_at")):
            continue
        held = _mean(by_week[_judged_week(r)]) if _judged_week(r) in by_week else cumulative
        if held is None:
            continue
        gap = float(r["measurement_result"]["delta"]) - held
        if gap <= -settings.TITLE_REVERT_LIFT:
            gaps.append((gap, r["id"], r))

    counts = dict.fromkeys(("attempted", "errored", "reverted", "skipped"), 0)
    for gap, _, row in sorted(gaps, key=lambda g: (g[0], g[1])):
        if counts["reverted"] >= settings.TITLE_REVERTS_PER_DAY:
            break
        counts["attempted"] += 1
        try:
            titles_apply.revert_title(row, auto=True)
        except ApplyError as e:
            if e.outcome in (ApplyOutcome.APPLY_DISABLED, ApplyOutcome.QUOTA_INSUFFICIENT):
                counts["skipped"] += 1
                log.info("title auto-revert %s: stopped for this run (%s); intervention %s "
                         "waits", channel_id, e.detail, row["id"])
                break
            counts["errored"] += 1
            log.warning("title auto-revert %s: intervention %s failed: %s",
                        channel_id, row["id"], e.detail)
            continue
        except HTTPException as e:
            if e.detail != titles_apply.TITLE_CHANGED:
                counts["errored"] += 1
                log.warning("title auto-revert %s: intervention %s failed: %s",
                            channel_id, row["id"], e.detail)
                continue
            counts["skipped"] += 1
            log.info("title auto-revert %s: intervention %s skipped: the live title isn't "
                     "Midas's", channel_id, row["id"])
            continue
        except Exception as e:
            counts["errored"] += 1
            log.warning("title auto-revert %s: intervention %s failed: %s",
                        channel_id, row["id"], e)
            continue
        counts["reverted"] += 1
        log.info("title auto-revert %s: intervention %s put back (delta − holdout %.3f)",
                 channel_id, row["id"], gap)
    return counts


def _has_titles(channel_id: str) -> bool:
    """Whether the channel has any `midas` title row (else the title half is skipped)."""
    return bool((
        supabase().table("interventions").select("id")
        .eq("channel_id", channel_id).eq("lever", InterventionLever.TITLE)
        .eq("origin", InterventionOrigin.MIDAS).limit(1).execute()
    ).data)


def run_weekly(*, today: date | None = None) -> dict | None:
    """APScheduler entry point (`lever_measurement`). Per channel: S1.6a's
    measurement, then this week's verdicts; then, for a channel with
    `playlist_arms` rows, the playlist test's measurement and verdicts
    (playlist_test.measure_channel, S2.3), errors under `playlist arms`. On a
    channel in TRAFFIC_INGEST_CHANNELS, first the Short links seen in its
    traffic (short_links.detect, S2.6), errors under `short-link pairs`, and
    after backlinks' verdicts the week's `short_link` ones. On a channel with
    title rows, their measurement (app/title_measurement.py, errors under
    `title interventions`), the week's verdicts per path, then the auto-revert
    (errors under `title reverts`; S3.5).

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

    # The channels whose playlist test is drawn. A failed read (e.g. before
    # 20261027000000 is applied) skips the playlist test this run, never
    # backlinks: the next run recomputes every week anyway.
    try:
        drawn = {r["channel_id"] for r in all_rows(
            supabase().table("playlist_arms").select("id,channel_id"))}
    except Exception as e:
        log.error("lever_measurement: playlist_arms unreadable; playlist test skipped: %s", e)
        drawn = set()
    for cid in eligibility.channel_ids_for(eligibility.Job.EVERY):
        ingested = cid in settings.TRAFFIC_INGEST_CHANNELS
        if ingested:
            # Short links seen in the traffic (S2.6), so they're measured below.
            # Its own category: a failure here doesn't stop the measurement.
            try:
                counts = short_links.detect(cid)
                failure, partial = job_status.item_error_verdict(
                    {short_links.PAIRS: (counts["errored"], counts["attempted"])})
                if failure:
                    log.error("lever_measurement %s: every Short-link pair failed: %s", cid, failure)
                    note(crashed, cid, f"ItemsFailed: {failure}")
                elif partial:
                    note(partial_errors, cid, partial)
            except Exception as e:
                log.exception("lever_measurement %s: Short-link detection crashed: %s", cid, e)
                note(crashed, cid, job_status.describe(e))
        try:
            counts = lever_measurement.measure_channel(cid, today=today)
            failure, partial = job_status.item_error_verdict(
                {"interventions": (counts["errored"], counts["attempted"])})
            if failure:
                log.error("lever_measurement %s: every intervention failed: %s", cid, failure)
                note(crashed, cid, f"ItemsFailed: {failure}")
            else:
                write_verdicts(cid, today=today)
                if ingested:
                    write_verdicts(cid, today=today, lever=InterventionLever.SHORT_LINK)
                if partial:
                    note(partial_errors, cid, partial)
        except Exception as e:
            log.exception("lever_measurement %s crashed: %s", cid, e)
            note(crashed, cid, job_status.describe(e))
        # Titles (S3.5), their own categories: a failure here doesn't stop the
        # channel's backlinks above, nor theirs this.
        try:
            if _has_titles(cid):
                counts = title_measurement.measure_channel(cid, today=today)
                failure, partial = job_status.item_error_verdict(
                    {title_measurement.ROWS: (counts["errored"], counts["attempted"])})
                if failure:
                    log.error("lever_measurement %s: every title row failed: %s", cid, failure)
                    note(crashed, cid, f"ItemsFailed: {failure}")
                else:
                    write_verdicts(cid, today=today, lever=InterventionLever.TITLE)
                    if partial:
                        note(partial_errors, cid, partial)
                    counts = auto_revert(cid)
                    failure, partial = job_status.item_error_verdict(
                        {REVERTS: (counts["errored"], counts["attempted"])})
                    if failure:
                        log.error("lever_measurement %s: every title revert failed: %s",
                                  cid, failure)
                        note(crashed, cid, f"ItemsFailed: {failure}")
                    elif partial:
                        note(partial_errors, cid, partial)
        except Exception as e:
            log.exception("lever_measurement %s: titles crashed: %s", cid, e)
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


def _counted(row: dict) -> bool:
    """Whether a title row enters its path's mean (as `_title_judged` keeps it)."""
    return (row["status"] == InterventionStatus.JUDGED
            or (row["status"] == InterventionStatus.CANCELLED
                and (row.get("measurement_result") or {}).get("pre", -1)
                >= settings.TITLE_MIN_PRE_VIEWS))


def _trace(rows: list[dict]) -> dict:
    """The §3.5 (a) check over the agent's runs (Part 6 S3.5): how many runs
    called a set of tools other than the most common one, and how many called
    each tool. Reported, not judged."""
    runs = [frozenset(agent_loop.tools_called(r["trajectory"])) for r in rows if r.get("trajectory")]
    if not runs:
        return {"runs": 0, "most_common": None, "share_differing": None, "share_calling": {}}
    sets: dict[frozenset, int] = {}
    for tools in runs:
        sets[tools] = sets.get(tools, 0) + 1
    common = max(sets, key=lambda t: (sets[t], sorted(t)))
    names = sorted(set().union(*runs))
    return {"runs": len(runs), "most_common": sorted(common),
            "share_differing": (len(runs) - sets[common]) / len(runs),
            "share_calling": {n: sum(n in t for t in runs) / len(runs) for n in names}}


@router.get("/channels/{channel_id}/title-test")
def channel_title_test(channel_id: str):
    """The title test on the channel (Part 6 S3.5), read-only: per path its
    treated, declined, cancelled (by reason; `reverted` for a title put back),
    judged and insufficient rows, mean Δ, cumulative lift against the holdout,
    auto-reverts and whether it has stopped; the holdout's n and mean Δ; and
    the agent's trace numbers."""
    rows = all_rows(
        supabase().table("interventions")
        .select("id,arm,status,payload,applied_at,measurement_result,trajectory")
        .eq("channel_id", channel_id).eq("lever", InterventionLever.TITLE)
        .eq("origin", InterventionOrigin.MIDAS)
    )

    def deltas(group: list[dict]) -> list[float]:
        return [float(r["measurement_result"]["delta"]) for r in group if _counted(r)]

    holdout = [r for r in rows if r.get("arm") == InterventionArm.HOLDOUT]
    holdout_mean = _mean(deltas(holdout))
    paths = {}
    for path, scope in TITLE_SCOPES.items():
        mine = [r for r in rows if r.get("arm") == InterventionArm.TREATED
                and (r.get("payload") or {}).get("path") == path]
        cancelled: dict[str, int] = {}
        for r in mine:
            if r["status"] == InterventionStatus.CANCELLED:
                payload = r.get("payload") or {}
                reason = ("reverted" if payload.get("revert")
                          else (payload.get("error") or {}).get("reason") or "unknown")
                cancelled[reason] = cancelled.get(reason, 0) + 1
        mean = _mean(deltas(mine))
        paths[path] = {
            "treated": sum(bool(r.get("applied_at")) for r in mine),
            "declined": sum(not r.get("applied_at") and r["status"] not in (
                InterventionStatus.CANCELLED, InterventionStatus.PLANNED) for r in mine),
            "cancelled": cancelled,
            "judged": sum(_counted(r) for r in mine),
            "insufficient": sum(r["status"] == InterventionStatus.INSUFFICIENT_DATA for r in mine),
            "mean_delta": mean,
            "cumulative_lift": (mean - holdout_mean if mean is not None
                                and holdout_mean is not None else None),
            "auto_reverts": sum(((r.get("payload") or {}).get("revert") or {}).get("auto") is True
                                for r in mine),
            "stopped": stopped(channel_id, InterventionLever.TITLE, scope),
        }
    agent = [r for r in rows if (r.get("payload") or {}).get("path") == "agent"]
    return {"paths": paths,
            "holdout": {"n": len(holdout), "judged": len(deltas(holdout)),
                        "mean_delta": holdout_mean},
            "trace": _trace(agent)}
