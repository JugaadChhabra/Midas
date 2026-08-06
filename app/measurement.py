"""CIL Loop 1 — per-video measurement (minimal slice: sense + judge, no auto-act).

After an audit is applied on a measurement-enabled channel, the audit enters
`awaiting_window`. Once the post-change window has elapsed AND the channel's
reach-CSV coverage certifies both windows, the daily `eval_measurements` job
compares post-change CTR against the video's own pre-change trailing window
(single-video A/B is impossible; trailing self-comparison is the honest
substitute — CIL Decision 3) and lands a terminal verdict:

    applied ─▶ awaiting_window ─▶ measuring ─┬─▶ win        ─▶ kept
                                             ├─▶ neutral    ─▶ kept
                                             └─▶ regression ─▶ (human review)

`measuring` here means "window elapsed, waiting for reach-CSV coverage" —
reach reports for a data-day arrive 1-6 days late (2026-07-02 probe), so a
window can be over on the calendar but not yet observable.

Deliberate deviations from the CIL §1 table, all toward caution:
  * AUTO_REVERT_ON_REGRESSION defaults false (CIL Decision 7): a regression
    verdict sets outcome_decision='none' and is surfaced via
    GET /channels/{id}/outcomes for a human to revert. No write to YouTube
    happens anywhere in this module.
  * Redo (§1.6) is NOT in this slice — queued behind watching a few real
    regressions first. redo_of_audit_id exists in the schema so nothing
    blocks it later.
  * Both windows exclude the apply day itself: it mixes pre/post regimes.

Windows are computed from `video_reach_daily` (daily grain — this is exactly
why Phase 0.5 chose a daily table), and the pre-change window is also written
to `video_metrics` with `is_pre_change=true` (CIL §1.2) so baselines are
inspectable alongside the weekly sensor windows.

Impressions floors (CIL §0.5 / §1.2 / §1.3):
  * pre-window impressions < MIN_IMPRESSIONS  → not_applicable (dormant
    video — metadata can't create demand; the "don't bother" rule in code).
  * post-window impressions < MIN_IMPRESSIONS → neutral (can't tell; don't
    penalize).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db import supabase
from app.rows import all_rows, rows_for_ids
from app.status_vocab import (
    ACTIVE_MEASUREMENT_STATUSES,
    MEASURED_STATUSES,
    AuditStatus,
    MeasurementStatus,
    OutcomeDecision,
)
# Coverage certification must use the identical definition of "covered
# data-day" — and the identical window walk — that the reach backfill uses, or
# the two pipelines disagree about whether a window is observable yet.
from app.reporting_poll import coverage_for_channel, days_between as _reporting_days_between

log = logging.getLogger("midas.measurement")

router = APIRouter()

_TERMINAL = MEASURED_STATUSES


# ── Window math ───────────────────────────────────────────────────────────

def _apply_date(audit: dict) -> date | None:
    ts = audit.get("applied_at") or audit.get("measurement_started_at")
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()


def _windows(applied: date) -> tuple[tuple[str, str], tuple[str, str]]:
    """(pre_start, pre_end), (post_start, post_end).

    Apply day ±1 excluded from BOTH windows: reach data-days roll over on
    America/Los_Angeles while `applied` is a UTC date, so the adjacent
    data-days can contain mixed pre/post exposure. Each window is still
    MEASUREMENT_WINDOW_DAYS long — shifted outward, not shortened.
    """
    n = settings.MEASUREMENT_WINDOW_DAYS
    pre = ((applied - timedelta(days=n + 1)).isoformat(), (applied - timedelta(days=2)).isoformat())
    post = ((applied + timedelta(days=2)).isoformat(), (applied + timedelta(days=n + 1)).isoformat())
    return pre, post


#: Inclusive list of ISO days in a window. Imported rather than redefined:
#: reporting_poll's backfill must walk windows identically or the two pipelines
#: disagree about which data-days a window needs.
days_between = _reporting_days_between


def _reach_aggregate(video_id: str, start: str, end: str) -> tuple[int, float | None]:
    """(impressions, weighted ctr) over [start, end] from video_reach_daily.

    Weighted like reporting_poll's backfill: ctr = Σclicks / Σimpressions.
    Missing days are REAL zeros here — callers only invoke this on
    coverage-certified windows. ctr None on zero impressions (no signal).
    """
    rows = all_rows(
            supabase().table("video_reach_daily")
            .select("impressions,ctr")
            .eq("video_id", video_id)
            .gte("date", start)
            .lte("date", end)
    )
    impressions = sum(r["impressions"] for r in rows)
    clicks = sum(r["impressions"] * r["ctr"] for r in rows)
    return impressions, (clicks / impressions) if impressions > 0 else None


# ── Verdict ───────────────────────────────────────────────────────────────

def _classify(pre_ctr: float | None, post_ctr: float | None) -> tuple[str, float | None]:
    """(measurement_status, relative delta). Floors already applied by caller."""
    if pre_ctr is None or pre_ctr == 0.0:
        # >= MIN_IMPRESSIONS with literally zero clicks pre-change: the
        # relative delta is undefined, and a single stray post-change click
        # should not mint a "win" that Loop 2 would then learn from.
        # Neutral — genuinely can't tell.
        return MeasurementStatus.NEUTRAL, None
    delta = ((post_ctr or 0.0) - pre_ctr) / pre_ctr
    if delta >= settings.CTR_WIN_THRESHOLD:
        return MeasurementStatus.WIN, delta
    if delta <= settings.CTR_REGRESSION_THRESHOLD:
        return MeasurementStatus.REGRESSION, delta
    return MeasurementStatus.NEUTRAL, delta


def _write_baseline(*, video_id: str, channel_id: str, pre: tuple[str, str],
                    impressions: int, ctr: float | None) -> None:
    """Persist the pre-change window to video_metrics (CIL §1.2)."""
    supabase().table("video_metrics").upsert(
        {
            "video_id": video_id,
            "channel_id": channel_id,
            "window_start": pre[0],
            "window_end": pre[1],
            "impressions": impressions,
            "ctr": ctr,
            "is_pre_change": True,
        },
        on_conflict="video_id,window_start,window_end",
    ).execute()


def _finalize(audit_id: int, status: str, outcome: str, result: dict) -> None:
    supabase().table("audits").update({
        "measurement_status": status,
        "outcome_decision": outcome,
        "measurement_result": result,
    }).eq("id", audit_id).execute()


# ── The decision, as two pure stages ──────────────────────────────────────
#
# Everything below decides; nothing reads or writes. _eval_audit is the shell
# that carries data between them. Splitting here is what makes the six policies
# testable: they used to sit between four Supabase round-trips in one body.

#: plan_measurement actions.
HOLD = "hold"                      # window still open — leave the row alone
MARK_MEASURING = "mark_measuring"  # window closed, reach CSVs not in yet
FINALIZE = "finalize"              # terminal, decided without reading reach
MEASURE = "measure"                # go read the reach windows, then judge


@dataclass(frozen=True)
class Plan:
    """What to do with an audit *before* any reach data is read."""

    action: str
    status: str | None = None
    outcome: str | None = None
    result: dict = field(default_factory=dict)
    pre: tuple[str, str] | None = None
    post: tuple[str, str] | None = None


@dataclass(frozen=True)
class Verdict:
    """A terminal measurement outcome and the evidence behind it."""

    status: str
    outcome: str
    result: dict


def plan_measurement(audit: dict, today: date, covered: set[str]) -> Plan:
    """Decide an audit's next state from its timestamps and coverage alone."""
    applied = _apply_date(audit)
    if applied is None:
        # awaiting_window without a timestamp — data bug; park it as
        # not_applicable (NOT neutral: neutral is a measured outcome and
        # feeds Loop 2's counts; this was never measured).
        return Plan(
            FINALIZE, MeasurementStatus.NOT_APPLICABLE, OutcomeDecision.NONE,
            {"rationale": "no applied_at/measurement_started_at timestamp; cannot window"},
        )

    pre, post = _windows(applied)
    post_end = date.fromisoformat(post[1])
    if today <= post_end:
        return Plan(HOLD, audit["measurement_status"])

    need = days_between(*pre) + days_between(*post)
    missing = [d for d in need if d not in covered]
    if missing:
        if today > post_end + timedelta(days=settings.MEASUREMENT_COVERAGE_GRACE_DAYS):
            return Plan(FINALIZE, MeasurementStatus.NEUTRAL, OutcomeDecision.KEPT, {
                "rationale": "reach coverage never completed within grace period",
                "missing_days": missing[:14],
                "pre_window": pre, "post_window": post,
            })
        return Plan(MARK_MEASURING, MeasurementStatus.MEASURING)

    return Plan(MEASURE, pre=pre, post=post)


def judge_reach(*, pre: tuple[str, str], post: tuple[str, str],
                pre_imp: int, pre_ctr: float | None,
                post_imp: int, post_ctr: float | None) -> Verdict:
    """Turn a measured window pair into a terminal verdict."""
    result = {
        "pre_window": {"start": pre[0], "end": pre[1], "impressions": pre_imp, "ctr": pre_ctr},
        "post_window": {"start": post[0], "end": post[1], "impressions": post_imp, "ctr": post_ctr},
        # Recorded so a later threshold change can't silently reinterpret an
        # old verdict.
        "min_impressions": settings.MIN_IMPRESSIONS,
        "win_threshold": settings.CTR_WIN_THRESHOLD,
        "regression_threshold": settings.CTR_REGRESSION_THRESHOLD,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        # v1 is bundle-level attribution (title+description+tags moved
        # together) — CIL open-question decision. Recorded so Loop 2's
        # distiller can say so.
        "attribution": "bundle",
    }

    # Dormant is checked first and deliberately: not_applicable and neutral
    # mean different things to Loop 2, and a dormant video fails both floors.
    if pre_imp < settings.MIN_IMPRESSIONS:
        result["rationale"] = f"dormant pre-change ({pre_imp} impressions < {settings.MIN_IMPRESSIONS} floor)"
        return Verdict(MeasurementStatus.NOT_APPLICABLE, OutcomeDecision.NONE, result)
    if post_imp < settings.MIN_IMPRESSIONS:
        result["rationale"] = f"insufficient post-change impressions ({post_imp} < {settings.MIN_IMPRESSIONS})"
        return Verdict(MeasurementStatus.NEUTRAL, OutcomeDecision.KEPT, result)

    status, delta = _classify(pre_ctr, post_ctr)
    result["ctr_delta_relative"] = delta
    if status == MeasurementStatus.WIN:
        result["rationale"] = "CTR up beyond win threshold"
        return Verdict(status, OutcomeDecision.KEPT, result)
    if status == MeasurementStatus.NEUTRAL:
        result["rationale"] = "CTR within noise band"
        return Verdict(status, OutcomeDecision.KEPT, result)
    result["rationale"] = "CTR down beyond regression threshold"
    # Human-gated: AUTO_REVERT_ON_REGRESSION defaults false and this slice does
    # not implement auto-revert at all — the verdict is surfaced for an operator
    # to POST /audits/{id}/revert.
    return Verdict(status, OutcomeDecision.NONE, result)


def _eval_audit(audit: dict, video: dict, covered: set[str], today: date) -> str:
    """Evaluate one audit. Returns the (possibly unchanged) measurement_status.

    Plumbing only: decide, fetch what the decision asked for, decide again,
    persist. The policies live in plan_measurement and judge_reach.
    """
    plan = plan_measurement(audit, today, covered)

    if plan.action == HOLD:
        return plan.status
    if plan.action == FINALIZE:
        _finalize(audit["id"], plan.status, plan.outcome, plan.result)
        return plan.status
    if plan.action == MARK_MEASURING:
        if audit["measurement_status"] != MeasurementStatus.MEASURING:
            supabase().table("audits").update(
                {"measurement_status": MeasurementStatus.MEASURING}
            ).eq("id", audit["id"]).execute()
        return MeasurementStatus.MEASURING

    pre_imp, pre_ctr = _reach_aggregate(audit["video_id"], *plan.pre)
    post_imp, post_ctr = _reach_aggregate(audit["video_id"], *plan.post)

    _write_baseline(video_id=audit["video_id"], channel_id=video["channel_id"],
                    pre=plan.pre, impressions=pre_imp, ctr=pre_ctr)

    verdict = judge_reach(pre=plan.pre, post=plan.post,
                          pre_imp=pre_imp, pre_ctr=pre_ctr,
                          post_imp=post_imp, post_ctr=post_ctr)
    _finalize(audit["id"], verdict.status, verdict.outcome, verdict.result)

    if verdict.status == MeasurementStatus.REGRESSION:
        log.warning(
            "REGRESSION verdict: audit %s video %s ctr %.4f → %.4f (Δ %.1f%%) — awaiting human review",
            audit["id"], audit["video_id"], pre_ctr or 0.0, post_ctr or 0.0,
            (verdict.result.get("ctr_delta_relative") or 0.0) * 100,
        )
    return verdict.status


# ── Job entry point ───────────────────────────────────────────────────────

def eval_measurements() -> dict:
    """Daily pass over all audits in awaiting_window / measuring.

    Once an audit has entered the pipeline it is evaluated even if the
    channel's measurement_enabled flag was flipped off afterwards — the flag
    gates ENTRY (at apply), not evaluation of in-flight measurements.
    """
    audits = all_rows(
            supabase().table("audits")
            .select("id,video_id,applied_at,measurement_started_at,measurement_status")
            .in_("measurement_status", list(ACTIVE_MEASUREMENT_STATUSES))
            # Only still-applied audits: a human revert mid-window takes the
            # video off the new metadata, so the post window would measure
            # post-REVERT exposure — and _finalize would clobber the
            # operator's outcome_decision='reverted'. revert_audit parks the
            # measurement state; this filter is the belt to that suspender.
            .eq("status", AuditStatus.APPLIED)
            .order("id")
    )
    if not audits:
        log.info("measurement_eval: nothing in flight")
        return {"evaluated": 0}

    # Resolve channel per audit (audits carry no channel_id), chunked.
    video_ids = list({a["video_id"] for a in audits})
    videos: dict[str, dict] = {}
    for i in range(0, len(video_ids), 100):
        for v in (
            supabase().table("videos")
            .select("id,channel_id")
            .in_("id", video_ids[i : i + 100])
            .execute()
            .data or []
        ):
            videos[v["id"]] = v

    today = datetime.now(timezone.utc).date()
    coverage: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    errors = 0
    for audit in audits:
        try:
            video = videos.get(audit["video_id"])
            if not video:
                _finalize(audit["id"], MeasurementStatus.NOT_APPLICABLE, OutcomeDecision.NONE,
                          {"rationale": "video row no longer exists"})
                counts[MeasurementStatus.NOT_APPLICABLE] = counts.get(MeasurementStatus.NOT_APPLICABLE, 0) + 1
                continue
            cid = video["channel_id"]
            if cid not in coverage:
                _, coverage[cid] = coverage_for_channel(cid)
            status = _eval_audit(audit, video, coverage[cid], today)
            counts[status] = counts.get(status, 0) + 1
        except Exception as e:
            errors += 1
            log.exception("measurement_eval failed for audit %s: %s", audit.get("id"), e)

    summary = {"evaluated": len(audits), "errors": errors, **counts}
    log.info("measurement_eval: %s", summary)
    return summary


# ── Endpoints (CIL §1.8, minimal slice subset) ────────────────────────────

@router.get("/audits/{audit_id}/measurement")
def get_measurement(audit_id: int):
    res = (
        supabase().table("audits")
        .select("id,video_id,status,applied_at,measurement_status,"
                "measurement_started_at,measurement_result,outcome_decision,"
                "redo_of_audit_id,strategy_version")
        .eq("id", audit_id)
        .maybe_single()
        .execute()
    )
    # maybe_single().execute() returns None (not an empty response) on 0 rows.
    audit = res.data if res else None
    if not audit:
        raise HTTPException(404, "Audit not found")
    return audit


@router.get("/channels/{channel_id}/outcomes")
def channel_outcomes(channel_id: str):
    """Win/neutral/regression rollup — Loop 2's input and the ops surface
    where human-gated regressions show up for review."""
    video_ids = [
        v["id"] for v in all_rows(
            supabase().table("videos")
            .select("id")
            .eq("channel_id", channel_id)
            .order("id")
        )
    ]
    if not video_ids:
        return {"channel_id": channel_id, "counts": {}, "pending_review": [], "recent": []}

    # One video has many audits, so each id-chunk is paged too — rows_for_ids
    # does both.
    rows = rows_for_ids(
        lambda chunk: (
            supabase().table("audits")
            .select("id,video_id,applied_at,measurement_status,outcome_decision,"
                    "measurement_result,strategy_version")
            .in_("video_id", chunk)
            .neq("measurement_status", MeasurementStatus.NOT_APPLICABLE)
            .order("id")
        ),
        video_ids,
    )

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["measurement_status"]] = counts.get(r["measurement_status"], 0) + 1

    terminal = [r for r in rows if r["measurement_status"] in _TERMINAL]
    terminal.sort(key=lambda r: (r.get("applied_at") or ""), reverse=True)
    pending_review = [
        r for r in terminal
        if r["measurement_status"] == MeasurementStatus.REGRESSION
        and r["outcome_decision"] == OutcomeDecision.NONE
    ]
    return {
        "channel_id": channel_id,
        "counts": counts,
        "pending_review": pending_review,
        "recent": terminal[:25],
    }


@router.post("/measurement/evaluate")
def trigger_eval():
    """Manual ops trigger for the daily eval pass."""
    return eval_measurements()
