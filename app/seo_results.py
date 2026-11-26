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

The title cell (#170) has the same fields, plus `paths: {pipeline, agent}` and
`first_verdict`. A path's figures are `lever_verdicts.title_paths`' own (the
channel's title-test endpoint reads through the same function) with the cell
fields added: each path against the shared holdout, declines in the agent's
mean, a title put back after it was judged still in its path's. The cell's
means pool both paths; its verdict, weeks and `cumulative_lift` are the lead
path's (the one with more titles written); `stop_rule_triggered` is true when
either path's fired. `counts.declined` / `judged` follow the title-test
summary (a measured decline is judged *and* a decline). `first_verdict` is the
earliest day a title row still in its window can be judged: d0
(`title_measurement.as_of`) + `TITLE_WINDOW_DAYS` + `TRAFFIC_LAG_DAYS`; the
response's `first_title_verdicts` is the earliest over the visible channels.

The playlist cell (#171) is `playlist_test.playlist_test_summary`'s figures
(the channel's `/playlist-test` reads the same function): `answer`, dates, `arms`
by status, the weekly rows and the latest's lift and stop. The Short-link cell is
the team's work, not Midas's (`by: "team"`, no lift): recommendations by status,
those `seen` in type-32 traffic, the team's `short_link` interventions and the
latest `human` verdict row. Their fleet cells sum counts only; playlist answers
are listed per channel (`answers`), never pooled.

The title and backlinks cells, and their fleet cells, carry `early` (#172): the
early read of the rows still inside their window, from the post data-days
already ingested (`app/early_read.py`; titles also impressions and CTR). It is
computed per request, never written, and nothing that judges or stops a lever
reads it; None while no open row has a post day. The fleet's pools every
visible row.

The fleet row sums the counts and pools: its means and `lift` are over every
judged row of the visible channels (the arithmetic `lever_verdicts` uses per
channel), never an average of channel lifts; its `weeks` are pooled the same
way per judged week (`lever_verdicts.verdicts`). It has no verdict and no stop
of its own; `stopped_channels` counts the channels whose rule fired.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app import access, early_read, lever_verdicts, playlist_test, reach, title_measurement
from app.channel_seo import lever_states, trim
from app.config import settings
from app.db import supabase
from app.rows import all_rows, rows_for_ids
from app.status_vocab import (
    ACTIVE_INTERVENTION_STATUSES,
    ALL_INTERVENTION_LEVERS,
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
    LeverVerdictScope,
    ShortLinkStatus,
)

router = APIRouter(tags=["seo-results"])

STATIC_DIR = Path(__file__).parent / "static"

#: The levers the scoreboard has a column for, in column order.
LEVERS = (InterventionLever.BACKLINKS, InterventionLever.TITLE, InterventionLever.PLAYLIST,
          InterventionLever.SHORT_LINK)

#: The verdict scopes whose weekly rows a lever's cell reads: backlinks' one,
#: and a title path's each (S3.5, `lever_verdicts.TITLE_SCOPES`).
SCOPES = {InterventionLever.BACKLINKS: (LeverVerdictScope.TREATED_VS_HOLDOUT,),
          InterventionLever.TITLE: tuple(lever_verdicts.TITLE_SCOPES.values())}

#: Days after a data-day before the traffic report has it (the steady lag,
#: docs/PHASE_A_FINDINGS.md A1.1; `channel_health` flags a frontier past 4).
TRAFFIC_LAG_DAYS = 2

#: When the weekly `lever_measurement` job judges (app/main.py: cron Mon 09:00 UTC).
JUDGEMENT_WEEKDAY, JUDGEMENT_HOUR = 0, 9

COLUMNS = ("id,video_id,channel_id,lever,origin,arm,status,payload,applied_at,created_at,"
           "measurement_status,measurement_result")
VERDICT_COLUMNS = ("channel_id,lever,arm_scope,week_start,n_treated,n_holdout,"
                   "treated_mean_delta,holdout_mean_delta,lift,cumulative_lift,"
                   "windows_judged,verdict,stop_rule_triggered")
REC_COLUMNS = "id,channel_id,status,seen_at"
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


def _pooled_weeks(judged: list[dict], scope: str = LeverVerdictScope.TREATED_VS_HOLDOUT
                  ) -> list[dict]:
    """The fleet's weeks: per judged week, treated vs holdout over every
    visible channel's rows judged that week (and, cumulatively, up to it). A
    title path's scope pools that path's rows against the shared holdout."""
    weeks = sorted({w for w in map(lever_verdicts._judged_week, judged) if w is not None})
    out = []
    for week in weeks:
        if scope == LeverVerdictScope.TREATED_VS_HOLDOUT:
            v = lever_verdicts.verdicts(judged, week, {}, min_lift=settings.BACKLINK_MIN_LIFT,
                                        windows=settings.BACKLINK_EXPERIMENT_WINDOWS)
        else:
            v = lever_verdicts.title_verdicts(judged, week, {})
        row = v.get(scope)
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


def _title_judged(rows: list[dict]) -> list[dict]:
    """The rows that enter a title mean: `midas`, the holdout or a known path's,
    judged or put back after they were (`lever_verdicts._counted`). Titles are
    never on a Short, so nothing is left out for that."""
    return [r for r in rows if r.get("origin") == InterventionOrigin.MIDAS
            and lever_verdicts._counted(r) and lever_verdicts._title_arm(r) is not None]


def _first_verdict(rows: list[dict]) -> str | None:
    """The earliest day a title row still in its window can be judged: d0 (the
    measurement's own rule), the post window, then the traffic report's lag."""
    days = [d0 + timedelta(days=settings.TITLE_WINDOW_DAYS + TRAFFIC_LAG_DAYS)
            for r in rows if r.get("origin") == InterventionOrigin.MIDAS
            and title_measurement._pending(r) and (d0 := title_measurement.as_of(r))]
    return min(days).isoformat() if days else None


def _lead_path(paths: dict) -> str:
    """The path with more titles written (ties: the pipeline): the one whose
    verdict and weeks stand for the cell."""
    return max(lever_verdicts.TITLE_SCOPES, key=lambda p: paths[p]["treated"])


def _title_counts(rows: list[dict], paths: dict) -> dict:
    """`_counts` for titles. `declined` and `judged` follow the title-test
    summary: a decline measured later is `judged` but still a decline, and a
    title put back after it was judged stays in the means (so it is in both
    `judged` and `reverted`)."""
    counts = _counts(rows, set())
    counts["declined"] = sum(p["declined"] for p in paths.values())
    counts["judged"] = len(_title_judged(rows))
    return counts


def _path_cell(summary: dict, holdout: dict, weeks: list[dict]) -> dict:
    """One path's figures: the title-test summary's own, then the cell fields
    (`mean_delta` / `cumulative_lift` are the same pooled numbers under their
    cell names) and the path's weekly verdict rows."""
    fired = [w for w in weeks if w.get("stop_rule_triggered")]
    latest = weeks[-1] if weeks else {}
    return {
        **summary,
        "n_treated": summary["judged"], "n_holdout": holdout["judged"],
        "treated_mean_delta": summary["mean_delta"], "holdout_mean_delta": holdout["mean_delta"],
        "lift": summary["cumulative_lift"],
        "windows_judged": latest.get("windows_judged") or 0,
        "verdict": latest.get("verdict"),
        "stop_rule_triggered": bool(fired),
        "stopped_week": fired[0]["week_start"] if fired else None,
        "weeks": [{k: w.get(k) for k in WEEK_FIELDS} for w in weeks],
    }


def _title_cell(rows: list[dict], weeks: list[dict], state: dict) -> dict:
    """A channel's title cell: backlinks' shape, with the means pooled over both
    paths against the shared holdout, the verdict, weeks and `cumulative_lift`
    of the lead path, and `paths` for each against the holdout."""
    scopes = lever_verdicts.TITLE_SCOPES
    fired_scopes = {w["arm_scope"] for w in weeks if w.get("stop_rule_triggered")}
    summary = lever_verdicts.title_paths(_midas(rows), lambda scope: scope in fired_scopes)
    paths = {p: _path_cell(summary["paths"][p], summary["holdout"],
                           [w for w in weeks if w["arm_scope"] == scopes[p]])
             for p in scopes}
    lead = paths[_lead_path(paths)]
    latest = lead["weeks"][-1] if lead["weeks"] else {}
    fired = sorted(p["stopped_week"] for p in paths.values() if p["stopped_week"])
    return {
        "state": state,
        "counts": _title_counts(rows, summary["paths"]),
        **_means(_title_judged(rows)),
        "cumulative_lift": latest.get("cumulative_lift"),
        "windows_judged": lead["windows_judged"],
        "verdict": lead["verdict"],
        "stop_rule_triggered": bool(fired),
        "stopped_week": fired[0] if fired else None,
        "weeks": lead["weeks"],
        "paths": paths,
        "first_verdict": _first_verdict(rows),
    }


def _midas(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("origin") == InterventionOrigin.MIDAS]


def _title_fleet(rows: list[dict], cells: list[dict]) -> dict:
    """The fleet's title cell: counts summed, every mean and path pooled over
    the visible channels' rows (never an average of channel lifts); no verdict
    or stop of its own, the stopped channels counted."""
    judged = _title_judged(rows)
    means = _means(judged)
    summary = lever_verdicts.title_paths(_midas(rows), lambda scope: False)
    stopped = {p: sum(1 for c in cells if c["paths"][p]["stop_rule_triggered"])
               for p in lever_verdicts.TITLE_SCOPES}
    paths = {}
    for p, scope in lever_verdicts.TITLE_SCOPES.items():
        weeks = _pooled_weeks([r for r in judged if lever_verdicts._title_arm(r) in
                               (p, InterventionArm.HOLDOUT)], scope)
        path = _path_cell(summary["paths"][p], summary["holdout"], weeks)
        paths[p] = {**path, "windows_judged": len(weeks), "verdict": None,
                    "stop_rule_triggered": None, "stopped_week": None,
                    "stopped": stopped[p] > 0, "stopped_channels": stopped[p]}
    weeks = paths[_lead_path(paths)]["weeks"]
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
        "paths": paths,
        "first_verdict": _first_verdict(rows),
    }


# ── The playlist test and Short links (#171) ────────────────────────────────

SHORT_LINK_STATUSES = (ShortLinkStatus.PENDING, ShortLinkStatus.SET,
                       ShortLinkStatus.NOT_CHOSEN, ShortLinkStatus.DISMISSED)


def _arm_counts(arms: list[dict]) -> dict:
    counts: dict = {}
    for a in arms:
        counts[a["status"]] = counts.get(a["status"], 0) + 1
    return counts


def _sum_dicts(dicts: list[dict]) -> dict:
    total: dict = {}
    for d in dicts:
        for k, n in d.items():
            total[k] = total.get(k, 0) + n
    return total


def _playlist_cell(summary: dict) -> dict:
    """A channel's playlist test, from `playlist_test.playlist_test_summary`
    (the channel's own endpoint reads the same function): its answer, dates,
    arms by status, and the weekly treated-vs-holdout rows with the latest's
    figures."""
    weeks = [v for v in summary["verdicts"]
             if v.get("arm_scope") == LeverVerdictScope.TREATED_VS_HOLDOUT]
    latest = weeks[-1] if weeks else {}
    fired = [w for w in weeks if w.get("stop_rule_triggered")]
    return {
        "answer": summary["answer"],
        "test_start": summary["test_start"], "test_end": summary["test_end"],
        "arms": _arm_counts(summary["arms"]),
        "lift": latest.get("lift"),
        "cumulative_lift": latest.get("cumulative_lift"),
        "windows_judged": latest.get("windows_judged") or 0,
        "verdict": latest.get("verdict"),
        "stop_rule_triggered": bool(fired),
        "stopped_week": fired[0]["week_start"] if fired else None,
        "weeks": [{k: w.get(k) for k in WEEK_FIELDS} for w in weeks],
    }


def _playlist_fleet(cells: list[dict]) -> dict:
    """Arms summed. Answers are never pooled: each channel's is listed (those
    with a test drawn), and the cell has no `answer` or lift of its own."""
    return {
        "arms": _sum_dicts([c["arms"] for c in cells]),
        "answers": {c["channel_id"]: c["answer"] for c in cells if c["arms"]},
        "stopped_channels": sum(1 for c in cells if c["stop_rule_triggered"]),
    }


def _short_link_cell(recs: list[dict], team: list[dict], human: list[dict]) -> dict:
    """The team's Short-link work (Midas only recommends): recommendations by
    status, those seen in type-32 traffic, the team's `short_link`
    interventions and the latest `human` verdict row. Never a Midas lift."""
    latest = max(human, key=lambda v: v["week_start"], default=None)
    return {
        "by": "team",
        "recommendations": {s: sum(1 for r in recs if r.get("status") == s)
                            for s in SHORT_LINK_STATUSES},
        "seen": sum(1 for r in recs if r.get("seen_at")),
        "team": len(team),
        "team_judged": sum(1 for r in team if r.get("status") == InterventionStatus.JUDGED),
        "verdict": None if latest is None else {
            k: latest.get(k) for k in ("week_start", "n_treated", "treated_mean_delta",
                                       "windows_judged")},
    }


def _short_link_fleet(cells: list[dict]) -> dict:
    return {
        "by": "team",
        "recommendations": _sum_dicts([c["recommendations"] for c in cells]),
        "seen": sum(c["seen"] for c in cells),
        "team": sum(c["team"] for c in cells),
        "team_judged": sum(c["team_judged"] for c in cells),
    }


def _shorts(rows: list[dict]) -> set:
    """Ids of the judged rows on a Short, which no mean reads."""
    judged = [r for r in rows if r.get("status") == InterventionStatus.JUDGED]
    kept = {r["id"] for r in lever_verdicts._without_shorts(judged)}
    return {r["id"] for r in judged if r["id"] not in kept}


def _read(table: str, columns: str, lever: str | None, user: dict, channel_id: str | None):
    query = supabase().table(table).select(columns)
    if lever is not None:
        query = query.eq("lever", lever)
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
    coverage = early_read.Coverage()
    fleet: dict = {"levers": {}}
    for name in LEVERS:
        if lever is not None and name != lever:
            continue
        if name == InterventionLever.PLAYLIST:
            cells = []
            for entry in out_channels:
                cell = _playlist_cell(playlist_test.playlist_test_summary(entry["id"]))
                entry["levers"][name] = cell
                cells.append({**cell, "channel_id": entry["id"]})
            fleet["levers"][name] = _playlist_fleet(cells)
            continue
        if name == InterventionLever.SHORT_LINK:
            recs = [r for r in _read("short_link_recommendations", REC_COLUMNS, None, user,
                                     channel_id) if r.get("channel_id") in ids] if ids else []
            team = [r for r in _read("interventions", COLUMNS, name, user, channel_id)
                    if r.get("channel_id") in ids and r.get("origin") == InterventionOrigin.HUMAN
                    ] if ids else []
            human = [v for v in _read("lever_verdicts", VERDICT_COLUMNS, name, user, channel_id)
                     if v.get("channel_id") in ids
                     and v.get("arm_scope") == LeverVerdictScope.HUMAN] if ids else []
            cells = []
            for entry in out_channels:
                cid = entry["id"]
                cell = _short_link_cell([r for r in recs if r["channel_id"] == cid],
                                        [r for r in team if r["channel_id"] == cid],
                                        [v for v in human if v["channel_id"] == cid])
                entry["levers"][name] = cell
                cells.append(cell)
            fleet["levers"][name] = _short_link_fleet(cells)
            continue
        rows = [r for r in _read("interventions", COLUMNS, name, user, channel_id)
                if r.get("channel_id") in ids] if ids else []
        verdicts = [v for v in _read("lever_verdicts", VERDICT_COLUMNS, name, user, channel_id)
                    if v.get("channel_id") in ids and v.get("arm_scope") in SCOPES[name]
                    ] if ids else []
        verdicts.sort(key=lambda v: v["week_start"])
        title = name == InterventionLever.TITLE
        shorts = set() if title else _shorts(rows)
        reads = list((early_read.titles(rows, coverage) if title
                      else early_read.backlinks(rows, coverage)).values())
        cells = []
        for entry in out_channels:
            cid = entry["id"]
            mine = [r for r in rows if r["channel_id"] == cid]
            weeks = [v for v in verdicts if v["channel_id"] == cid]
            cell = (_title_cell(mine, weeks, states[cid][name]) if title
                    else _channel_cell(mine, weeks, shorts, states[cid][name]))
            cell["early"] = early_read.summary([x for x in reads if x["channel_id"] == cid],
                                               with_reach=title)
            entry["levers"][name] = cell
            cells.append(cell)
        fleet["levers"][name] = (_title_fleet(rows, cells) if title
                                 else _fleet_cell(rows, cells, shorts))
        fleet["levers"][name]["early"] = early_read.summary(reads, with_reach=title)

    first = fleet["levers"].get(InterventionLever.TITLE, {}).get("first_verdict")
    return {"generated_at": now.isoformat(), "next_judgement": next_judgement(now).isoformat(),
            "first_title_verdicts": first, "channels": out_channels, "fleet": fleet}


# ── The changes drill-down (#173) ───────────────────────────────────────────

ORDERS = ("delta", "recent")
CHANGE_ARMS = (InterventionArm.TREATED, InterventionArm.HOLDOUT, InterventionArm.NOT_APPLICABLE)
CHANGES_MAX = 1000
CHANGES_DEFAULT = 100

CHANGE_COLUMNS = ("id,video_id,channel_id,lever,origin,arm,status,payload,applied_at,"
                  "detected_at,created_at,measurement_status,measurement_result")
ARM_COLUMNS = ("id,channel_id,playlist_id,arm,status,eligible_members,first_applied_at,"
               "last_applied_at,measurement_status,measurement_result,drawn_at")
REC_DETAIL_COLUMNS = ("id,channel_id,short_id,target_video_id,rank,similarity,impressions,"
                      "feed_views,status,decided_at,seen_at,created_at")
VIDEO_COLUMNS = "id,title,thumbnail_url,is_short"


def _video_info(videos: dict, video_id: str | None) -> dict | None:
    v = videos.get(video_id)
    return None if v is None else {k: v.get(k) for k in ("title", "thumbnail_url", "is_short")}


def _read_videos(ids: set) -> dict:
    ids = sorted(i for i in ids if i)
    if not ids:
        return {}
    return {v["id"]: v for v in rows_for_ids(
        lambda chunk: supabase().table("videos").select(VIDEO_COLUMNS).in_("id", chunk), ids)}


def _measured(row: dict) -> float | None:
    """The delta a row is ordered by: its measurement's, unless the window
    lacked data (`insufficient_data` is never judged)."""
    if row.get("status") == InterventionStatus.INSUFFICIENT_DATA:
        return None
    return _delta(row)


def _arm_delta(row: dict) -> float | None:
    """A playlist arm's latest weekly delta."""
    weeks = (row.get("measurement_result") or {}).get("weeks") or []
    return next((w["delta"] for w in reversed(weeks) if w.get("delta") is not None), None)


def _delta_order(rows: list[dict], delta, stamp: str) -> list[dict]:
    """Judged rows first: the gains best first, then the losses worst first;
    the rest (still open, no data) newest first."""
    def key(r):
        d = delta(r)
        if d is None:
            return (2, 0.0, _newest(r, stamp))
        return (0, -d, _newest(r, stamp)) if d >= 0 else (1, d, _newest(r, stamp))
    return sorted(rows, key=key)


def _newest(row: dict, stamp: str):
    """A (stamp, id) pair that sorts newest first inside an ascending key."""
    return _Rev((row.get(stamp) or "", row["id"]))


class _Rev:
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v

    def __lt__(self, other):
        return self.v > other.v

    def __eq__(self, other):
        return self.v == other.v


def _early_for(rows: list[dict], lever: str) -> dict:
    """{id: early} for the page's open rows, from `early_read` (read-only)."""
    title = lever == InterventionLever.TITLE
    reads = early_read.titles(rows) if title else early_read.backlinks(rows)
    out = {}
    for rid, x in reads.items():
        e = {"post_days": x["post_days"], "delta": x["delta"]}
        if title:
            e["impressions"] = {s: x["impressions"][s] for s in ("pre", "post")}
            e["ctr"] = {s: reach.weighted_ctr(x["reach"][s])[1] for s in ("pre", "post")}
        out[rid] = e
    return out


def _intervention_changes(channel_id: str, lever: str, arm: str | None, order: str,
                          limit: int, offset: int) -> list[dict]:
    query = (supabase().table("interventions").select(CHANGE_COLUMNS)
             .eq("channel_id", channel_id).eq("lever", lever))
    if arm:
        query = query.eq("arm", arm)
    rows = all_rows(query)
    if order == "recent":
        rows.sort(key=lambda r: (r.get("created_at") or "", r["id"]), reverse=True)
    else:
        rows = _delta_order(rows, _measured, "created_at")
    page = rows[offset:offset + limit]
    early = _early_for(page, lever)
    videos = _read_videos({r["video_id"] for r in page}
                          | {t.get("video_id") for r in page
                             for t in (r.get("payload") or {}).get("targets") or []
                             if isinstance(t, dict)})
    out = []
    for r in page:
        revert = (r.get("payload") or {}).get("revert")
        out.append({**trim(r), "video": _video_info(videos, r["video_id"]),
                    "early": early.get(r["id"]),
                    "reverted_by": None if not revert
                    else "midas" if revert.get("auto") is True else "person"})
    return out


def _arm_changes(channel_id: str, arm: str | None, order: str, limit: int,
                 offset: int) -> list[dict]:
    query = supabase().table("playlist_arms").select(ARM_COLUMNS).eq("channel_id", channel_id)
    if arm:
        query = query.eq("arm", arm)
    rows = all_rows(query)
    if order == "recent":
        rows.sort(key=lambda r: (r.get("drawn_at") or "", r["id"]), reverse=True)
    else:
        rows = _delta_order(rows, _arm_delta, "drawn_at")
    page = rows[offset:offset + limit]
    playlists = {}
    if page:
        playlists = {p["id"]: p for p in rows_for_ids(
            lambda chunk: supabase().table("playlists").select("id,title").in_("id", chunk),
            sorted({r["playlist_id"] for r in page}))}
    return [{**r, "delta": _arm_delta(r),
             "playlist": {"id": r["playlist_id"],
                          "title": (playlists.get(r["playlist_id"]) or {}).get("title")}}
            for r in page]


def _recommendation_changes(channel_id: str, order: str, limit: int, offset: int) -> list[dict]:
    rows = all_rows(supabase().table("short_link_recommendations")
                    .select(REC_DETAIL_COLUMNS).eq("channel_id", channel_id))
    # Pending first, the way the channel's card lists them, then the newest.
    rows.sort(key=lambda r: (r.get("created_at") or "", r["id"]), reverse=True)
    if order == "delta":
        rows.sort(key=lambda r: r.get("status") != ShortLinkStatus.PENDING)
    page = rows[offset:offset + limit]
    videos = _read_videos({r["short_id"] for r in page} | {r["target_video_id"] for r in page})
    return [{**r, "video": _video_info(videos, r["short_id"]),
             "target": _video_info(videos, r["target_video_id"])} for r in page]


@router.get("/seo/results/changes")
def seo_results_changes(channel_id: str, lever: str, arm: str | None = None,
                        order: str = "delta",
                        limit: int = Query(CHANGES_DEFAULT, ge=1, le=CHANGES_MAX),
                        offset: int = Query(0, ge=0),
                        user: dict = Depends(access.current_user)):
    """One cell's rows for one channel (the Results page's modal): the channel
    page's trimmed interventions with the video behind each and, for a row
    still in its window, its early read; the playlist test's arms; the Short
    links' recommendations. `arm` filters interventions and playlist arms
    (`treated|holdout|n/a`) and is ignored for Short links. `order=delta` puts
    the judged rows first, gains best first then losses worst first, the rest
    newest first; `recent` is newest first. `next_offset` is set when the page
    is full."""
    if lever not in ALL_INTERVENTION_LEVERS:
        raise HTTPException(400, f"unknown lever: {lever}")
    if arm is not None and arm not in CHANGE_ARMS:
        raise HTTPException(400, f"unknown arm: {arm}")
    if order not in ORDERS:
        raise HTTPException(400, f"unknown order: {order}")
    access.check_channel(user, channel_id)
    channel = (supabase().table("channels").select("id").eq("id", channel_id)
               .execute().data or [None])[0]
    if channel is None:
        raise HTTPException(404, access.CHANNEL_NOT_FOUND)

    if lever == InterventionLever.PLAYLIST:
        kind, changes = "arms", _arm_changes(channel_id, arm, order, limit, offset)
    elif lever == InterventionLever.SHORT_LINK:
        kind, changes = "recommendations", _recommendation_changes(channel_id, order, limit,
                                                                   offset)
    else:
        kind, changes = "interventions", _intervention_changes(channel_id, lever, arm, order,
                                                               limit, offset)
    return {"channel_id": channel_id, "lever": lever, "kind": kind, "arm": arm, "order": order,
            "limit": limit, "offset": offset,
            "next_offset": offset + limit if len(changes) == limit else None,
            "changes": changes}
