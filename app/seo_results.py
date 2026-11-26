"""The Results page's read: is Midas working, per channel and lever (#167).

`GET /seo/results?channel_id=&lever=` → one scoreboard for the channels the
signed-in user can see: per channel and lever a cell, and a fleet row over all
of them. Read-only: no write, no YouTube, no Analytics call.

A lever cell:

  - `state`: whether the lever can write on the channel, and why not
    (`channel_seo.lever_states`, the channel page's own answer). The fleet's
    counts the channels it is on for.
  - `counts`: Midas's rows by what became of them: `written` (treated rows
    that reached YouTube), `holdout`, `declined`, `cancelled` by
    `payload.error.reason`, `reverted` (`auto` / `manual`), `judged` (the rows
    in the means), `insufficient_data`, `awaiting` (still in their window,
    `ACTIVE_INTERVENTION_STATUSES`), `shorts_excluded` (judged backlinks rows
    on Shorts, `lever_verdicts._without_shorts`: `judged` + it = the table's
    judged rows), and the team's (`human`) rows, `team` / `team_judged`.
  - `n_treated`, `n_holdout`, `treated_mean_delta`, `holdout_mean_delta`,
    `lift` (treated − holdout mean): over the judged `midas` rows, every week
    so far, with their current deltas. `insufficient_data`, Shorts and team
    rows never enter a mean.
  - `cumulative_lift`, `windows_judged`, `verdict`: the latest weekly
    `lever_verdicts` row's, the numbers the stop rule read.
    `stop_rule_triggered` / `stopped_week`: whether any week fired it, and
    the first that did.
  - `weeks`: every treated-vs-holdout verdict row of the channel, oldest first.

The fleet row sums the counts and pools: its means and `lift` are over every
judged row of the visible channels (the arithmetic `lever_verdicts` uses per
channel), never an average of channel lifts; its `weeks` are pooled the same
way per judged week (`lever_verdicts.verdicts`). It has no verdict and no stop
of its own; `stopped_channels` counts the channels whose rule fired.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app import access, lever_verdicts
from app.channel_seo import lever_states
from app.config import settings
from app.db import supabase
from app.rows import all_rows
from app.status_vocab import (
    ACTIVE_INTERVENTION_STATUSES,
    ALL_INTERVENTION_LEVERS,
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
    LeverVerdictScope,
)

router = APIRouter(tags=["seo-results"])

STATIC_DIR = Path(__file__).parent / "static"

#: The levers the scoreboard has a column for, in column order.
LEVERS = (InterventionLever.BACKLINKS,)

#: When the weekly `lever_measurement` job judges (app/main.py: cron Mon 09:00 UTC).
JUDGEMENT_WEEKDAY, JUDGEMENT_HOUR = 0, 9

COLUMNS = "id,video_id,channel_id,lever,origin,arm,status,payload,applied_at,measurement_result"
VERDICT_COLUMNS = ("channel_id,lever,arm_scope,week_start,n_treated,n_holdout,"
                   "treated_mean_delta,holdout_mean_delta,lift,cumulative_lift,"
                   "windows_judged,verdict,stop_rule_triggered")
#: A weekly row as the cell carries it.
WEEK_FIELDS = ("week_start", "n_treated", "n_holdout", "treated_mean_delta",
               "holdout_mean_delta", "lift", "cumulative_lift", "windows_judged",
               "verdict", "stop_rule_triggered")
#: Counts that are numbers (the rest are {key: n}).
_COUNTS = ("written", "holdout", "declined", "judged", "insufficient_data", "awaiting",
           "shorts_excluded", "team", "team_judged")


def next_judgement(now: datetime) -> datetime:
    """The next weekly judgement after `now` (UTC)."""
    days = (JUDGEMENT_WEEKDAY - now.weekday()) % 7
    at = (now + timedelta(days=days)).replace(hour=JUDGEMENT_HOUR, minute=0, second=0,
                                              microsecond=0)
    return at if at > now else at + timedelta(days=7)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _delta(row: dict) -> float | None:
    d = (row.get("measurement_result") or {}).get("delta")
    return None if d is None else float(d)


def _means(judged: list[dict]) -> dict:
    """Treated vs holdout over judged rows (Shorts already out)."""
    by_arm = {arm: [d for r in judged if r.get("arm") == arm
                    and (d := _delta(r)) is not None]
              for arm in (InterventionArm.TREATED, InterventionArm.HOLDOUT)}
    t, h = (_mean(by_arm[InterventionArm.TREATED]), _mean(by_arm[InterventionArm.HOLDOUT]))
    return {"n_treated": len(by_arm[InterventionArm.TREATED]),
            "n_holdout": len(by_arm[InterventionArm.HOLDOUT]),
            "treated_mean_delta": t, "holdout_mean_delta": h,
            "lift": None if t is None or h is None else t - h}


def _counts(rows: list[dict], shorts: set) -> dict:
    counts = {k: 0 for k in _COUNTS}
    counts["cancelled"], counts["reverted"] = {}, {"auto": 0, "manual": 0}
    for r in rows:
        if r.get("origin") == InterventionOrigin.HUMAN:
            counts["team"] += 1
            counts["team_judged"] += r.get("status") == InterventionStatus.JUDGED
            continue
        if r.get("origin") != InterventionOrigin.MIDAS:
            continue
        status, arm, payload = r.get("status"), r.get("arm"), r.get("payload") or {}
        if arm == InterventionArm.TREATED and r.get("applied_at"):
            counts["written"] += 1
        if arm == InterventionArm.HOLDOUT:
            counts["holdout"] += 1
        if status == InterventionStatus.DECLINED:
            counts["declined"] += 1
        elif status == InterventionStatus.CANCELLED:
            if payload.get("revert"):
                auto = payload["revert"].get("auto") is True
                counts["reverted"]["auto" if auto else "manual"] += 1
            else:
                reason = (payload.get("error") or {}).get("reason") or "unknown"
                counts["cancelled"][reason] = counts["cancelled"].get(reason, 0) + 1
        elif status == InterventionStatus.JUDGED:
            counts["shorts_excluded" if r["id"] in shorts else "judged"] += 1
        elif status == InterventionStatus.INSUFFICIENT_DATA:
            counts["insufficient_data"] += 1
        elif status in ACTIVE_INTERVENTION_STATUSES:
            counts["awaiting"] += 1
    return counts


def _judged(rows: list[dict], shorts: set) -> list[dict]:
    """The rows that enter the means: judged, Midas's, a treated or holdout arm,
    not on a Short."""
    return [r for r in rows if r.get("origin") == InterventionOrigin.MIDAS
            and r.get("status") == InterventionStatus.JUDGED
            and r.get("arm") in (InterventionArm.TREATED, InterventionArm.HOLDOUT)
            and r["id"] not in shorts]


def _channel_cell(rows: list[dict], weeks: list[dict], shorts: set, state: dict) -> dict:
    latest = weeks[-1] if weeks else {}
    fired = [w for w in weeks if w.get("stop_rule_triggered")]
    return {
        "state": state,
        "counts": _counts(rows, shorts),
        **_means(_judged(rows, shorts)),
        "cumulative_lift": latest.get("cumulative_lift"),
        "windows_judged": latest.get("windows_judged") or 0,
        "verdict": latest.get("verdict"),
        "stop_rule_triggered": bool(fired),
        "stopped_week": fired[0]["week_start"] if fired else None,
        "weeks": [{k: w.get(k) for k in WEEK_FIELDS} for w in weeks],
    }


def _pooled_weeks(judged: list[dict]) -> list[dict]:
    """The fleet's weeks: per judged week, treated vs holdout over every
    visible channel's rows judged that week (and, cumulatively, up to it)."""
    weeks = sorted({w for w in map(lever_verdicts._judged_week, judged) if w is not None})
    out = []
    for week in weeks:
        v = lever_verdicts.verdicts(judged, week, {}, min_lift=settings.BACKLINK_MIN_LIFT,
                                    windows=settings.BACKLINK_EXPERIMENT_WINDOWS)
        row = v.get(LeverVerdictScope.TREATED_VS_HOLDOUT)
        if row:
            out.append({"week_start": week.isoformat(),
                        **{k: row[k] for k in ("n_treated", "n_holdout", "treated_mean_delta",
                                               "holdout_mean_delta", "lift",
                                               "cumulative_lift")}})
    return out


def _sum_counts(cells: list[dict]) -> dict:
    total = {k: 0 for k in _COUNTS}
    total["cancelled"], total["reverted"] = {}, {"auto": 0, "manual": 0}
    for c in cells:
        for k in _COUNTS:
            total[k] += c[k]
        for k, n in c["cancelled"].items():
            total["cancelled"][k] = total["cancelled"].get(k, 0) + n
        for k, n in c["reverted"].items():
            total["reverted"][k] += n
    return total


def _fleet_cell(rows: list[dict], cells: list[dict], shorts: set) -> dict:
    judged = _judged(rows, shorts)
    means = _means(judged)
    weeks = _pooled_weeks(judged)
    on = sum(1 for c in cells if c["state"]["on"])
    return {
        "state": {"on": on > 0, "reason": None if on else "off on every channel",
                  "channels_on": on, "channels": len(cells)},
        "counts": _sum_counts([c["counts"] for c in cells]),
        **means,
        "cumulative_lift": means["lift"],
        "windows_judged": len(weeks),
        "verdict": None,
        "stop_rule_triggered": None,
        "stopped_week": None,
        "stopped_channels": sum(1 for c in cells if c["stop_rule_triggered"]),
        "weeks": weeks,
    }


def _shorts(rows: list[dict]) -> set:
    """Ids of the judged rows on a Short, which no mean reads."""
    judged = [r for r in rows if r.get("status") == InterventionStatus.JUDGED]
    kept = {r["id"] for r in lever_verdicts._without_shorts(judged)}
    return {r["id"] for r in judged if r["id"] not in kept}


def _read(table: str, columns: str, lever: str, user: dict, channel_id: str | None):
    query = supabase().table(table).select(columns).eq("lever", lever)
    if channel_id:
        return all_rows(query.eq("channel_id", channel_id))
    query = access.scope_to_visible(query, user)
    return all_rows(query) if query is not None else []


@router.get("/results", dependencies=[Depends(access.current_user)])
def results_page():
    return FileResponse(STATIC_DIR / "results.html")


@router.get("/seo/results")
def seo_results(channel_id: str | None = None, lever: str | None = None,
                user: dict = Depends(access.current_user)):
    if lever is not None and lever not in ALL_INTERVENTION_LEVERS:
        raise HTTPException(400, f"unknown lever: {lever}")
    if channel_id:
        access.check_channel(user, channel_id)
    now = datetime.now(timezone.utc)

    query = access.filter_channels(
        supabase().table("channels").select("id,name,agent_enabled,default_language"), user)
    if channel_id:
        query = query.eq("id", channel_id)
    channels = sorted(all_rows(query), key=lambda c: ((c.get("name") or "").lower(), c["id"]))
    if channel_id and not channels:
        raise HTTPException(404, access.CHANNEL_NOT_FOUND)
    ids = {c["id"] for c in channels}
    states = {c["id"]: lever_states(c) for c in channels}

    out_channels = [{"id": c["id"], "name": c.get("name"), "levers": {}} for c in channels]
    fleet: dict = {"levers": {}}
    for name in LEVERS:
        if lever is not None and name != lever:
            continue
        rows = [r for r in _read("interventions", COLUMNS, name, user, channel_id)
                if r.get("channel_id") in ids] if ids else []
        verdicts = [v for v in _read("lever_verdicts", VERDICT_COLUMNS, name, user, channel_id)
                    if v.get("channel_id") in ids
                    and v.get("arm_scope") == LeverVerdictScope.TREATED_VS_HOLDOUT] if ids else []
        verdicts.sort(key=lambda v: v["week_start"])
        shorts = _shorts(rows)
        cells = []
        for entry in out_channels:
            cid = entry["id"]
            cell = _channel_cell([r for r in rows if r["channel_id"] == cid],
                                 [v for v in verdicts if v["channel_id"] == cid],
                                 shorts, states[cid][name])
            entry["levers"][name] = cell
            cells.append(cell)
        fleet["levers"][name] = _fleet_cell(rows, cells, shorts)

    return {"generated_at": now.isoformat(), "next_judgement": next_judgement(now).isoformat(),
            "channels": out_channels, "fleet": fleet}
