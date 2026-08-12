"""Loop 1's judge, tested through pure functions.

measurement.py is 405 lines containing the six policy decisions that turn an
applied audit into win / neutral / regression — and it had ZERO tests, because
those policies were interleaved with four Supabase round-trips inside one
function body. Four of its helpers were already pure and still untested.

The decision is now two pure stages with the I/O pushed to the edges:

    plan_measurement(audit, today, covered)  -- what to do before reading reach
    judge_reach(...)                         -- the verdict, given the numbers

so every branch below runs with no mocks at all.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app import measurement as m
from app import reach
from app.status_vocab import MeasurementStatus, OutcomeDecision

APPLIED = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def _fixed_thresholds():
    """Pin the policy knobs so these tests describe behaviour, not config."""
    with patch.object(m.settings, "MEASUREMENT_WINDOW_DAYS", 21), \
         patch.object(m.settings, "MIN_IMPRESSIONS", 500), \
         patch.object(m.settings, "CTR_WIN_THRESHOLD", 0.10), \
         patch.object(m.settings, "CTR_REGRESSION_THRESHOLD", -0.10), \
         patch.object(m.settings, "MEASUREMENT_COVERAGE_GRACE_DAYS", 14):
        yield


def _audit(**kw):
    return {"id": 1, "video_id": "v1", "applied_at": "2026-06-01T12:00:00+00:00",
            "measurement_status": MeasurementStatus.AWAITING_WINDOW, **kw}


def _covered(pre, post):
    return set(reach.days(pre)) | set(reach.days(post))


# Window arithmetic itself now belongs to app.reach and is tested in
# tests/test_reach.py. What remains here is what measurement decides GIVEN a
# window: the plan, and the verdict.


def test_apply_date_prefers_applied_at_then_falls_back():
    assert m._apply_date({"applied_at": "2026-06-01T00:00:00Z"}) == APPLIED
    assert m._apply_date({"measurement_started_at": "2026-06-01T00:00:00Z"}) == APPLIED
    assert m._apply_date({}) is None


# ── classify ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pre,post,status", [
    (0.04, 0.05, MeasurementStatus.WIN),          # +25%
    (0.04, 0.042, MeasurementStatus.NEUTRAL),     # +5%
    (0.04, 0.039, MeasurementStatus.NEUTRAL),     # -2.5%
    (0.04, 0.02, MeasurementStatus.REGRESSION),   # -50%
])
def test_classify_thresholds(pre, post, status):
    assert m._classify(pre, post)[0] == status


def test_thresholds_are_inclusive_at_the_boundary():
    """A delta landing exactly on the threshold counts.

    Uses exactly-representable values: with realistic CTRs like 0.04 -> 0.044
    the delta computes to 0.09999999999999991, so the "boundary" would be
    fictional and the test would be asserting float noise.
    """
    with patch.object(m.settings, "CTR_WIN_THRESHOLD", 0.5), \
         patch.object(m.settings, "CTR_REGRESSION_THRESHOLD", -0.5):
        assert (3.0 - 2.0) / 2.0 == 0.5          # exact
        assert m._classify(2.0, 3.0)[0] == MeasurementStatus.WIN
        assert (1.0 - 2.0) / 2.0 == -0.5         # exact
        assert m._classify(2.0, 1.0)[0] == MeasurementStatus.REGRESSION


def test_zero_pre_ctr_is_neutral_not_a_win():
    """A single stray post-change click must not mint a win Loop 2 learns from."""
    for pre in (None, 0.0):
        status, delta = m._classify(pre, 0.05)
        assert status == MeasurementStatus.NEUTRAL
        assert delta is None


def test_missing_post_ctr_counts_as_zero():
    status, delta = m._classify(0.04, None)
    assert status == MeasurementStatus.REGRESSION
    assert delta == pytest.approx(-1.0)


# ── plan_measurement: the pre-reach policies ──────────────────────────────

def test_no_timestamp_is_parked_as_not_applicable():
    """not_applicable, NOT neutral — neutral is a measured outcome that feeds
    Loop 2's counts; this was never measured."""
    p = m.plan_measurement(_audit(applied_at=None), date(2026, 7, 1), set())
    assert p.action == m.FINALIZE
    assert p.status == MeasurementStatus.NOT_APPLICABLE
    assert p.outcome == OutcomeDecision.NONE


def test_open_window_is_held_unchanged():
    p = m.plan_measurement(_audit(), date(2026, 6, 10), set())
    assert p.action == m.HOLD
    assert p.status == MeasurementStatus.AWAITING_WINDOW


def test_closed_window_with_full_coverage_proceeds_to_measure():
    pre, post = reach.window_for(APPLIED)
    p = m.plan_measurement(_audit(), date(2026, 7, 1), _covered(pre, post))
    assert p.action == m.MEASURE
    assert (p.pre, p.post) == (pre, post)


def test_missing_coverage_within_grace_waits_as_measuring():
    """'measuring' means window closed, reach CSVs not in yet — they arrive
    1-6 days late."""
    pre, post = reach.window_for(APPLIED)
    covered = _covered(pre, post) - {post[1]}
    p = m.plan_measurement(_audit(), date(2026, 7, 1), covered)
    assert p.action == m.MARK_MEASURING


def _covered_up_to(pre, post, frontier_day, missing):
    """Coverage of both windows minus `missing`, extended to `frontier_day`.

    The grace period runs in INGESTED time, so a test about giving up has to say
    how far ingestion actually got — not just what today's date is.
    """
    days = _covered(pre, post) - set(missing)
    cursor = date.fromisoformat(post[1])
    end = date.fromisoformat(frontier_day)
    while cursor <= end:
        days.add(cursor.isoformat())
        cursor += timedelta(days=1)
    return days - set(missing)


def test_missing_coverage_gives_up_once_ingestion_has_moved_past_the_window():
    """not_applicable, NOT neutral — and only once the frontier proves the days
    are lost rather than late.

    Coverage never arriving is a fact about our ingestion, not about the
    audience. As neutral it entered the win rate that promotes prompt versions
    (reflection filters on MEASURED_STATUSES, which excludes not_applicable) and
    counted toward the _MIN_DATA_POINTS floor meant to keep the prompt loop off
    thin evidence. A downed poller must not read as a prompt that didn't work.
    """
    pre, post = reach.window_for(APPLIED)
    # post_end is 2026-06-23; ingestion has reached 2026-07-10, well past
    # post_end + 14 — so the hole at post[1] will never be filled.
    covered = _covered_up_to(pre, post, "2026-07-10", {post[1]})
    p = m.plan_measurement(_audit(), date(2026, 7, 20), covered)
    assert p.action == m.FINALIZE
    assert p.status == MeasurementStatus.NOT_APPLICABLE
    assert p.outcome == OutcomeDecision.NONE
    assert p.result["missing_days"] == [post[1]]
    assert p.result["frontier"] == "2026-07-10"


def test_a_stalled_poller_holds_instead_of_expiring():
    """The reason this commit exists. The window closed a month ago on the
    calendar, but ingestion stopped the day it closed — so there is nothing to
    conclude, and wall-clock grace would have manufactured a verdict out of our
    own outage."""
    pre, post = reach.window_for(APPLIED)
    covered = _covered(pre, post) - {post[1]}          # frontier stuck at post_end - 1
    p = m.plan_measurement(_audit(), date(2026, 8, 30), covered)
    assert p.action == m.MARK_MEASURING
    assert p.result["awaiting_ingestion"] is True
    assert p.result["missing_days"] == [post[1]]


def test_a_channel_with_no_coverage_at_all_holds():
    """Nothing ingested ever: there is no frontier, so no clock can have run."""
    p = m.plan_measurement(_audit(), date(2026, 12, 31), set())
    assert p.action == m.MARK_MEASURING
    assert p.result["awaiting_ingestion"] is True


def test_the_grace_verdict_is_excluded_from_the_evidence_base():
    """The property that makes the status choice matter, asserted rather than
    assumed: whatever plan_measurement finalizes here must not be a status the
    prompt loop counts."""
    from app.status_vocab import MEASURED_STATUSES

    pre, post = reach.window_for(APPLIED)
    covered = _covered_up_to(pre, post, "2026-07-10", {post[1]})
    p = m.plan_measurement(_audit(), date(2026, 7, 20), covered)
    assert p.status not in MEASURED_STATUSES


def test_grace_boundary_is_not_off_by_one():
    """Measured against the frontier, not today: grace expires when ingestion has
    passed post_end + 14, whatever the calendar says."""
    pre, post = reach.window_for(APPLIED)
    post_end = date.fromisoformat(post[1])
    far_future = date(2027, 1, 1)

    at_edge = _covered_up_to(pre, post, (post_end + timedelta(days=14)).isoformat(), {post[1]})
    assert m.plan_measurement(_audit(), far_future, at_edge).action \
        == m.MARK_MEASURING          # frontier only just reached the edge
    past_edge = _covered_up_to(pre, post, (post_end + timedelta(days=15)).isoformat(), {post[1]})
    assert m.plan_measurement(_audit(), far_future, past_edge).action \
        == m.FINALIZE                # ingestion moved past it; the days are lost


# ── judge_reach: the post-reach policies ──────────────────────────────────

def _judge(pre_imp, pre_ctr, post_imp, post_ctr):
    pre, post = reach.window_for(APPLIED)
    return m.judge_reach(pre=pre, post=post, pre_imp=pre_imp, pre_ctr=pre_ctr,
                         post_imp=post_imp, post_ctr=post_ctr)


def test_dormant_pre_window_is_not_applicable():
    """Metadata can't create demand — the 'don't bother' rule."""
    v = _judge(100, 0.04, 5000, 0.06)
    assert v.status == MeasurementStatus.NOT_APPLICABLE
    assert v.outcome == OutcomeDecision.NONE
    assert "dormant" in v.result["rationale"]


def test_thin_post_window_is_neutral_not_a_penalty():
    v = _judge(5000, 0.04, 100, 0.01)
    assert v.status == MeasurementStatus.NEUTRAL
    assert v.outcome == OutcomeDecision.KEPT
    assert "insufficient post-change" in v.result["rationale"]


def test_a_win_is_kept():
    v = _judge(5000, 0.04, 5000, 0.06)
    assert (v.status, v.outcome) == (MeasurementStatus.WIN, OutcomeDecision.KEPT)
    assert v.result["ctr_delta_relative"] == pytest.approx(0.5)


def test_a_regression_is_not_auto_acted_on():
    """AUTO_REVERT_ON_REGRESSION is off: the verdict is surfaced for a human."""
    v = _judge(5000, 0.04, 5000, 0.02)
    assert v.status == MeasurementStatus.REGRESSION
    assert v.outcome == OutcomeDecision.NONE


def test_result_records_the_thresholds_it_judged_against():
    """Otherwise a later threshold change silently reinterprets old verdicts."""
    v = _judge(5000, 0.04, 5000, 0.06)
    assert v.result["min_impressions"] == 500
    assert v.result["win_threshold"] == 0.10
    assert v.result["regression_threshold"] == -0.10
    assert v.result["attribution"] == "bundle"
    assert v.result["pre_window"]["impressions"] == 5000


def test_the_dormant_check_precedes_the_thin_post_check():
    """Both floors fail here; dormant must win, since not_applicable and
    neutral mean different things to Loop 2."""
    v = _judge(100, 0.04, 100, 0.04)
    assert v.status == MeasurementStatus.NOT_APPLICABLE
