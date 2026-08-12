"""Reach data-day arithmetic and coverage — app/reach.py.

Two of these functions had ZERO tests before the module existed: `certify` and
the contiguous-run count behind it were reachable only through a scheduled job
that does network I/O, so the Phase 0 exit gate — the thing that decides whether
a channel may be measured at all — was never exercised. Everything below except
the last test runs with no mocks.
"""
import re
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import reach

APPLIED = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def _fixed_window():
    """Pin the window length so these tests describe behaviour, not config."""
    with patch.object(reach.settings, "MEASUREMENT_WINDOW_DAYS", 21):
        yield


# ── windows ───────────────────────────────────────────────────────────────

def test_windows_exclude_the_apply_day_and_its_neighbours():
    """Reach data-days roll over on Pacific while `applied` is a UTC date, so
    the adjacent days can contain mixed pre/post exposure."""
    pre, post = reach.window_for(APPLIED)
    assert pre == ("2026-05-10", "2026-05-30")
    assert post == ("2026-06-03", "2026-06-23")
    for w in (pre, post):
        assert APPLIED.isoformat() not in reach.days(w)
        assert "2026-05-31" not in reach.days(w)   # apply day - 1
        assert "2026-06-02" not in reach.days(w)   # apply day + 1


def test_both_windows_are_full_length():
    """Shifted outward, not shortened — otherwise pre and post aren't comparable."""
    pre, post = reach.window_for(APPLIED)
    assert len(reach.days(pre)) == 21
    assert len(reach.days(post)) == 21


def test_the_excluded_band_follows_the_slop_constant():
    """The 2s in the boundaries are slop+1, not a hardcoded lag."""
    with patch.object(reach, "ROLLOVER_SLOP_DAYS", 2):
        pre, post = reach.window_for(APPLIED)
        assert pre[1] == "2026-05-29"          # apply day - 3
        assert post[0] == "2026-06-04"         # apply day + 3
        assert len(reach.days(pre)) == 21      # still full length


def test_days_is_inclusive():
    assert reach.days(("2026-01-01", "2026-01-03")) == \
        ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert reach.days(("2026-01-01", "2026-01-01")) == ["2026-01-01"]


# ── coverage predicate ────────────────────────────────────────────────────

def test_missing_days_is_empty_when_every_day_is_covered():
    pre, post = reach.window_for(APPLIED)
    covered = set(reach.days(pre)) | set(reach.days(post))
    assert reach.missing_days(covered, pre, post) == []


def test_missing_days_names_the_gap():
    pre, post = reach.window_for(APPLIED)
    covered = (set(reach.days(pre)) | set(reach.days(post))) - {post[1]}
    assert reach.missing_days(covered, pre, post) == [post[1]]


def test_missing_days_spans_every_window_it_is_given():
    """One call answers for the whole comparison, not one window at a time."""
    pre, post = reach.window_for(APPLIED)
    assert reach.missing_days(set(), pre, post) == reach.days(pre) + reach.days(post)


def test_missing_days_of_no_windows_is_empty():
    assert reach.missing_days({"2026-01-01"}) == []


# ── frontier ──────────────────────────────────────────────────────────────

def test_frontier_is_the_latest_covered_day():
    assert reach.frontier({"2026-01-01", "2026-03-01", "2026-02-01"}) == "2026-03-01"
    assert reach.frontier(set()) is None


# ── certification ─────────────────────────────────────────────────────────

def _run_of(n: int, start=date(2026, 6, 1)) -> set[str]:
    from datetime import timedelta
    return {(start + timedelta(days=i)).isoformat() for i in range(n)}


def test_certify_needs_a_full_window_behind_the_frontier():
    with patch.object(reach, "coverage", return_value=_run_of(21)):
        assert reach.certify("c1")["certified"] is True
    with patch.object(reach, "coverage", return_value=_run_of(20)):
        assert reach.certify("c1")["certified"] is False


def test_a_week_of_coverage_no_longer_certifies():
    """The bug this commit closes. Seven contiguous days used to pass, then the
    evaluator asked for 42 specific ones and could never get them."""
    with patch.object(reach, "coverage", return_value=_run_of(7)):
        cov = reach.certify("c1")
    assert cov["certified"] is False
    assert len(cov["missing_days"]) == 14


def test_certify_names_the_missing_days():
    """Usually a failed report retry away — the operator needs to know which."""
    covered = _run_of(21) - {"2026-06-10", "2026-06-15"}
    with patch.object(reach, "coverage", return_value=covered):
        cov = reach.certify("c1")
    assert cov["certified"] is False
    assert cov["missing_days"] == ["2026-06-10", "2026-06-15"]
    assert cov["window"] == ("2026-06-01", "2026-06-21")


def test_certify_ignores_history_older_than_the_window():
    """A clean run from months ago says nothing about measuring now."""
    stale = _run_of(40, start=date(2026, 1, 1))
    with patch.object(reach, "coverage", return_value=stale | {"2026-06-30"}):
        cov = reach.certify("c1")
    assert cov["certified"] is False
    assert cov["latest_day"] == "2026-06-30"


def test_a_stale_frontier_does_not_make_certification_easier():
    """It still demands a full window; it just asks about an older apply date."""
    with patch.object(reach, "coverage", return_value=_run_of(21, start=date(2025, 1, 1))):
        cov = reach.certify("c1")
    assert cov["certified"] is True          # 21 consecutive days, however old
    assert cov["latest_day"] == "2025-01-21"  # and the staleness is visible


def test_certify_of_an_unpolled_channel_is_not_an_error():
    with patch.object(reach, "coverage", return_value=set()):
        cov = reach.certify("c1")
    assert cov == {
        "certified": False, "window": None, "missing_days": None,
        "latest_day": None, "covered_total": 0,
    }


# ── the property this refactor exists for ─────────────────────────────────

@pytest.mark.parametrize("label,covered", [
    ("exactly one window",   _run_of(21)),
    ("more than a window",   _run_of(60)),
    ("one short",            _run_of(20)),
    ("a week",               _run_of(7)),
    ("hole in the middle",   _run_of(21) - {"2026-06-11"}),
    ("hole at the frontier", _run_of(22) - {"2026-06-21"}),
])
def test_the_gate_and_the_evaluator_agree(label, covered):
    """The keystone.

    The gate and the evaluator must not be able to disagree about how many
    data-days a comparison needs. Before app/reach.py they were separate walks
    in separate modules: the gate accepted 7 contiguous days anywhere in
    history, while plan_measurement then required 42 specific ones and parked
    the audit until a grace period turned it into a measured-and-flat verdict.

    Stated as a biconditional, so it bites in both directions: certification
    passes for exactly those coverage sets where the audit it vouches for has an
    observable pre window — measured with the evaluator's own predicate, not a
    restatement of it.
    """
    with patch.object(reach, "coverage", return_value=covered):
        cov = reach.certify("c1")

    applied = reach.applied_after(date.fromisoformat(cov["latest_day"]))
    pre, _post = reach.window_for(applied)
    observable = reach.missing_days(covered, pre) == []

    assert cov["certified"] is observable, label


def test_the_certification_window_is_exactly_a_pre_window():
    """The equivalence the keystone rests on, asserted directly."""
    end = date(2026, 6, 21)
    pre, _ = reach.window_for(reach.applied_after(end))
    assert pre == reach.window_ending(end)


# ── values ────────────────────────────────────────────────────────────────

def _day(impressions, ctr):
    return {"impressions": impressions, "ctr": ctr}


def test_weighted_ctr_weights_by_impressions_not_by_day():
    """A low-traffic day's noisy rate must not count as much as a busy day's.

    1 impression at 100% plus 999 at 10% is 10.09%, not the 55% a mean of the
    two daily rates would give.
    """
    imp, ctr = reach.weighted_ctr([_day(1, 1.0), _day(999, 0.10)])
    assert imp == 1000
    assert ctr == pytest.approx(0.1009)


def test_weighted_ctr_of_a_single_day_is_that_day():
    assert reach.weighted_ctr([_day(500, 0.04)]) == (500, pytest.approx(0.04))


def test_weighted_ctr_of_nothing_is_zero_impressions_and_no_signal():
    """0/0 is no signal, not 0% CTR — the distinction Loop 1 judges on."""
    assert reach.weighted_ctr([]) == (0, None)


def test_weighted_ctr_of_impressions_without_clicks_is_zero_not_none():
    """Genuine zero: the video was shown and nobody clicked. Distinct from
    never having been shown."""
    assert reach.weighted_ctr([_day(500, 0.0)]) == (500, 0.0)


def test_weighted_ctr_ignores_zero_impression_days():
    imp, ctr = reach.weighted_ctr([_day(0, 0.0), _day(100, 0.05)])
    assert (imp, ctr) == (100, pytest.approx(0.05))


def test_aggregate_reads_one_video_over_the_window():
    sb = MagicMock()
    with patch.object(reach, "supabase", return_value=sb), \
         patch.object(reach, "all_rows", return_value=[_day(100, 0.02), _day(100, 0.04)]):
        assert reach.aggregate("v1", ("2026-06-01", "2026-06-21")) == (200, pytest.approx(0.03))

    sel = sb.table.return_value.select.return_value
    sb.table.assert_called_once_with("video_reach_daily")
    sel.eq.assert_called_once_with("video_id", "v1")
    sel.eq.return_value.gte.assert_called_once_with("date", "2026-06-01")
    sel.eq.return_value.gte.return_value.lte.assert_called_once_with("date", "2026-06-21")


# ── the one I/O function ──────────────────────────────────────────────────

def test_coverage_reads_the_ledger_scoped_to_the_channel():
    """Shape, not rows. The ledger has no `id` column, so paging must be
    ordered by report_id or all_rows' total order is undefined."""
    sb = MagicMock()
    eq = sb.table.return_value.select.return_value.eq.return_value
    with patch.object(reach, "supabase", return_value=sb), \
         patch.object(reach, "all_rows", return_value=[
             {"data_date": "2026-06-01"}, {"data_date": "2026-06-02"},
         ]) as all_rows:
        assert reach.coverage("c1") == {"2026-06-01", "2026-06-02"}

    sb.table.assert_called_once_with("reporting_reports_ingested")
    sb.table.return_value.select.assert_called_once_with("data_date")
    sb.table.return_value.select.return_value.eq.assert_called_once_with("channel_id", "c1")
    assert all_rows.call_args[0][0] is eq
    assert all_rows.call_args[1]["order_by"] == "report_id"


# ── nobody re-solves it ───────────────────────────────────────────────────
#
# Same discipline as tests/test_rows.py: the point of the module is that these
# facts have ONE owner, and a source scan is what keeps a second copy from
# appearing. Both patterns below existed in two places before this module.

APP = Path(__file__).resolve().parents[1] / "app"

_WINDOW_LENGTH = re.compile(r"settings\.MEASUREMENT_WINDOW_DAYS")
_MISSING_DAYS = re.compile(r"for\s+\w+\s+in\s+[\w.\[\]()]+\s+if\s+\w+\s+not\s+in\s+cover")
#: The impression-weighted CTR formula, reconstructed by hand. Existed twice —
#: here and in reporting_poll's backfill — each claiming in prose to match the
#: other. A backfilled window and the baseline judged against it must agree.
#: Matches both historical spellings — `clicks / impressions` in measurement and
#: `a["clicks"] / a["impressions"]` in the backfill. A first version caught only
#: the former, which is half a guard.
_WEIGHTED_CTR = re.compile(r"""clicks["'\]\s]*/\s*[\w.\["']*impressions""")


def _app_sources():
    for p in sorted(APP.rglob("*.py")):
        if p.name == "reach.py":
            continue
        yield p


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_declares_its_own_reach_window_length(path):
    """A second reader of MEASUREMENT_WINDOW_DAYS is how the gate and the judge
    came to disagree about how many data-days a comparison needs."""
    assert not _WINDOW_LENGTH.search(path.read_text()), (
        f"{path.name} reads settings.MEASUREMENT_WINDOW_DAYS directly — build "
        "the window with app.reach.window_for so its length has one owner"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_hand_rolls_the_coverage_diff(path):
    assert not _MISSING_DAYS.search(path.read_text()), (
        f"{path.name} hand-rolls the covered-day diff — use "
        "app.reach.missing_days so the predicate has one owner"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_rebuilds_the_weighted_ctr(path):
    assert not _WEIGHTED_CTR.search(path.read_text()), (
        f"{path.name} reconstructs the impression-weighted CTR — use "
        "app.reach.weighted_ctr so a backfilled window and the baseline judged "
        "against it cannot disagree"
    )
