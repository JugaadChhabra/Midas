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


# ── nobody re-solves it ───────────────────────────────────────────────────

APP = Path(__file__).resolve().parents[1] / "app"

#: A module reaching into the stored verdict by key instead of asking for it.
_RAW_KEY = re.compile(r"""["'](?:ctr_delta_relative|pre_window|post_window)["']""")
#: The lever taxonomy, spelled out. Matches both historical copies, which
#: differed only in the response key they assigned it to.
_OWN_LEVERS = re.compile(
    r"""["']title_before["']\s*\)?\s*or\s*["']{2}\s*\)?\s*!=""")


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
