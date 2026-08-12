"""The measured-outcome shape — app/verdicts.py.

Loop 1 writes `audits.measurement_result`; four readers used to destructure it by
string key, each re-deriving the same numbers. The failure mode that justifies a
single owner is silent: `ctr_delta_relative` is legitimately absent on a neutral
verdict, so a reader looking for a wrong or renamed key finds None, reports "no
delta", and is indistinguishable from one working correctly.

Everything here runs without mocks.
"""
import re
from pathlib import Path

import pytest

from app import verdicts
from app.verdicts import Verdict
from app.status_vocab import MeasurementStatus, OutcomeDecision

PRE = ("2026-05-10", "2026-05-30")
POST = ("2026-06-03", "2026-06-23")


def _result(**over):
    r = verdicts.result_of(
        pre=PRE, post=POST, pre_imp=5000, pre_ctr=0.04,
        post_imp=5200, post_ctr=0.06,
        min_impressions=500, win_threshold=0.10, regression_threshold=-0.10,
        evaluated_at="2026-07-01T00:00:00+00:00",
    )
    r.update(over)
    return r


# ── the written shape ─────────────────────────────────────────────────────

def test_the_result_records_both_windows_with_their_numbers():
    r = _result()
    assert r[verdicts.PRE_WINDOW] == {
        "start": "2026-05-10", "end": "2026-05-30", "impressions": 5000, "ctr": 0.04}
    assert r[verdicts.POST_WINDOW] == {
        "start": "2026-06-03", "end": "2026-06-23", "impressions": 5200, "ctr": 0.06}


def test_the_result_records_the_thresholds_it_was_judged_against():
    """Otherwise a later threshold change silently reinterprets old verdicts."""
    r = _result()
    assert r["min_impressions"] == 500
    assert r["win_threshold"] == 0.10
    assert r["regression_threshold"] == -0.10


def test_attribution_is_recorded_as_bundle():
    """Title, description and tags move together, so a verdict cannot be
    apportioned between them. Loop 2's distiller has to be told that."""
    assert _result()["attribution"] == "bundle"


# ── reading one back ──────────────────────────────────────────────────────

def _audit(**over):
    a = {"id": 1, "measurement_status": MeasurementStatus.WIN,
         "outcome_decision": OutcomeDecision.KEPT,
         "measurement_result": _result(**{verdicts.CTR_DELTA: 0.5})}
    a.update(over)
    return a


def test_a_measured_audit_yields_its_verdict():
    v = verdicts.from_audit(_audit())
    assert v.status == MeasurementStatus.WIN
    assert v.outcome == OutcomeDecision.KEPT
    assert v.ctr_delta == 0.5
    assert v.pre_ctr == 0.04
    assert v.post_ctr == 0.06


@pytest.mark.parametrize("status", [
    MeasurementStatus.AWAITING_WINDOW,
    MeasurementStatus.MEASURING,
    MeasurementStatus.NOT_APPLICABLE,
    None,
])
def test_an_unmeasured_audit_has_no_verdict(status):
    """not_applicable included deliberately: never measured is not a verdict,
    which is what keeps a downed poller out of the win rate."""
    assert verdicts.from_audit(_audit(measurement_status=status)) is None


def test_a_missing_delta_reads_as_no_signal_not_as_zero():
    """A neutral verdict under the impressions floor has nothing to compare. Zero
    would be a measured no-change, which is a different claim."""
    v = verdicts.from_audit(_audit(
        measurement_status=MeasurementStatus.NEUTRAL,
        measurement_result=_result()))          # no ctr_delta key at all
    assert v.ctr_delta is None


def test_an_absent_result_does_not_explode():
    v = verdicts.from_audit(_audit(measurement_result=None))
    assert (v.ctr_delta, v.pre_ctr, v.post_ctr, v.rationale) == (None, None, None, None)


def test_a_verdict_round_trips_through_the_stored_shape():
    """The property that makes one owner worth having: what the writer writes is
    what the reader reads, without either naming a key itself."""
    written = _result(**{verdicts.CTR_DELTA: -0.25, verdicts.RATIONALE: "CTR down"})
    v = verdicts.from_audit(_audit(
        measurement_status=MeasurementStatus.REGRESSION,
        measurement_result=written))
    assert v.ctr_delta == -0.25
    assert v.rationale == "CTR down"
    assert (v.pre_ctr, v.post_ctr) == (0.04, 0.06)


# ── levers ────────────────────────────────────────────────────────────────

def test_each_lever_is_detected_independently():
    assert verdicts.levers({"title_before": "a", "suggested_title": "b"}) == \
        frozenset({verdicts.TITLE})
    assert verdicts.levers({"description_before": "a", "suggested_description": "b"}) == \
        frozenset({verdicts.DESCRIPTION})
    assert verdicts.levers({"tags_before": ["a"], "suggested_tags": ["b"]}) == \
        frozenset({verdicts.TAGS})


def test_an_unchanged_field_is_not_a_lever():
    """An audit that 'changed' the title to the same string moved nothing."""
    assert verdicts.levers({
        "title_before": "same", "suggested_title": "same",
        "description_before": "d", "suggested_description": "d",
        "tags_before": ["x"], "suggested_tags": ["x"],
    }) == frozenset()


def test_none_and_empty_are_the_same_absence():
    """A title going from NULL to "" is not a change anyone made."""
    assert verdicts.levers({"title_before": None, "suggested_title": ""}) == frozenset()
    assert verdicts.levers({"tags_before": None, "suggested_tags": []}) == frozenset()


def test_tag_order_counts_as_a_change():
    """Tag order is part of what was applied to YouTube, so a reorder is a real
    edit — the list comparison is deliberate, not a set."""
    assert verdicts.levers({"tags_before": ["a", "b"], "suggested_tags": ["b", "a"]}) == \
        frozenset({verdicts.TAGS})


def test_an_empty_audit_moved_nothing():
    assert verdicts.levers({}) == frozenset()


def test_all_three_can_move_together():
    moved = verdicts.levers({
        "title_before": "a", "suggested_title": "b",
        "description_before": "c", "suggested_description": "d",
        "tags_before": [], "suggested_tags": ["e"],
    })
    assert moved == frozenset(verdicts.ALL_LEVERS)


# ── evidence ──────────────────────────────────────────────────────────────

def test_a_reverted_regression_is_still_evidence():
    """The behaviour change. Reverting is what an operator does to a BAD outcome,
    so filtering evidence on status='applied' drops the worst results and
    flatters the prompt version that produced them."""
    reverted = {"status": "reverted", "measurement_status": MeasurementStatus.REGRESSION,
                "measurement_result": _result(**{verdicts.CTR_DELTA: -0.4})}
    assert verdicts.is_evidence(reverted) is True
    assert verdicts.evidence([reverted])[0].ctr_delta == -0.4


def test_an_unmeasured_audit_is_not_evidence():
    for status in (MeasurementStatus.MEASURING, MeasurementStatus.NOT_APPLICABLE, None):
        assert verdicts.is_evidence({"measurement_status": status}) is False


def test_evidence_drops_the_rows_without_verdicts():
    rows = [_audit(), {"measurement_status": MeasurementStatus.MEASURING}, _audit()]
    assert len(verdicts.evidence(rows)) == 2


# ── rollups ───────────────────────────────────────────────────────────────

def test_win_rate_counts_neutral_in_the_denominator():
    """Neutral is a measured outcome, not an absent one — a prompt that produces
    flat results is not a prompt with no results."""
    assert verdicts.win_rate(["win", "neutral", "neutral", "regression"]) == 25.0


def test_win_rate_of_nothing_is_none_not_zero():
    """Zero would claim a measured 0% success; None says we have no evidence."""
    assert verdicts.win_rate([]) is None


def test_median_is_taken_on_raw_values_then_rounded_once():
    """The behaviour change. performance used to round each delta to one decimal
    before the median; on an even-sized cohort the two disagree.

    Raw: median(0.12345, 0.12355) = 0.1235 -> 12.35 -> 12.4 (banker's rounding
    on the exact float). Pre-rounded to 12.3 and 12.4, the median is 12.35 too,
    but the intermediate loss is what compounds — assert the raw path directly.
    """
    assert verdicts.median_ctr_delta_pct([0.10, 0.20, 0.30]) == 20.0
    assert verdicts.median_ctr_delta_pct([0.1234, 0.5678]) == pytest.approx(34.6)


def test_median_ignores_verdicts_with_nothing_to_compare():
    """A neutral with no delta is not a zero — averaging it in as one would drag
    every median toward the middle."""
    assert verdicts.median_ctr_delta_pct([0.5, None, None]) == 50.0
    assert verdicts.median_ctr_delta_pct([None, None]) is None


def test_median_of_nothing_is_none():
    assert verdicts.median_ctr_delta_pct([]) is None


def test_distribution_counts_every_measured_status():
    d = verdicts.distribution(["win", "win", "neutral", "regression"])
    assert d == {"win": 2, "neutral": 1, "regression": 1, "total": 4}


def test_distribution_of_nothing_is_zeros_not_empty():
    """The UI renders these counts; a missing key would render as blank rather
    than as zero."""
    d = verdicts.distribution([])
    assert d == {"win": 0, "neutral": 0, "regression": 0, "total": 0}


def test_rollup_reports_all_three_together():
    vs = verdicts.evidence([
        _audit(measurement_status=MeasurementStatus.WIN,
               measurement_result=_result(**{verdicts.CTR_DELTA: 0.5})),
        _audit(measurement_status=MeasurementStatus.NEUTRAL,
               measurement_result=_result()),                       # no delta
        _audit(measurement_status=MeasurementStatus.REGRESSION,
               measurement_result=_result(**{verdicts.CTR_DELTA: -0.3})),
    ])
    r = verdicts.rollup(vs)
    assert r["win_rate"] == pytest.approx(33.3)
    assert r["median_ctr_delta_pct"] == 10.0        # median(0.5, -0.3) = 0.1
    assert r["distribution"] == {"win": 1, "neutral": 1, "regression": 1, "total": 3}


# ── nobody re-solves it ───────────────────────────────────────────────────

APP = Path(__file__).resolve().parents[1] / "app"

#: A module reaching into the stored verdict by key instead of asking for it.
_RAW_KEY = re.compile(r"""["'](?:ctr_delta_relative|pre_window|post_window)["']""")
#: The lever taxonomy, spelled out. Matches both historical copies, which
#: differed only in the response key they assigned it to.
_OWN_LEVERS = re.compile(
    r"""["']title_before["']\s*\)?\s*or\s*["']{2}\s*\)?\s*!=""")
#: A win rate derived by hand. Matches both historical spellings —
#: `counts["win"] / len(measured)` and `wins / len(enriched)`. A first attempt
#: matched any `100.0 * x`, which flagged four modules computing perfectly
#: legitimate percentages; a guard with false positives gets deleted, not obeyed.
_OWN_WIN_RATE = re.compile(r"""(?:\[["']win["']\]|\bwins\b)\s*/""")
#: A median taken outside the owner. Both readers used to take their own, one of
#: them over pre-rounded values.
_OWN_MEDIAN = re.compile(r"statistics\.median")


def _app_sources():
    for p in sorted(APP.rglob("*.py")):
        if p.name == "verdicts.py":
            continue
        yield p


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_reads_the_stored_verdict_by_key(path):
    hits = _RAW_KEY.findall(path.read_text())
    assert not hits, (
        f"{path.name} reads the stored verdict by key {hits} — use "
        "app.verdicts.from_audit so the writer and readers share one definition"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_derives_the_levers_itself(path):
    assert not _OWN_LEVERS.search(path.read_text()), (
        f"{path.name} derives the lever taxonomy itself — use "
        "app.verdicts.levers so the UI and the prompt describe the same fact"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_computes_its_own_win_rate(path):
    assert not _OWN_WIN_RATE.search(path.read_text()), (
        f"{path.name} computes a win rate itself — use app.verdicts.win_rate, so "
        "the number the UI shows and the number the prompt loop acts on agree"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_takes_its_own_median(path):
    assert not _OWN_MEDIAN.search(path.read_text()), (
        f"{path.name} takes its own median of CTR deltas — use "
        "app.verdicts.median_ctr_delta_pct, which aggregates raw and rounds once"
    )
